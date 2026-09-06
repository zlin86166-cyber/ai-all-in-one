from __future__ import annotations

import os
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any

from .config import AppPaths
from .db import Database, utcnow
from .task_manager_v2 import TaskManager, future_iso


class IntegrationManager:
    def __init__(self, paths: AppPaths, database: Database, tasks: TaskManager):
        self.paths, self.database, self.tasks = paths, database, tasks

    def status(self) -> dict[str, Any]:
        return {"google_play": {"token_present": bool(os.environ.get("GOOGLE_PLAY_ACCESS_TOKEN")), "mode": "Android Publisher API"},
                "google_sites": {"mode": "modern-sites-browser-assisted", "write_api": False},
                "model_sync": {"metadata_present": (self.paths.data / "latest-models.json").is_file()}}

    def _launch(self, kind: str, title: str, script: Path, args: list[str], project: dict[str, Any],
                conversation_id: str | None, predicted_seconds: int = 120) -> dict[str, Any]:
        task = self.database.create_task(f"integration:{kind}", title, " ".join(args), conversation_id,
            project.get("id"), predicted_seconds, future_iso(predicted_seconds),
            metadata={"integration": kind, "recoverable": False})
        cancel = threading.Event(); thread = threading.Thread(target=self._worker,
            args=(task["id"], kind, script, args, project, conversation_id, cancel),
            daemon=True, name=f"integration-{kind}-{task['id']}")
        self.tasks.register_parent(task["id"], cancel, thread); thread.start(); return task

    def _worker(self, task_id: str, kind: str, script: Path, args: list[str], project: dict[str, Any],
                conversation_id: str | None, cancel: threading.Event) -> None:
        started = time.monotonic(); self.database.update_task(task_id, status="running", stage="啟動整合工具", progress=3, started_at=utcnow())
        command = [sys.executable, str(script), *args]
        try:
            process = subprocess.Popen(command, cwd=project["path"], stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, encoding="utf-8", errors="replace", creationflags=getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0))
            lines = []
            assert process.stdout is not None
            for line in process.stdout:
                line = line.rstrip(); lines.append(line)
                if line: self.database.add_task_event(task_id, line, level="output")
                if cancel.is_set() and process.poll() is None:
                    process.terminate(); break
            code = process.wait()
            if cancel.is_set(): raise InterruptedError("整合工作已停止。")
            if code: raise RuntimeError(f"{kind} 結束碼 {code}: {' '.join(lines[-10:])}")
            result = "\n".join(lines[-80:]) or f"{kind} 完成"
            self.database.update_task(task_id, status="completed", stage="整合完成", progress=100, result=result,
                                      metadata_json={"integration": kind, "execution_completed": True}, completed_at=utcnow())
            self.database.add_task_event(task_id, "整合工作完成", progress=100)
            self.database.audit(f"integration.{kind}.completed", task_id, {"seconds": round(time.monotonic()-started,1)})
            if conversation_id:
                self.database.add_message(conversation_id, "assistant", result, provider_id=f"integration:{kind}", metadata={"task_id":task_id})
        except Exception as error:
            cancelled = isinstance(error, InterruptedError) or cancel.is_set()
            self.database.update_task(task_id, status="cancelled" if cancelled else "failed", stage="已停止" if cancelled else "整合失敗",
                                      error=str(error), completed_at=utcnow())
            self.database.add_task_event(task_id, str(error), level="warning" if cancelled else "error")
        finally:
            self.tasks.unregister_parent(task_id)

    def sync_models(self, project: dict[str, Any], conversation_id: str | None = None) -> dict[str, Any]:
        return self._launch("model-sync", "同步 Kimi / DeepSeek 官方模型", self.paths.root / "tools" / "model_sync.py",
                            ["--output", "data/latest-models.json"], project, conversation_id, 90)

    def publish_play(self, project: dict[str, Any], package: str, artifact: Path, track: str, status: str,
                     commit: bool, conversation_id: str | None = None) -> dict[str, Any]:
        args = ["--package", package, "--artifact", str(artifact), "--track", track, "--status", status, "--approve-account-action"]
        if commit: args.append("--commit")
        return self._launch("google-play", "Google Play 發布流程", self.paths.root / "tools" / "play_publish.py", args, project, conversation_id, 300)

    def open_sites(self, project: dict[str, Any], title: str, profile: str | None,
                   template_url: str | None, conversation_id: str | None = None) -> dict[str, Any]:
        args = ["--title", title, "--approve-account-action"]
        if profile: args += ["--profile", profile]
        if template_url: args += ["--template-url", template_url]
        return self._launch("google-sites", "Google Sites 建站工作階段", self.paths.root / "tools" / "google_sites_assist.py", args, project, conversation_id, 60)
