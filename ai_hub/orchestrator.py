from __future__ import annotations

import json
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

from .db import Database, utcnow
from .tasks import TaskManager, future_iso


PLAN_SCHEMA = {
    "summary": "一句話策略",
    "steps": [
        {
            "id": "s1",
            "title": "短標題",
            "instruction": "可獨立執行且有驗收標準的完整指令",
            "provider_id": "只可使用允許清單內的 ID",
            "depends_on": [],
            "mode": "analysis|research|implementation|test|review",
            "parallel_safe": False,
            "acceptance": ["可驗證條件"],
        }
    ],
}


class CollaborationOrchestrator:
    def __init__(self, database: Database, tasks: TaskManager, max_parallel: callable):
        self.database = database
        self.tasks = tasks
        self.max_parallel = max_parallel

    def launch(
        self,
        goal: str,
        provider_ids: list[str],
        project: dict[str, Any],
        conversation_id: str,
        permission_mode: str,
        feasibility: dict[str, Any],
        web_access: bool,
        peer_review: bool,
    ) -> dict[str, Any]:
        predicted = max(60, int(feasibility.get("estimated_seconds", 120) * 1.8))
        parent = self.database.create_task(
            provider_id="collaboration",
            title="AI 協作任務",
            prompt=goal,
            conversation_id=conversation_id,
            project_id=project.get("id"),
            predicted_seconds=predicted,
            predicted_end_at=future_iso(predicted),
            metadata={"provider_ids": provider_ids, "feasibility": feasibility},
        )
        cancel = threading.Event()
        thread = threading.Thread(
            target=self._worker,
            args=(
                parent["id"], goal, provider_ids, project, conversation_id, permission_mode,
                feasibility, web_access, peer_review, cancel,
            ),
            name=f"collaboration-{parent['id']}",
            daemon=True,
        )
        self.tasks.register_parent(parent["id"], cancel, thread)
        thread.start()
        return parent

    def _worker(
        self,
        parent_id: str,
        goal: str,
        provider_ids: list[str],
        project: dict[str, Any],
        conversation_id: str,
        permission_mode: str,
        feasibility: dict[str, Any],
        web_access: bool,
        peer_review: bool,
        cancel: threading.Event,
    ) -> None:
        started = time.monotonic()
        self.database.update_task(
            parent_id, status="running", stage="由主協調 AI 排定工作", progress=2, started_at=utcnow()
        )
        self.database.add_task_event(parent_id, "協作模式已啟動；只會使用使用者選取的 AI。", progress=2)
        try:
            if not provider_ids:
                raise ValueError("未選取任何 AI。")
            planner_id = provider_ids[0]
            plan_prompt = self._plan_prompt(goal, provider_ids, feasibility)
            _, plan_result = self.tasks.run_inline(
                planner_id,
                "規劃先後順序與分工",
                plan_prompt,
                project,
                conversation_id,
                permission_mode="observe",
                predicted_seconds=max(30, int(feasibility.get("estimated_seconds", 60) * 0.35)),
                parent_task_id=parent_id,
                web_access=web_access,
            )
            if cancel.is_set():
                raise InterruptedError("協作工作已停止。")
            plan = self._parse_plan(plan_result.text, provider_ids)
            self.database.update_task(
                parent_id,
                stage=f"執行 {len(plan['steps'])} 個協作步驟",
                progress=12,
                metadata_json={
                    "provider_ids": provider_ids,
                    "feasibility": feasibility,
                    "plan": plan,
                },
            )
            self.database.add_task_event(
                parent_id, f"規劃完成：{plan.get('summary', '')}", progress=12
            )
            completed: dict[str, dict[str, Any]] = {}
            remaining = {item["id"]: item for item in plan["steps"]}
            total = max(1, len(remaining))
            while remaining:
                if cancel.is_set():
                    raise InterruptedError("協作工作已停止。")
                ready = [
                    item for item in remaining.values()
                    if all(dependency in completed for dependency in item["depends_on"])
                ]
                if not ready:
                    raise ValueError("AI 規劃含有循環相依，無法安全執行。")
                parallel = [
                    item for item in ready
                    if item.get("parallel_safe") and item.get("mode") in {"analysis", "research", "test", "review"}
                ]
                batch = parallel[: max(1, int(self.max_parallel()))] if parallel else [ready[0]]
                outcomes: dict[str, dict[str, Any]] = {}
                if len(batch) == 1:
                    item = batch[0]
                    outcomes[item["id"]] = self._run_step(
                        parent_id, goal, item, completed, project, conversation_id,
                        permission_mode, web_access,
                    )
                else:
                    self.database.add_task_event(
                        parent_id,
                        "並行執行：" + "、".join(item["title"] for item in batch),
                        progress=None,
                    )
                    with ThreadPoolExecutor(max_workers=len(batch), thread_name_prefix="ai-collab") as executor:
                        futures = {
                            executor.submit(
                                self._run_step,
                                parent_id,
                                goal,
                                item,
                                completed,
                                project,
                                conversation_id,
                                permission_mode,
                                web_access,
                            ): item
                            for item in batch
                        }
                        for future in as_completed(futures):
                            item = futures[future]
                            outcomes[item["id"]] = future.result()
                for step_id, outcome in outcomes.items():
                    completed[step_id] = outcome
                    remaining.pop(step_id, None)
                progress = 12 + round((len(completed) / total) * (66 if peer_review else 76))
                self.database.update_task(
                    parent_id,
                    stage=f"已完成 {len(completed)}/{total} 個步驟",
                    progress=min(progress, 88),
                )
            reviews: list[dict[str, Any]] = []
            if peer_review and len(provider_ids) > 1 and not cancel.is_set():
                self.database.update_task(parent_id, stage="交叉監看與驗證", progress=82)
                reviewer_id = provider_ids[1]
                review_prompt = self._review_prompt(goal, plan, completed)
                _, review_result = self.tasks.run_inline(
                    reviewer_id,
                    "交叉檢查其他 AI 的成果",
                    review_prompt,
                    project,
                    conversation_id,
                    permission_mode=permission_mode,
                    predicted_seconds=max(40, int(feasibility.get("estimated_seconds", 90) * 0.4)),
                    parent_task_id=parent_id,
                    web_access=False,
                )
                reviews.append({"provider_id": reviewer_id, "result": review_result.text})
            if cancel.is_set():
                raise InterruptedError("協作工作已停止。")
            self.database.update_task(parent_id, stage="彙整成果與驗收證據", progress=91)
            final_prompt = self._summary_prompt(goal, plan, completed, reviews)
            _, final_result = self.tasks.run_inline(
                planner_id,
                "彙整協作結果",
                final_prompt,
                project,
                conversation_id,
                permission_mode="observe",
                predicted_seconds=45,
                parent_task_id=parent_id,
                web_access=False,
            )
            duration = time.monotonic() - started
            metadata = {
                "provider_ids": provider_ids,
                "feasibility": feasibility,
                "plan": plan,
                "steps": completed,
                "reviews": reviews,
                "duration_seconds": round(duration, 1),
            }
            self.database.update_task(
                parent_id,
                status="completed",
                stage="協作完成",
                progress=100,
                result=final_result.text,
                metadata_json=metadata,
                completed_at=utcnow(),
            )
            self.database.add_task_event(parent_id, "全部 AI 協作步驟與交叉驗證完成。", progress=100)
            self.database.add_message(
                conversation_id,
                "assistant",
                final_result.text,
                provider_id="collaboration",
                metadata={"task_id": parent_id, "collaboration": metadata},
            )
            self.database.add_metric(
                "collaboration", "large", int(feasibility.get("estimated_seconds", 120)), duration, True
            )
        except Exception as error:
            duration = time.monotonic() - started
            cancelled = isinstance(error, InterruptedError) or cancel.is_set()
            self.database.update_task(
                parent_id,
                status="cancelled" if cancelled else "failed",
                stage="已停止" if cancelled else "協作失敗",
                error=str(error),
                completed_at=utcnow(),
            )
            self.database.add_task_event(
                parent_id, str(error), level="warning" if cancelled else "error"
            )
            if not cancelled:
                self.database.add_message(
                    conversation_id,
                    "assistant",
                    f"AI 協作失敗：{error}",
                    provider_id="collaboration",
                    metadata={"task_id": parent_id, "error": True},
                )
            self.database.add_metric(
                "collaboration", "large", int(feasibility.get("estimated_seconds", 120)), duration, False
            )
        finally:
            self.tasks.unregister_parent(parent_id)

    def _run_step(
        self,
        parent_id: str,
        goal: str,
        item: dict[str, Any],
        completed: dict[str, dict[str, Any]],
        project: dict[str, Any],
        conversation_id: str,
        permission_mode: str,
        web_access: bool,
    ) -> dict[str, Any]:
        dependency_notes = "\n\n".join(
            f"前置步驟 {key} 的結果：\n{completed[key]['result'][-5000:]}"
            for key in item["depends_on"] if key in completed
        )
        prompt = (
            f"你是協作流程中的執行 AI。\n"
            f"整體目標：{goal}\n\n"
            f"你的工作：{item['instruction']}\n"
            f"模式：{item['mode']}\n"
            f"驗收條件：{json.dumps(item['acceptance'], ensure_ascii=False)}\n"
            f"請直接在目前專案完成工作並自行驗證。不要擴張使用者原意，不要撤銷其他 AI 的既有變更。"
            + (f"\n\n{dependency_notes}" if dependency_notes else "")
        )
        task, result = self.tasks.run_inline(
            item["provider_id"],
            item["title"],
            prompt,
            project,
            conversation_id,
            permission_mode,
            predicted_seconds=90,
            parent_task_id=parent_id,
            web_access=web_access and item["mode"] in {"analysis", "research"},
        )
        return {
            "title": item["title"],
            "provider_id": item["provider_id"],
            "task_id": task["id"],
            "result": result.text,
        }

    @staticmethod
    def _plan_prompt(goal: str, provider_ids: list[str], feasibility: dict[str, Any]) -> str:
        return (
            "你是多 AI 協作的主協調者。先判斷先做什麼、後做什麼、交給誰，"
            "而且只能使用允許清單內的 AI。把會修改相同檔案的工作設為相依；只有純研究、分析、測試或審查可標記 parallel_safe=true。"
            "每步都要有可驗證的 acceptance。不得加入使用者沒有要求的大型產品方向。\n\n"
            f"使用者目標：{goal}\n"
            f"允許的 provider_id：{json.dumps(provider_ids, ensure_ascii=False)}\n"
            f"預先成功性評估：{json.dumps(feasibility, ensure_ascii=False)}\n\n"
            "只輸出一個合法 JSON 物件，不要 Markdown。格式：\n"
            f"{json.dumps(PLAN_SCHEMA, ensure_ascii=False)}"
        )

    @staticmethod
    def _parse_plan(text: str, allowed: list[str]) -> dict[str, Any]:
        cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip(), flags=re.IGNORECASE)
        try:
            payload = json.loads(cleaned)
        except json.JSONDecodeError:
            start, end = cleaned.find("{"), cleaned.rfind("}")
            if start < 0 or end <= start:
                raise ValueError("主協調 AI 未回傳可解析的 JSON 工作計畫。")
            payload = json.loads(cleaned[start : end + 1])
        raw_steps = payload.get("steps")
        if not isinstance(raw_steps, list) or not raw_steps:
            raise ValueError("工作計畫沒有任何步驟。")
        steps: list[dict[str, Any]] = []
        used_ids: set[str] = set()
        for index, raw in enumerate(raw_steps[:12]):
            step_id = re.sub(r"[^a-zA-Z0-9_-]", "", str(raw.get("id") or f"s{index + 1}"))
            if not step_id or step_id in used_ids:
                step_id = f"s{index + 1}"
            used_ids.add(step_id)
            provider_id = str(raw.get("provider_id") or allowed[index % len(allowed)])
            if provider_id not in allowed:
                raise ValueError(f"計畫試圖使用未選取的 AI：{provider_id}")
            mode = str(raw.get("mode") or "implementation")
            if mode not in {"analysis", "research", "implementation", "test", "review"}:
                mode = "implementation"
            acceptance = raw.get("acceptance")
            if not isinstance(acceptance, list):
                acceptance = [str(acceptance or "完成指令並提供驗證證據")]
            steps.append(
                {
                    "id": step_id,
                    "title": str(raw.get("title") or f"步驟 {index + 1}")[:120],
                    "instruction": str(raw.get("instruction") or raw.get("title") or "完成指定工作"),
                    "provider_id": provider_id,
                    "depends_on": [str(item) for item in raw.get("depends_on", [])],
                    "mode": mode,
                    "parallel_safe": bool(raw.get("parallel_safe", False)),
                    "acceptance": [str(item) for item in acceptance[:8]],
                }
            )
        valid_ids = {item["id"] for item in steps}
        for item in steps:
            item["depends_on"] = [dependency for dependency in item["depends_on"] if dependency in valid_ids and dependency != item["id"]]
        return {"summary": str(payload.get("summary") or "AI 協作計畫"), "steps": steps}

    @staticmethod
    def _review_prompt(
        goal: str, plan: dict[str, Any], completed: dict[str, dict[str, Any]]
    ) -> str:
        summaries = [
            {"step": key, "provider": value["provider_id"], "result": value["result"][-6000:]}
            for key, value in completed.items()
        ]
        return (
            "你是另一個被使用者選取的監看 AI。請檢查其他 AI 的成果與目前專案實際狀態，"
            "執行最相關的測試。只修正能證明的缺陷；保持使用者原意與既有介面方向。"
            "最後列出測試命令、結果、修正與尚未驗證事項。\n\n"
            f"目標：{goal}\n計畫：{json.dumps(plan, ensure_ascii=False)}\n"
            f"執行摘要：{json.dumps(summaries, ensure_ascii=False)}"
        )

    @staticmethod
    def _summary_prompt(
        goal: str,
        plan: dict[str, Any],
        completed: dict[str, dict[str, Any]],
        reviews: list[dict[str, Any]],
    ) -> str:
        compact = [
            {"step": key, "provider": value["provider_id"], "result": value["result"][-5000:]}
            for key, value in completed.items()
        ]
        return (
            "彙整這次多 AI 工作。不要再修改檔案。用繁體中文先給完成結果，再列驗證證據、"
            "真正未完成或需帳號同意的事項；不要把未測試的能力說成已完成。\n\n"
            f"原始目標：{goal}\n計畫：{json.dumps(plan, ensure_ascii=False)}\n"
            f"各步成果：{json.dumps(compact, ensure_ascii=False)}\n"
            f"交叉審查：{json.dumps(reviews, ensure_ascii=False)}"
        )
