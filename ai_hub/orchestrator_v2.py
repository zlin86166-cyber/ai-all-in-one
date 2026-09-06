from __future__ import annotations

import json
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

from .db import Database, utcnow
from .task_manager_v2 import TaskManager, future_iso

PLAN_SCHEMA = {"summary": "一句話策略", "steps": [{"id": "s1", "title": "短標題",
    "instruction": "可獨立執行且有驗收標準的完整指令", "provider_id": "允許清單內 ID",
    "depends_on": [], "mode": "analysis|research|implementation|test|review",
    "parallel_safe": False, "acceptance": ["可驗證條件"]}]}


class CollaborationOrchestrator:
    def __init__(self, database: Database, tasks: TaskManager, max_parallel: callable):
        self.database, self.tasks, self.max_parallel = database, tasks, max_parallel
        self._recovery_done = False

    def launch(self, goal: str, provider_ids: list[str], project: dict[str, Any], conversation_id: str,
               permission_mode: str, feasibility: dict[str, Any], web_access: bool, peer_review: bool,
               selected_files: list[str] | None = None, resume_state: dict[str, Any] | None = None,
               retry_of: str | None = None) -> dict[str, Any]:
        selected_files = selected_files or []
        predicted = max(60, int(feasibility.get("estimated_seconds", 120) * 1.8))
        meta = {"provider_ids": provider_ids, "feasibility": feasibility, "goal": goal,
                "permission_mode": permission_mode, "web_access": web_access,
                "peer_review": peer_review, "selected_files": selected_files,
                "checkpoint": resume_state or {}, "retry_of": retry_of, "recoverable": True}
        parent = self.database.create_task("collaboration", "AI 協作任務", goal, conversation_id,
            project.get("id"), predicted, future_iso(predicted), metadata=meta)
        cancel = threading.Event()
        thread = threading.Thread(target=self._worker,
            args=(parent["id"], goal, provider_ids, project, conversation_id, permission_mode,
                  feasibility, web_access, peer_review, selected_files, cancel, resume_state),
            name=f"collaboration-{parent['id']}", daemon=True)
        self.tasks.register_parent(parent["id"], cancel, thread)
        thread.start()
        return parent

    def recover_incomplete(self) -> list[dict[str, Any]]:
        if self._recovery_done:
            return []
        self._recovery_done = True
        recovered = []
        for old in self.database.list_tasks(active_only=True, limit=500):
            if old.get("provider_id") != "collaboration":
                continue
            meta = old.get("metadata") or {}
            self.database.update_task(old["id"], status="interrupted", stage="程序重啟，準備續跑",
                                      error="AI Hub 非正常結束；協作流程已從最近安全 checkpoint 復原。", completed_at=utcnow())
            project = self.database.get_project(str(old.get("project_id") or ""))
            if not project or not isinstance(meta, dict) or not meta.get("provider_ids"):
                continue
            recovered.append(self.launch(str(meta.get("goal") or old.get("prompt") or ""), list(meta["provider_ids"]),
                project, str(old.get("conversation_id") or ""), str(meta.get("permission_mode") or "workspace"),
                dict(meta.get("feasibility") or {}), bool(meta.get("web_access", True)), bool(meta.get("peer_review", True)),
                list(meta.get("selected_files") or []), dict(meta.get("checkpoint") or {}), retry_of=old["id"]))
        return recovered

    def _checkpoint(self, parent_id: str, base: dict[str, Any], plan: dict[str, Any], completed: dict[str, Any], reviews: list[dict[str, Any]]) -> None:
        self.database.update_task(parent_id, metadata_json={**base, "checkpoint": {"plan": plan, "completed": completed, "reviews": reviews}})

    def _worker(self, parent_id: str, goal: str, provider_ids: list[str], project: dict[str, Any],
                conversation_id: str, permission_mode: str, feasibility: dict[str, Any], web_access: bool,
                peer_review: bool, selected_files: list[str], cancel: threading.Event,
                resume_state: dict[str, Any] | None) -> None:
        started = time.monotonic()
        base_meta = {"provider_ids": provider_ids, "feasibility": feasibility, "goal": goal,
                     "permission_mode": permission_mode, "web_access": web_access,
                     "peer_review": peer_review, "selected_files": selected_files, "recoverable": True}
        self.database.update_task(parent_id, status="running", stage="由主協調 AI 排定工作", progress=2, started_at=utcnow())
        self.database.add_task_event(parent_id, "協作模式已啟動；只使用使用者選取的 AI。", progress=2)
        try:
            if not provider_ids:
                raise ValueError("未選取任何 AI。")
            planner_id = provider_ids[0]
            checkpoint = resume_state or {}
            plan = checkpoint.get("plan") if isinstance(checkpoint, dict) else None
            completed = dict(checkpoint.get("completed") or {}) if isinstance(checkpoint, dict) else {}
            reviews = list(checkpoint.get("reviews") or []) if isinstance(checkpoint, dict) else []
            if not plan:
                _, result = self.tasks.run_inline(planner_id, "規劃先後順序與分工",
                    self._plan_prompt(goal, provider_ids, feasibility), project, conversation_id, "observe",
                    max(30, int(feasibility.get("estimated_seconds", 60) * .35)), parent_id,
                    web_access=web_access, selected_files=selected_files)
                plan = self._parse_plan(result.text, provider_ids)
                self._checkpoint(parent_id, base_meta, plan, completed, reviews)
            remaining = {item["id"]: item for item in plan["steps"] if item["id"] not in completed}
            total = max(1, len(plan["steps"]))
            while remaining:
                if cancel.is_set():
                    raise InterruptedError("協作工作已停止。")
                ready = [item for item in remaining.values() if all(dep in completed for dep in item["depends_on"])]
                if not ready:
                    raise ValueError("AI 規劃含有循環或遺失相依。")
                parallel = [item for item in ready if item.get("parallel_safe") and item.get("mode") in {"analysis","research","test","review"}]
                batch = parallel[:max(1, int(self.max_parallel()))] if parallel else [ready[0]]
                outcomes = {}
                if len(batch) == 1:
                    item = batch[0]
                    outcomes[item["id"]] = self._run_step(parent_id, goal, item, completed, project,
                        conversation_id, permission_mode, web_access, selected_files)
                else:
                    with ThreadPoolExecutor(max_workers=len(batch), thread_name_prefix="ai-collab") as executor:
                        futures = {executor.submit(self._run_step, parent_id, goal, item, completed, project,
                            conversation_id, permission_mode, web_access, selected_files): item for item in batch}
                        for future in as_completed(futures):
                            outcomes[futures[future]["id"]] = future.result()
                completed.update(outcomes)
                for key in outcomes:
                    remaining.pop(key, None)
                self._checkpoint(parent_id, base_meta, plan, completed, reviews)
                progress = 12 + round(len([k for k in completed if k in {s['id'] for s in plan['steps']}]) / total * 66)
                self.database.update_task(parent_id, stage=f"已完成 {min(total, len(completed))}/{total} 個步驟", progress=min(progress, 78))

            if peer_review and len(provider_ids) > 1:
                reviewer_id = provider_ids[1]
                passed = False
                for cycle in range(3):
                    self.database.update_task(parent_id, stage=f"品質閘門 {cycle + 1}/3", progress=80 + cycle * 3)
                    _, rr = self.tasks.run_inline(reviewer_id, "獨立驗收成果", self._review_prompt(goal, plan, completed),
                        project, conversation_id, "observe", 60, parent_id, web_access=False, selected_files=selected_files)
                    review = self._parse_review(rr.text)
                    reviews.append({"provider_id": reviewer_id, **review})
                    self._checkpoint(parent_id, base_meta, plan, completed, reviews)
                    if review["verdict"] == "pass":
                        passed = True
                        break
                    if cycle >= 2:
                        break
                    _, fix = self.tasks.run_inline(planner_id, f"修正驗收問題 {cycle + 1}",
                        self._fix_prompt(goal, completed, review), project, conversation_id, permission_mode,
                        120, parent_id, web_access=False, selected_files=selected_files)
                    completed[f"remediation-{cycle + 1}"] = {"title": "品質修正", "provider_id": planner_id,
                        "result": fix.text}
                if not passed:
                    raise ValueError("Peer Review 品質閘門未通過；工作不會被標記為完成。")

            if cancel.is_set():
                raise InterruptedError("協作工作已停止。")
            _, final = self.tasks.run_inline(planner_id, "彙整協作結果",
                self._summary_prompt(goal, plan, completed, reviews), project, conversation_id, "observe",
                45, parent_id, web_access=False, selected_files=selected_files)
            duration = time.monotonic() - started
            meta = {**base_meta, "plan": plan, "steps": completed, "reviews": reviews,
                    "duration_seconds": round(duration, 1), "review_passed": bool(not peer_review or len(provider_ids) < 2 or reviews[-1].get("verdict") == "pass"),
                    "acceptance_passed": True}
            self.database.update_task(parent_id, status="completed", stage="協作完成", progress=100,
                result=final.text, metadata_json=meta, completed_at=utcnow())
            self.database.add_task_event(parent_id, "協作步驟與品質閘門完成。", progress=100)
            self.database.add_message(conversation_id, "assistant", final.text, provider_id="collaboration",
                                      metadata={"task_id": parent_id, "collaboration": meta})
            self.database.add_metric("collaboration", "large", int(feasibility.get("estimated_seconds", 120)), duration, True)
        except Exception as error:
            duration = time.monotonic() - started
            cancelled = isinstance(error, InterruptedError) or cancel.is_set()
            self.database.update_task(parent_id, status="cancelled" if cancelled else "failed",
                stage="已停止" if cancelled else "協作失敗", error=str(error), completed_at=utcnow())
            self.database.add_task_event(parent_id, str(error), level="warning" if cancelled else "error")
            if not cancelled:
                self.database.add_message(conversation_id, "assistant", f"AI 協作失敗：{error}", provider_id="collaboration",
                                          metadata={"task_id": parent_id, "error": True})
            self.database.add_metric("collaboration", "large", int(feasibility.get("estimated_seconds", 120)), duration, False)
        finally:
            self.tasks.unregister_parent(parent_id)

    def _run_step(self, parent_id: str, goal: str, item: dict[str, Any], completed: dict[str, Any],
                  project: dict[str, Any], conversation_id: str, permission_mode: str,
                  web_access: bool, selected_files: list[str]) -> dict[str, Any]:
        deps = "\n\n".join(f"前置步驟 {key}：\n{completed[key]['result'][-5000:]}" for key in item["depends_on"] if key in completed)
        prompt = (f"你是協作流程中的執行 AI。\n整體目標：{goal}\n\n你的工作：{item['instruction']}\n"
                  f"模式：{item['mode']}\n驗收條件：{json.dumps(item['acceptance'], ensure_ascii=False)}\n"
                  "只在目前授權範圍完成工作；完成後必須執行可行的驗證並提供證據。" + (f"\n\n{deps}" if deps else ""))
        task, result = self.tasks.run_inline(item["provider_id"], item["title"], prompt, project, conversation_id,
            permission_mode, 90, parent_id, web_access=web_access and item["mode"] in {"analysis","research"},
            selected_files=selected_files)
        return {"title": item["title"], "provider_id": item["provider_id"], "task_id": task["id"], "result": result.text,
                "acceptance": item["acceptance"]}

    @staticmethod
    def _plan_prompt(goal: str, provider_ids: list[str], feasibility: dict[str, Any]) -> str:
        return ("你是多 AI 協作主協調者。只使用允許清單 AI；修改相同檔案必須串行，只有研究/分析/測試/審查可 parallel_safe。"
                "每一步都要有客觀 acceptance。只輸出 JSON。\n\n" +
                f"目標：{goal}\n允許：{json.dumps(provider_ids, ensure_ascii=False)}\n可行性：{json.dumps(feasibility, ensure_ascii=False)}\n格式：{json.dumps(PLAN_SCHEMA, ensure_ascii=False)}")

    @staticmethod
    def _parse_plan(text: str, allowed: list[str]) -> dict[str, Any]:
        cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip(), flags=re.I)
        try:
            payload = json.loads(cleaned)
        except json.JSONDecodeError:
            start, end = cleaned.find("{"), cleaned.rfind("}")
            if start < 0 or end <= start:
                raise ValueError("主協調 AI 未回傳合法 JSON 計畫。")
            payload = json.loads(cleaned[start:end+1])
        raw_steps = payload.get("steps")
        if not isinstance(raw_steps, list) or not raw_steps:
            raise ValueError("工作計畫沒有步驟。")
        steps, used = [], set()
        for index, raw in enumerate(raw_steps[:12]):
            sid = re.sub(r"[^a-zA-Z0-9_-]", "", str(raw.get("id") or f"s{index+1}")) or f"s{index+1}"
            if sid in used: sid = f"s{index+1}"
            used.add(sid)
            provider = str(raw.get("provider_id") or allowed[index % len(allowed)])
            if provider not in allowed: raise ValueError(f"計畫使用未選取 AI：{provider}")
            mode = str(raw.get("mode") or "implementation")
            if mode not in {"analysis","research","implementation","test","review"}: mode = "implementation"
            acceptance = raw.get("acceptance") if isinstance(raw.get("acceptance"), list) else [raw.get("acceptance") or "提供驗證證據"]
            steps.append({"id": sid, "title": str(raw.get("title") or sid)[:120],
                "instruction": str(raw.get("instruction") or raw.get("title") or "完成指定工作"), "provider_id": provider,
                "depends_on": [str(x) for x in raw.get("depends_on", [])], "mode": mode,
                "parallel_safe": bool(raw.get("parallel_safe", False)), "acceptance": [str(x) for x in acceptance[:8]]})
        valid = {s["id"] for s in steps}
        for step in steps:
            step["depends_on"] = [d for d in step["depends_on"] if d in valid and d != step["id"]]
        return {"summary": str(payload.get("summary") or ""), "steps": steps}

    @staticmethod
    def _review_prompt(goal: str, plan: dict[str, Any], completed: dict[str, Any]) -> str:
        return ("你是獨立品質閘門。不要因為執行 AI 宣稱完成就通過；依 acceptance、測試證據、變更一致性判定。"
                "只輸出 JSON：{\"verdict\":\"pass|needs_fix|fail\",\"issues\":[...],\"evidence\":[...]}。\n\n"
                f"目標：{goal}\n計畫：{json.dumps(plan, ensure_ascii=False)}\n成果：{json.dumps(completed, ensure_ascii=False)}")

    @staticmethod
    def _parse_review(text: str) -> dict[str, Any]:
        cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip(), flags=re.I)
        try: payload = json.loads(cleaned)
        except json.JSONDecodeError:
            start, end = cleaned.find("{"), cleaned.rfind("}")
            payload = json.loads(cleaned[start:end+1]) if start >= 0 and end > start else {"verdict":"fail","issues":["Reviewer 未回傳合法 JSON"],"evidence":[]}
        verdict = str(payload.get("verdict") or "fail").lower()
        if verdict not in {"pass","needs_fix","fail"}: verdict = "fail"
        return {"verdict": verdict, "issues": [str(x) for x in (payload.get("issues") or [])][:20],
                "evidence": [str(x) for x in (payload.get("evidence") or [])][:20]}

    @staticmethod
    def _fix_prompt(goal: str, completed: dict[str, Any], review: dict[str, Any]) -> str:
        return f"品質閘門未通過。目標：{goal}\n問題：{json.dumps(review, ensure_ascii=False)}\n既有成果：{json.dumps(completed, ensure_ascii=False)}\n請直接修正並重新執行必要測試，不要只解釋。"

    @staticmethod
    def _summary_prompt(goal: str, plan: dict[str, Any], completed: dict[str, Any], reviews: list[dict[str, Any]]) -> str:
        return f"彙整已通過品質閘門的結果。目標：{goal}\n計畫：{json.dumps(plan, ensure_ascii=False)}\n成果：{json.dumps(completed, ensure_ascii=False)}\n驗收：{json.dumps(reviews, ensure_ascii=False)}\n說明做了什麼、驗證證據、仍存在的平台限制。"
