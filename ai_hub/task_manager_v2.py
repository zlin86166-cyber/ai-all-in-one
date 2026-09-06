from __future__ import annotations

import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from .db import Database, utcnow
from .providers import ProviderContext, ProviderRegistry, ProviderResult
from .workspace_guard import ScopedWorkspaceGuard


def future_iso(seconds: int) -> str:
    return (datetime.now(timezone.utc) + timedelta(seconds=seconds)).isoformat(timespec="seconds")


class TaskManager:
    def __init__(self, database: Database, providers: ProviderRegistry):
        self.database = database
        self.providers = providers
        self._cancel_events: dict[str, threading.Event] = {}
        self._threads: dict[str, threading.Thread] = {}
        self._lock = threading.RLock()
        self._recovery_done = False

    def launch(self, provider_id: str, title: str, prompt: str, project: dict[str, Any],
               conversation_id: str | None, permission_mode: str, predicted_seconds: int,
               selected_files: list[str] | None = None, web_access: bool = True,
               parent_task_id: str | None = None, metadata: dict[str, Any] | None = None,
               publish_message: bool = True) -> dict[str, Any]:
        selected_files = selected_files or []
        meta = dict(metadata or {})
        attempt = int(meta.get("attempt") or 1)
        meta.setdefault("recoverable", provider_id not in {"comfyui-image"})
        meta["attempt"] = attempt
        meta["resume_payload"] = {
            "provider_id": provider_id, "title": title, "prompt": prompt,
            "project_id": project.get("id"), "conversation_id": conversation_id,
            "permission_mode": permission_mode, "predicted_seconds": predicted_seconds,
            "selected_files": selected_files, "web_access": web_access,
            "publish_message": publish_message,
        }
        task = self.database.create_task(provider_id, title, prompt, conversation_id, project.get("id"),
                                         predicted_seconds, future_iso(predicted_seconds),
                                         parent_task_id=parent_task_id, metadata=meta)
        self._spawn(task["id"], provider_id, prompt, project, conversation_id, permission_mode,
                    predicted_seconds, selected_files, web_access, publish_message)
        return task

    def _spawn(self, task_id: str, provider_id: str, prompt: str, project: dict[str, Any],
               conversation_id: str | None, permission_mode: str, predicted_seconds: int,
               selected_files: list[str], web_access: bool, publish_message: bool) -> None:
        cancel = threading.Event()
        thread = threading.Thread(target=self._worker,
            args=(task_id, provider_id, prompt, project, conversation_id, permission_mode,
                  predicted_seconds, selected_files, web_access, publish_message),
            name=f"ai-task-{task_id}", daemon=True)
        with self._lock:
            self._cancel_events[task_id] = cancel
            self._threads[task_id] = thread
        thread.start()

    def recover_incomplete(self, exclude: set[str] | None = None, max_attempts: int = 2) -> list[dict[str, Any]]:
        if self._recovery_done:
            return []
        self._recovery_done = True
        exclude = exclude or set()
        recovered: list[dict[str, Any]] = []
        for old in self.database.list_tasks(active_only=True, limit=500):
            if old.get("provider_id") in exclude:
                continue
            metadata = old.get("metadata") or {}
            resume = metadata.get("resume_payload") if isinstance(metadata, dict) else None
            self.database.update_task(old["id"], status="interrupted", stage="程序重啟，已中斷",
                                      error="AI Hub 上次程序非正常結束；已進入復原流程。", completed_at=utcnow())
            if not isinstance(resume, dict) or not metadata.get("recoverable", True):
                continue
            attempt = int(metadata.get("attempt") or 1) + 1
            if attempt > max_attempts:
                continue
            project = self.database.get_project(str(resume.get("project_id") or ""))
            if not project or not Path(project["path"]).is_dir():
                continue
            new_meta = {"retry_of": old["id"], "attempt": attempt, "recovered_after_crash": True}
            recovered.append(self.launch(
                str(resume["provider_id"]), str(resume["title"]), str(resume["prompt"]), project,
                resume.get("conversation_id"), str(resume.get("permission_mode") or "workspace"),
                int(resume.get("predicted_seconds") or 120), list(resume.get("selected_files") or []),
                bool(resume.get("web_access", True)), metadata=new_meta,
                publish_message=bool(resume.get("publish_message", True))))
        return recovered

    def _conversation_history(self, conversation_id: str | None) -> list[dict[str, Any]]:
        if not conversation_id:
            return []
        messages = self.database.list_messages(conversation_id)
        return messages[:-1] if messages and messages[-1].get("role") == "user" else messages

    def _worker(self, task_id: str, provider_id: str, prompt: str, project: dict[str, Any],
                conversation_id: str | None, permission_mode: str, predicted_seconds: int,
                selected_files: list[str], web_access: bool, publish_message: bool) -> None:
        started = time.monotonic()
        self.database.update_task(task_id, status="running", stage="準備上下文", progress=1, started_at=utcnow())
        self.database.add_task_event(task_id, "工作已開始", progress=1)
        cancel = self._cancel_events[task_id]
        guard: ScopedWorkspaceGuard | None = None

        def emit(stage: str, message: str, progress: float | None, level: str) -> None:
            values: dict[str, Any] = {"stage": stage}
            if progress is not None:
                values["progress"] = max(0, min(99, progress))
            self.database.update_task(task_id, **values)
            if level != "debug" or message:
                self.database.add_task_event(task_id, message, level=level, progress=progress)

        try:
            provider = self.providers.get(provider_id)
            if selected_files and permission_mode != "observe" and getattr(provider, "kind", "") in {"cli", "system"}:
                guard = ScopedWorkspaceGuard(Path(project["path"]), selected_files)
            context = ProviderContext(prompt=prompt, project_path=Path(project["path"]),
                permission_mode=permission_mode, selected_files=selected_files,
                history=self._conversation_history(conversation_id), web_access=web_access)
            result = provider.run(context, emit, cancel)
            if guard:
                guard.enforce()
            duration = time.monotonic() - started
            current = self.database.get_task(task_id) or {}
            result_metadata = {**(current.get("metadata") or {}), **result.metadata,
                               "execution_completed": True}
            self.database.update_task(task_id, status="completed", stage="已完成", progress=100,
                session_id=result.session_id, result=result.text, metadata_json=result_metadata,
                completed_at=utcnow())
            self.database.add_task_event(task_id, "工作完成", progress=100)
            if conversation_id and publish_message:
                self.database.add_message(conversation_id, "assistant", result.text, provider_id=provider_id,
                                          metadata={"task_id": task_id, **result_metadata})
            self.database.add_metric(provider_id, self._workload(prompt), predicted_seconds, duration, True)
        except Exception as error:
            duration = time.monotonic() - started
            cancelled = cancel.is_set()
            self.database.update_task(task_id, status="cancelled" if cancelled else "failed",
                stage="已停止" if cancelled else "執行失敗", error=str(error) or error.__class__.__name__,
                completed_at=utcnow())
            self.database.add_task_event(task_id, str(error), level="warning" if cancelled else "error")
            if conversation_id and publish_message and not cancelled:
                self.database.add_message(conversation_id, "assistant", f"執行失敗：{error}", provider_id=provider_id,
                                          metadata={"task_id": task_id, "error": True})
            self.database.add_metric(provider_id, self._workload(prompt), predicted_seconds, duration, False)
        finally:
            if guard:
                guard.close()
            with self._lock:
                self._cancel_events.pop(task_id, None)
                self._threads.pop(task_id, None)

    @staticmethod
    def _workload(prompt: str) -> str:
        return "small" if len(prompt) < 300 else ("medium" if len(prompt) < 1200 else "large")

    def run_inline(self, provider_id: str, title: str, prompt: str, project: dict[str, Any],
                   conversation_id: str | None, permission_mode: str, predicted_seconds: int,
                   parent_task_id: str, web_access: bool = True,
                   selected_files: list[str] | None = None) -> tuple[dict[str, Any], ProviderResult]:
        selected_files = selected_files or []
        task = self.database.create_task(provider_id, title, prompt, conversation_id, project.get("id"),
                                         predicted_seconds, future_iso(predicted_seconds), parent_task_id=parent_task_id,
                                         metadata={"selected_files": selected_files})
        task_id = task["id"]
        cancel = self._cancel_events.get(parent_task_id, threading.Event())
        started = time.monotonic()
        self.database.update_task(task_id, status="running", stage="執行中", progress=2, started_at=utcnow())
        guard: ScopedWorkspaceGuard | None = None

        def emit(stage: str, message: str, progress: float | None, level: str) -> None:
            values: dict[str, Any] = {"stage": stage}
            if progress is not None:
                values["progress"] = max(0, min(99, progress))
            self.database.update_task(task_id, **values)
            self.database.add_task_event(task_id, message, level, progress)

        try:
            provider = self.providers.get(provider_id)
            if selected_files and permission_mode != "observe" and getattr(provider, "kind", "") in {"cli", "system"}:
                guard = ScopedWorkspaceGuard(Path(project["path"]), selected_files)
            result = provider.run(ProviderContext(prompt=prompt, project_path=Path(project["path"]),
                permission_mode=permission_mode, selected_files=selected_files,
                history=self._conversation_history(conversation_id), web_access=web_access), emit, cancel)
            if guard:
                guard.enforce()
            duration = time.monotonic() - started
            current = self.database.get_task(task_id) or {}
            meta = {**(current.get("metadata") or {}), **result.metadata, "execution_completed": True}
            self.database.update_task(task_id, status="completed", stage="已完成", progress=100,
                result=result.text, session_id=result.session_id, metadata_json=meta, completed_at=utcnow())
            self.database.add_metric(provider_id, self._workload(prompt), predicted_seconds, duration, True)
            return self.database.get_task(task_id) or task, result
        except Exception as error:
            self.database.update_task(task_id, status="failed", stage="執行失敗", error=str(error), completed_at=utcnow())
            self.database.add_metric(provider_id, self._workload(prompt), predicted_seconds, time.monotonic() - started, False)
            raise
        finally:
            if guard:
                guard.close()

    def register_parent(self, task_id: str, cancel: threading.Event, thread: threading.Thread) -> None:
        with self._lock:
            self._cancel_events[task_id] = cancel
            self._threads[task_id] = thread

    def unregister_parent(self, task_id: str) -> None:
        with self._lock:
            self._cancel_events.pop(task_id, None)
            self._threads.pop(task_id, None)

    def cancel(self, task_id: str) -> bool:
        with self._lock:
            event = self._cancel_events.get(task_id)
        if not event:
            return False
        self.database.update_task(task_id, status="cancelling", stage="正在停止")
        event.set()
        return True

    def wait(self, task_id: str, timeout: float | None = None) -> dict[str, Any] | None:
        with self._lock:
            thread = self._threads.get(task_id)
        if thread:
            thread.join(timeout=timeout)
        return self.database.get_task(task_id)
