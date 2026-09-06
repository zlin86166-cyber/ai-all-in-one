from __future__ import annotations

import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from .db import Database, utcnow
from .providers import ProviderContext, ProviderError, ProviderRegistry, ProviderResult


def future_iso(seconds: int) -> str:
    return (datetime.now(timezone.utc) + timedelta(seconds=seconds)).isoformat(timespec="seconds")


class TaskManager:
    def __init__(self, database: Database, providers: ProviderRegistry):
        self.database = database
        self.providers = providers
        self._cancel_events: dict[str, threading.Event] = {}
        self._threads: dict[str, threading.Thread] = {}
        self._lock = threading.RLock()

    def launch(
        self,
        provider_id: str,
        title: str,
        prompt: str,
        project: dict[str, Any],
        conversation_id: str | None,
        permission_mode: str,
        predicted_seconds: int,
        selected_files: list[str] | None = None,
        web_access: bool = True,
        parent_task_id: str | None = None,
        metadata: dict[str, Any] | None = None,
        publish_message: bool = True,
    ) -> dict[str, Any]:
        task = self.database.create_task(
            provider_id=provider_id,
            title=title,
            prompt=prompt,
            conversation_id=conversation_id,
            project_id=project.get("id"),
            predicted_seconds=predicted_seconds,
            predicted_end_at=future_iso(predicted_seconds),
            parent_task_id=parent_task_id,
            metadata=metadata,
        )
        cancel = threading.Event()
        thread = threading.Thread(
            target=self._worker,
            args=(
                task["id"], provider_id, prompt, project, conversation_id, permission_mode,
                predicted_seconds, selected_files or [], web_access, publish_message,
            ),
            name=f"ai-task-{task['id']}",
            daemon=True,
        )
        with self._lock:
            self._cancel_events[task["id"]] = cancel
            self._threads[task["id"]] = thread
        thread.start()
        return task

    def _conversation_history(self, conversation_id: str | None) -> list[dict[str, Any]]:
        if not conversation_id:
            return []
        messages = self.database.list_messages(conversation_id)
        return messages[:-1] if messages and messages[-1].get("role") == "user" else messages

    def _worker(
        self,
        task_id: str,
        provider_id: str,
        prompt: str,
        project: dict[str, Any],
        conversation_id: str | None,
        permission_mode: str,
        predicted_seconds: int,
        selected_files: list[str],
        web_access: bool,
        publish_message: bool,
    ) -> None:
        started = time.monotonic()
        self.database.update_task(
            task_id, status="running", stage="準備上下文", progress=1, started_at=utcnow()
        )
        self.database.add_task_event(task_id, "工作已開始", progress=1)
        cancel = self._cancel_events[task_id]

        def emit(stage: str, message: str, progress: float | None, level: str) -> None:
            values: dict[str, Any] = {"stage": stage}
            if progress is not None:
                values["progress"] = max(0, min(99, progress))
            self.database.update_task(task_id, **values)
            if level != "debug" or message:
                self.database.add_task_event(task_id, message, level=level, progress=progress)

        try:
            provider = self.providers.get(provider_id)
            context = ProviderContext(
                prompt=prompt,
                project_path=Path(project["path"]),
                permission_mode=permission_mode,
                selected_files=selected_files,
                history=self._conversation_history(conversation_id),
                web_access=web_access,
            )
            result = provider.run(context, emit, cancel)
            duration = time.monotonic() - started
            current = self.database.get_task(task_id) or {}
            result_metadata = {
                **(current.get("metadata") or {}),
                **result.metadata,
            }
            self.database.update_task(
                task_id,
                status="completed",
                stage="已完成",
                progress=100,
                session_id=result.session_id,
                result=result.text,
                metadata_json=result_metadata,
                completed_at=utcnow(),
            )
            self.database.add_task_event(task_id, "工作完成", progress=100)
            if conversation_id and publish_message:
                self.database.add_message(
                    conversation_id,
                    "assistant",
                    result.text,
                    provider_id=provider_id,
                    metadata={"task_id": task_id, **result_metadata},
                )
            self.database.add_metric(
                provider_id, self._workload(prompt), predicted_seconds, duration, True
            )
        except Exception as error:
            duration = time.monotonic() - started
            cancelled = cancel.is_set()
            status = "cancelled" if cancelled else "failed"
            message = str(error) or error.__class__.__name__
            self.database.update_task(
                task_id,
                status=status,
                stage="已停止" if cancelled else "執行失敗",
                error=message,
                completed_at=utcnow(),
            )
            self.database.add_task_event(task_id, message, level="warning" if cancelled else "error")
            if conversation_id and publish_message and not cancelled:
                self.database.add_message(
                    conversation_id,
                    "assistant",
                    f"執行失敗：{message}",
                    provider_id=provider_id,
                    metadata={"task_id": task_id, "error": True},
                )
            self.database.add_metric(
                provider_id, self._workload(prompt), predicted_seconds, duration, False
            )
        finally:
            with self._lock:
                self._cancel_events.pop(task_id, None)
                self._threads.pop(task_id, None)

    @staticmethod
    def _workload(prompt: str) -> str:
        length = len(prompt)
        if length < 300:
            return "small"
        if length < 1200:
            return "medium"
        return "large"

    def run_inline(
        self,
        provider_id: str,
        title: str,
        prompt: str,
        project: dict[str, Any],
        conversation_id: str | None,
        permission_mode: str,
        predicted_seconds: int,
        parent_task_id: str,
        web_access: bool = True,
    ) -> tuple[dict[str, Any], ProviderResult]:
        task = self.database.create_task(
            provider_id,
            title,
            prompt,
            conversation_id,
            project.get("id"),
            predicted_seconds,
            future_iso(predicted_seconds),
            parent_task_id=parent_task_id,
        )
        task_id = task["id"]
        cancel = self._cancel_events.get(parent_task_id, threading.Event())
        started = time.monotonic()
        self.database.update_task(task_id, status="running", stage="執行中", progress=2, started_at=utcnow())

        def emit(stage: str, message: str, progress: float | None, level: str) -> None:
            values: dict[str, Any] = {"stage": stage}
            if progress is not None:
                values["progress"] = max(0, min(99, progress))
            self.database.update_task(task_id, **values)
            self.database.add_task_event(task_id, message, level, progress)

        try:
            result = self.providers.get(provider_id).run(
                ProviderContext(
                    prompt=prompt,
                    project_path=Path(project["path"]),
                    permission_mode=permission_mode,
                    history=self._conversation_history(conversation_id),
                    web_access=web_access,
                ),
                emit,
                cancel,
            )
            duration = time.monotonic() - started
            current = self.database.get_task(task_id) or {}
            result_metadata = {
                **(current.get("metadata") or {}),
                **result.metadata,
            }
            self.database.update_task(
                task_id,
                status="completed",
                stage="已完成",
                progress=100,
                result=result.text,
                session_id=result.session_id,
                metadata_json=result_metadata,
                completed_at=utcnow(),
            )
            self.database.add_metric(provider_id, self._workload(prompt), predicted_seconds, duration, True)
            return self.database.get_task(task_id) or task, result
        except Exception as error:
            duration = time.monotonic() - started
            self.database.update_task(
                task_id, status="failed", stage="執行失敗", error=str(error), completed_at=utcnow()
            )
            self.database.add_metric(provider_id, self._workload(prompt), predicted_seconds, duration, False)
            raise

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
