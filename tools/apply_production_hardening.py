from __future__ import annotations

"""One-shot repository migration used by the hardening workflow.

This script intentionally operates only on known AI Hub source paths and is safe to
run repeatedly: generated modules are replaced atomically and textual migrations
are guarded by exact anchors.  The workflow removes this helper after verification.
"""

from pathlib import Path
import textwrap

ROOT = Path(__file__).resolve().parents[1]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def write(path: str, content: str) -> None:
    target = ROOT / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content.rstrip() + "\n", encoding="utf-8")


def replace_once(path: str, old: str, new: str) -> None:
    source = read(path)
    if new in source:
        return
    if old not in source:
        raise RuntimeError(f"migration anchor missing in {path}: {old[:120]!r}")
    write(path, source.replace(old, new, 1))


def append_once(path: str, marker: str, content: str) -> None:
    source = read(path)
    if marker in source:
        return
    write(path, source.rstrip() + "\n\n" + content.rstrip() + "\n")


SECURITY = r'''from __future__ import annotations

import hashlib
import ipaddress
import json
import re
import socket
import urllib.parse
from pathlib import Path
from typing import Any


FULL_ACCESS_PHRASE = "我同意完整系統權限"


class SecurityError(ValueError):
    pass


def canonical_path(value: str | Path) -> Path:
    try:
        return Path(value).expanduser().resolve(strict=False)
    except (OSError, RuntimeError) as error:
        raise SecurityError(f"無法解析路徑：{value}") from error


def path_inside(candidate: str | Path, root: str | Path) -> bool:
    target = canonical_path(candidate)
    base = canonical_path(root)
    try:
        target.relative_to(base)
        return True
    except ValueError:
        return False


def scoped_path(candidate: str | Path, project_root: str | Path, full_access: bool = False) -> Path:
    target = canonical_path(candidate)
    if not full_access and not path_inside(target, project_root):
        raise SecurityError("路徑超出目前專案；請先切換專案或明確啟用完整系統權限。")
    return target


def require_write_mode(mode: str) -> None:
    if mode == "observe":
        raise PermissionError("觀察模式是唯讀模式，禁止建立、修改、刪除或覆寫資料。")


DESTRUCTIVE_PATTERNS = [
    r"\bremove-item\b.*-recurse\b", r"\brm\s+(-[^\s]*r[^\s]*f|-[^\s]*f[^\s]*r)\b",
    r"\bdel\s+/(s|q)\b", r"\bformat(\.com)?\b", r"\bdiskpart\b", r"\bclean\s+all\b",
    r"\bgit\s+reset\s+--hard\b", r"\bgit\s+clean\s+-[^\s]*f", r"\breg\s+delete\b",
    r"\bbcdedit\b", r"\bclear-disk\b", r"\bremove-partition\b", r"\bremove-volume\b",
]
SYSTEM_PATTERNS = [
    r"\bpowercfg\b", r"\bset-service\b", r"\bsc(\.exe)?\s+(create|delete|config|stop)\b",
    r"\bschtasks\b", r"\bshutdown\b", r"\brestart-computer\b",
    r"\bwinget\s+(install|uninstall|upgrade)\b", r"\bset-executionpolicy\b",
    r"\bnew-service\b", r"\bstop-service\b", r"\bstart-service\b",
]
ACCOUNT_PATTERNS = [
    r"\b(deploy|publish|release)\b", r"\bsites?\b", r"\b(login|logout|oauth|sign[ -]?in)\b",
    r"\b(play console|app store|firebase|cloudflare|aws|azure|gcloud)\b",
    r"(部署|發布|上架|送審|公開網站|建立網站|建立\s*sites?|申請\s*apk|使用.*帳號|登入|登出|oauth|授權帳號)",
]
DOWNLOAD_PATTERNS = [
    r"\b(curl|wget|invoke-webrequest|invoke-restmethod|start-bitstransfer|bitsadmin)\b",
    r"\b(npm|pnpm|pip|uv|cargo)\s+(install|add)\b", r"\b(git\s+clone|ollama\s+pull)\b",
]


def classify_command(command: str) -> dict[str, Any]:
    lowered = command.lower()
    if any(re.search(pattern, lowered, re.IGNORECASE) for pattern in DESTRUCTIVE_PATTERNS):
        return {"kind": "destructive", "requires_approval": True, "risk": "high"}
    if any(re.search(pattern, lowered, re.IGNORECASE) for pattern in SYSTEM_PATTERNS):
        return {"kind": "system", "requires_approval": True, "risk": "high"}
    if any(re.search(pattern, lowered, re.IGNORECASE) for pattern in ACCOUNT_PATTERNS):
        return {"kind": "account", "requires_approval": True, "risk": "medium"}
    if any(re.search(pattern, lowered, re.IGNORECASE) for pattern in DOWNLOAD_PATTERNS):
        return {"kind": "download", "requires_approval": True, "risk": "medium"}
    return {"kind": "command", "requires_approval": False, "risk": "normal"}


def validate_workspace_command(command: str, project_root: str | Path, mode: str) -> None:
    require_write_mode(mode)
    if mode == "full":
        return
    root = canonical_path(project_root)
    # Conservative path guard for the local PowerShell endpoint.  AI CLI providers
    # have their own workspace sandbox; this closes the common absolute/parent path escape.
    candidates = re.findall(
        r"(?i)(?:[A-Z]:\\[^\s\"'|;]+|\\\\[^\s\"'|;]+|(?:\.\.\\)+(?:[^\s\"'|;]+)?)",
        command,
    )
    for candidate in candidates:
        value = candidate.rstrip(",.)]")
        target = canonical_path(root / value) if value.startswith("..") else canonical_path(value)
        if not path_inside(target, root):
            raise PermissionError(f"Workspace 模式禁止終端機存取專案外路徑：{target}")


def action_fingerprint(kind: str, payload: dict[str, Any]) -> str:
    serialized = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(f"{kind}:{serialized}".encode("utf-8")).hexdigest()


def requires_account_approval(prompt: str) -> bool:
    return any(re.search(pattern, prompt, re.IGNORECASE) for pattern in ACCOUNT_PATTERNS)


def validate_network_url(url: str, *, allow_private: bool = False) -> urllib.parse.ParseResult:
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("只支援有效的 HTTP/HTTPS 網址。")
    if allow_private:
        return parsed
    host = parsed.hostname
    try:
        addresses = {item[4][0] for item in socket.getaddrinfo(host, parsed.port or (443 if parsed.scheme == "https" else 80), type=socket.SOCK_STREAM)}
    except socket.gaierror as error:
        raise ConnectionError(f"無法解析網域：{host}") from error
    if not addresses:
        raise ConnectionError(f"網域沒有可用位址：{host}")
    for address in addresses:
        ip = ipaddress.ip_address(address.split("%", 1)[0])
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_unspecified or ip.is_multicast:
            raise PermissionError(f"公開研究模式禁止連線到內部/保留位址：{host} → {ip}")
    return parsed
'''

WORKSPACE_GUARD = r'''from __future__ import annotations

import hashlib
import os
import shutil
import tempfile
from pathlib import Path

from .security import canonical_path, path_inside


class ScopeViolation(PermissionError):
    pass


class ScopedWorkspaceGuard:
    """Rollback file changes outside an explicitly selected file/directory set.

    This is a postcondition guard around CLI agents.  To make rollback reliable it
    snapshots non-selected project files before execution.  Extremely large projects
    are rejected rather than silently pretending the selected-file boundary is hard.
    """

    EXCLUDED_DIRS = {".git", ".runtime", "__pycache__", ".build"}

    def __init__(self, project_root: Path, selected: list[str], max_backup_bytes: int = 512 * 1024 * 1024):
        self.root = canonical_path(project_root)
        self.allowed = [canonical_path(item) for item in selected]
        self.max_backup_bytes = max_backup_bytes
        self.temp = Path(tempfile.mkdtemp(prefix="aihub-scope-"))
        self.initial: dict[str, str] = {}
        self._snapshot()

    def _allowed(self, path: Path) -> bool:
        target = canonical_path(path)
        return any(target == item or path_inside(target, item) for item in self.allowed)

    @staticmethod
    def _digest(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            while True:
                chunk = handle.read(1024 * 1024)
                if not chunk:
                    break
                digest.update(chunk)
        return digest.hexdigest()

    def _walk(self):
        for base, dirs, files in os.walk(self.root, topdown=True, followlinks=False):
            dirs[:] = [name for name in dirs if name not in self.EXCLUDED_DIRS and name != "data"]
            base_path = Path(base)
            for name in files:
                yield base_path / name

    def _snapshot(self) -> None:
        total = 0
        count = 0
        for path in self._walk():
            if self._allowed(path) or path.is_symlink():
                continue
            count += 1
            if count > 20_000:
                raise ScopeViolation("選取檔案硬限制拒絕啟動：專案超過 20,000 個可寫檔案，無法安全建立回復快照。")
            try:
                size = path.stat().st_size
            except OSError:
                continue
            total += size
            if total > self.max_backup_bytes:
                raise ScopeViolation("選取檔案硬限制拒絕啟動：非選取檔案快照超過 512 MB；請縮小專案或改用 Workspace 範圍。")
            rel = path.relative_to(self.root).as_posix()
            self.initial[rel] = self._digest(path)
            backup = self.temp / rel
            backup.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, backup)

    def enforce(self) -> None:
        violations: list[str] = []
        current: dict[str, Path] = {}
        for path in self._walk():
            if self._allowed(path) or path.is_symlink():
                continue
            rel = path.relative_to(self.root).as_posix()
            current[rel] = path
            if rel not in self.initial:
                violations.append(f"created:{rel}")
                try:
                    path.unlink()
                except OSError:
                    pass
                continue
            try:
                changed = self._digest(path) != self.initial[rel]
            except OSError:
                changed = True
            if changed:
                violations.append(f"modified:{rel}")
                backup = self.temp / rel
                path.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(backup, path)
        for rel in self.initial:
            if rel in current:
                continue
            violations.append(f"deleted:{rel}")
            target = self.root / rel
            backup = self.temp / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(backup, target)
        if violations:
            sample = "、".join(violations[:12])
            raise ScopeViolation(f"AI 嘗試修改選取範圍外檔案；AI Hub 已回復這些變更：{sample}")

    def close(self) -> None:
        shutil.rmtree(self.temp, ignore_errors=True)
'''

TASKS_V2 = r'''from __future__ import annotations

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
'''

ORCHESTRATOR_V2 = r'''from __future__ import annotations

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
'''

HARDWARE_V2 = r'''from __future__ import annotations

import ctypes
import os
from typing import Any

from .hardware import HardwareMonitor as BaseHardwareMonitor


class HardwareMonitor(BaseHardwareMonitor):
    def resource_policy(self, requested_parallel: int = 3) -> dict[str, Any]:
        snap = super().snapshot()
        memory = float(snap.get("memory", {}).get("percent") or 0)
        cpu = float(snap.get("cpu_percent") or 0)
        free_disk = float(snap.get("disk", {}).get("free_gb") or 0)
        ac = bool(snap.get("power", {}).get("ac_connected", True))
        parallel = max(1, int(requested_parallel))
        reasons = []
        if memory >= 90:
            parallel = 1; reasons.append("RAM >= 90%：暫停新增大型本機並行工作")
        elif memory >= 80:
            parallel = min(parallel, 2); reasons.append("RAM >= 80%：降低並行度")
        if cpu >= 95:
            parallel = 1; reasons.append("CPU >= 95%：降低並行度")
        if not ac:
            parallel = min(parallel, 2); reasons.append("電池供電：限制高負載")
        return {"max_parallel_agents": parallel, "prefer_remote_model": memory >= 88 or free_disk < 15,
                "admit_large_local_model": memory < 80 and free_disk >= 25,
                "reasons": reasons or ["資源正常"]}

    def recommended_parallelism(self, requested: int) -> int:
        return int(self.resource_policy(requested)["max_parallel_agents"])

    def snapshot(self) -> dict[str, Any]:
        snap = super().snapshot()
        snap["resource_policy"] = self.resource_policy(3)
        return snap

    def update_performance_boost(self, enabled: bool, threshold: int) -> bool:
        # High memory pressure should throttle, not raise process priority.  Priority
        # boost is used only when plugged in and below the configured pressure limit.
        snap = super().snapshot()
        should_boost = bool(enabled and snap["power"]["ac_connected"] and snap["memory"]["percent"] < threshold and snap.get("cpu_percent", 0) < 92)
        if should_boost == self._boost_active:
            return self._boost_active
        if os.name == "nt":
            priority = 0x00000080 if should_boost else 0x00000020
            ctypes.windll.kernel32.SetPriorityClass(ctypes.windll.kernel32.GetCurrentProcess(), priority)
        self._boost_active = should_boost
        return self._boost_active
'''

PROVIDER_REGISTRY_V2 = r'''from __future__ import annotations

import json
import os
import subprocess
import urllib.error
import urllib.request
from typing import Any

from .providers import ProviderRegistry as BaseProviderRegistry, _find_command, _codex_authenticated, _gemini_authenticated


class ProviderRegistry(BaseProviderRegistry):
    def _compatible_probe(self) -> tuple[bool, str]:
        config = self.settings.get("provider_config", {}).get("compatible", {})
        base = str(config.get("base_url") or "").rstrip("/")
        model = str(config.get("model") or "")
        if not base or not model:
            return False, "未設定模型或端點"
        headers = {"Accept": "application/json"}
        key = os.environ.get(str(config.get("api_key_env") or "AI_HUB_API_KEY"), "")
        if key: headers["Authorization"] = f"Bearer {key}"
        try:
            with urllib.request.urlopen(urllib.request.Request(base + "/models", headers=headers), timeout=2.5) as response:
                if response.status >= 400: return False, f"端點 HTTP {response.status}"
            return True, f"{model} · {base} · live"
        except Exception as error:
            return False, f"端點未就緒：{error}"

    def _codex_live_auth(self) -> bool:
        cmd = _find_command("codex", self.paths)
        if not cmd or not _codex_authenticated(): return False
        try:
            result = subprocess.run([str(cmd), "login", "status"], capture_output=True, timeout=8,
                                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            return result.returncode == 0
        except Exception:
            return False

    def status(self, force: bool = False) -> list[dict[str, Any]]:
        items = super().status(force=force)
        compatible_ok, compatible_detail = self._compatible_probe()
        codex_live = self._codex_live_auth()
        ollama_reachable = False
        try:
            with urllib.request.urlopen("http://127.0.0.1:11434/api/tags", timeout=1.2) as response:
                json.loads(response.read().decode("utf-8")); ollama_reachable = True
        except Exception:
            pass
        for item in items:
            if item["id"] == "compatible":
                item["available"], item["detail"] = compatible_ok, compatible_detail
            elif item["id"] == "codex":
                item["authenticated"] = codex_live
                item["available"] = bool(item.get("installed") and codex_live)
                if item.get("installed") and not codex_live: item["detail"] = "CLI 已安裝，但即時登入狀態未通過"
            elif item["id"] == "ollama:empty" and not ollama_reachable:
                item["detail"] = "Ollama 服務未連線或尚未啟動"
        self._status_cache = (__import__("time").monotonic(), items)
        return items
'''

MODEL_MANAGER_V2 = r'''from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .models import ModelManager as BaseModelManager


class ModelManager(BaseModelManager):
    def _dynamic_entries(self) -> list[dict[str, Any]]:
        path = self.paths.data / "latest-models.json"
        if not path.is_file(): return []
        try: payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError): return []
        result = []
        for family, info in (payload.get("families") or {}).items():
            seen = set()
            for key in ("latest_eligible", "largest_eligible"):
                row = info.get(key) if isinstance(info, dict) else None
                if not isinstance(row, dict) or not row.get("id") or row["id"] in seen: continue
                seen.add(row["id"])
                p = float(row.get("parameters_b") or 0)
                if not (0 < p <= 50): continue
                ram = 20 if p <= 8 else (32 if p <= 16 else (64 if p <= 32 else 96))
                disk = max(8, round(p * 2.2))
                result.append({"id": row["id"], "family": family,
                    "label": f"{row['id'].split('/')[-1]} · {'最新' if key == 'latest_eligible' else '最大'} ≤50B",
                    "parameters_b": p, "runtime": "openai-compatible", "install": None,
                    "ram_gb": ram, "disk_gb": disk, "recommended": key == "latest_eligible",
                    "notes": "由官方 Hugging Face organization metadata 動態同步",
                    "source": row.get("source"), "hf_repo": row["id"], "training_model": row["id"],
                    "dynamic": True, "last_modified": row.get("last_modified")})
        return result

    def catalog(self) -> list[dict[str, Any]]:
        static = super().catalog()
        existing = {item["id"] for item in static}
        snapshot = self.hardware.snapshot(); disk = float(snapshot.get("disk", {}).get("free_gb") or 0)
        for item in self._dynamic_entries():
            if item["id"] in existing: continue
            target = self.paths.downloads / "models" / item["id"].replace("/", "--")
            installed = (target / ".aihub-download-complete.json").is_file() and (target / "config.json").is_file()
            item["installed"] = installed; item["download_path"] = str(target)
            if installed: state, reason = "downloaded", "官方權重已下載；可接 vLLM/SGLang 或進行 QLoRA"
            elif disk < float(item["disk_gb"]) + 10: state, reason = "blocked", "磁碟安全空間不足"
            else: state, reason = "available", "官方動態目錄項目可下載"
            item["compatibility"] = {"state": state, "reason": reason}; static.append(item)
        return static

    def _find_any(self, model_id: str) -> dict[str, Any] | None:
        return next((item for item in self.catalog() if item["id"] == model_id), None)

    def pull(self, model_id: str, project: dict[str, Any], conversation_id: str | None = None) -> dict[str, Any]:
        dynamic = next((item for item in self._dynamic_entries() if item["id"] == model_id), None)
        if not dynamic: return super().pull(model_id, project, conversation_id)
        item = self._find_any(model_id) or dynamic
        if item.get("installed"): raise ValueError("模型已下載。")
        if item.get("compatibility", {}).get("state") == "blocked": raise ValueError(item["compatibility"]["reason"])
        target = self.paths.downloads / "models" / model_id.replace("/", "--")
        return self.tasks.launch("hf-model-manager", f"下載 {item['label']}",
            json.dumps({"repository": model_id, "target": str(target)}, ensure_ascii=False), project,
            conversation_id, "workspace", max(600, int(float(item.get("disk_gb") or 1) * 160)),
            web_access=True, metadata={"model_id": model_id, "download": True, "repository": model_id},
            publish_message=bool(conversation_id))

    def training_preflight(self, model_id: str, dataset_path: str) -> dict[str, Any]:
        dynamic = next((item for item in self._dynamic_entries() if item["id"] == model_id), None)
        if not dynamic: return super().training_preflight(model_id, dataset_path)
        parameters = float(dynamic["parameters_b"]); dataset = self._validate_dataset(Path(dataset_path).expanduser().resolve())
        requirements = self._training_requirements(parameters); hardware = self.hardware.snapshot(); cuda = self._cuda_probe()
        ram = float(hardware.get("memory", {}).get("total_gb") or 0); disk = float(hardware.get("disk", {}).get("free_gb") or 0)
        blockers = []
        if not dataset["valid"]: blockers.append(str(dataset["error"]))
        if not cuda["available"]: blockers.append("未偵測到可用 NVIDIA CUDA GPU")
        elif float(cuda["vram_gb"]) < requirements["vram_gb"]: blockers.append(f"VRAM 需要至少 {requirements['vram_gb']:.0f} GB")
        if ram < requirements["ram_gb"]: blockers.append(f"RAM 需要至少 {requirements['ram_gb']:.0f} GB，目前 {ram:.1f} GB")
        if disk < requirements["disk_gb"]: blockers.append(f"可用磁碟需要至少 {requirements['disk_gb']:.0f} GB，目前 {disk:.1f} GB")
        return {"ready": not blockers, "model_id": model_id, "training_model": model_id, "parameters_b": parameters,
                "dataset": dataset, "cuda": cuda, "requirements": requirements, "detected": {"ram_gb": ram, "disk_gb": disk}, "blockers": blockers}

    def readiness(self) -> dict[str, Any]:
        value = super().readiness(); sync = self.paths.data / "latest-models.json"
        value["official_model_sync"] = {"available": sync.is_file(), "path": str(sync),
            "detail": "主模型目錄會直接合併同步結果" if sync.is_file() else "尚未同步官方模型 metadata"}
        return value
'''

INTEGRATIONS = r'''from __future__ import annotations

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
'''

MAINTENANCE = r'''from __future__ import annotations

import shutil
import sqlite3
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


class DataMaintenance:
    def __init__(self, database, data_root: Path):
        self.database, self.data_root = database, data_root
        self._last = 0.0

    def maybe_run(self, force: bool = False) -> dict[str, Any] | None:
        if not force and time.monotonic() - self._last < 3600:
            return None
        self._last = time.monotonic(); return self.run()

    def run(self) -> dict[str, Any]:
        backups = self.data_root / "backups"; backups.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d")
        backup = backups / f"ai-hub-{stamp}.sqlite3"
        if not backup.exists():
            src = sqlite3.connect(self.database.path); dst = sqlite3.connect(backup)
            try: src.backup(dst)
            finally: dst.close(); src.close()
        for old in sorted(backups.glob("ai-hub-*.sqlite3"), reverse=True)[7:]: old.unlink(missing_ok=True)
        cutoff = (datetime.now(timezone.utc) - timedelta(days=90)).isoformat(timespec="seconds")
        with self.database._write_lock, self.database._session() as connection:
            connection.execute("DELETE FROM task_events WHERE created_at < ?", (cutoff,))
            connection.execute("DELETE FROM audit_log WHERE id NOT IN (SELECT id FROM audit_log ORDER BY id DESC LIMIT 5000)")
            connection.execute("DELETE FROM research_documents WHERE rowid NOT IN (SELECT MAX(rowid) FROM research_documents GROUP BY url)")
            if self.database._fts_enabled:
                self.database._rebuild_search_index(connection)
        generated = self.data_root / "generated"; removed = 0
        if generated.exists():
            files = sorted((p for p in generated.iterdir() if p.is_file()), key=lambda p: p.stat().st_mtime, reverse=True)
            total = sum(p.stat().st_size for p in files); limit = 2 * 1024**3
            for path in reversed(files):
                if total <= limit: break
                size = path.stat().st_size; path.unlink(missing_ok=True); total -= size; removed += 1
        result = {"backup": str(backup), "generated_removed": removed}
        self.database.audit("maintenance.completed", "data", result); return result
'''

CRAWLER = r'''from __future__ import annotations

import html
import re
import urllib.error
import urllib.parse
import urllib.request
import urllib.robotparser
from html.parser import HTMLParser
from typing import Any

from .config import Settings
from .db import Database
from .security import validate_network_url

USER_AGENT = "AIHubLocalResearch/1.0 (+local-user-agent)"


class TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True); self.parts=[]; self.title_parts=[]; self._ignored=0; self._in_title=False
    def handle_starttag(self, tag, attrs):
        if tag in {"script","style","svg","noscript"}: self._ignored += 1
        if tag == "title": self._in_title=True
        if tag in {"p","div","article","section","li","h1","h2","h3","br"}: self.parts.append("\n")
    def handle_endtag(self, tag):
        if tag in {"script","style","svg","noscript"} and self._ignored: self._ignored -= 1
        if tag == "title": self._in_title=False
    def handle_data(self, data):
        if self._ignored: return
        if self._in_title: self.title_parts.append(data)
        self.parts.append(data)
    def result(self):
        title=" ".join(" ".join(self.title_parts).split()); text=html.unescape("\n".join(self.parts))
        text=re.sub(r"[ \t]+"," ",text); text=re.sub(r"\n{3,}","\n\n",text).strip(); return title,text


class SafeRedirectHandler(urllib.request.HTTPRedirectHandler):
    def __init__(self, allow_private: bool): super().__init__(); self.allow_private=allow_private
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        validate_network_url(newurl, allow_private=self.allow_private)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


class ResearchCrawler:
    def __init__(self, database: Database, settings: Settings): self.database=database; self.settings=settings
    def _allowed(self, url: str) -> bool:
        allowlist=self.settings.get("crawler_allowlist", [])
        if not allowlist: return True
        host=(urllib.parse.urlparse(url).hostname or "").lower()
        return any(host == item.lower() or host.endswith("."+item.lower()) for item in allowlist)
    def fetch(self, url: str) -> dict[str, Any]:
        allow_private=bool(self.settings.get("allow_private_research", False))
        parsed=validate_network_url(url, allow_private=allow_private)
        if not self._allowed(url): raise PermissionError("此網域不在自動研究允許清單。")
        robots_url=f"{parsed.scheme}://{parsed.netloc}/robots.txt"; robot=urllib.robotparser.RobotFileParser(); robot.set_url(robots_url)
        try:
            robot.read()
            if not robot.can_fetch(USER_AGENT, url): raise PermissionError("網站 robots.txt 不允許擷取此頁面。")
        except urllib.error.URLError: pass
        request=urllib.request.Request(url, headers={"User-Agent":USER_AGENT,"Accept":"text/html,text/plain,application/json"})
        opener=urllib.request.build_opener(SafeRedirectHandler(allow_private))
        try:
            with opener.open(request, timeout=30) as response:
                validate_network_url(response.geturl(), allow_private=allow_private)
                content_type=response.headers.get_content_type(); raw=response.read(2_000_001)
                if len(raw)>2_000_000: raise ValueError("頁面超過 2 MB 擷取上限。")
                charset=response.headers.get_content_charset() or "utf-8"
        except urllib.error.URLError as error: raise ConnectionError(f"無法擷取網址：{error}") from error
        decoded=raw.decode(charset, errors="replace")
        if content_type == "text/html": parser=TextExtractor(); parser.feed(decoded); title,text=parser.result()
        else: title,text=parsed.path.rsplit("/",1)[-1] or parsed.hostname,decoded
        if not text.strip(): raise ValueError("頁面沒有可用文字內容。")
        return self.database.save_research_document(url=response.geturl(), title=title or parsed.hostname,
            text=text[:500_000], metadata={"content_type":content_type,"characters":len(text)})
'''

SCHEDULER = r'''from __future__ import annotations

import threading
from datetime import datetime, timedelta
from typing import Any, Callable

from .db import Database, utcnow


class Scheduler:
    def __init__(self, database: Database, dispatch: Callable[[dict[str, Any]], dict[str, Any] | None]):
        self.database=database; self.dispatch=dispatch; self._stop=threading.Event(); self._inflight={}
        self._thread=threading.Thread(target=self._loop, name="ai-hub-scheduler", daemon=True)
    def start(self):
        if not self._thread.is_alive(): self._thread.start()
    def stop(self):
        self._stop.set()
        if self._thread.is_alive(): self._thread.join(timeout=3)
    @staticmethod
    def _within_window(current: str, start: str, end: str) -> bool:
        return start <= current <= end if start <= end else current >= start or current <= end
    def _busy(self, schedule_id: str) -> bool:
        task_id=self._inflight.get(schedule_id)
        if not task_id: return False
        task=self.database.get_task(task_id)
        if task and task.get("status") in {"queued","running","cancelling"}: return True
        self._inflight.pop(schedule_id, None); return False
    def _loop(self):
        while not self._stop.wait(20):
            now=datetime.now(); current=now.strftime("%H:%M")
            for schedule in self.database.list_schedules():
                if not schedule.get("enabled") or now.weekday() not in schedule.get("weekdays", []): continue
                if not self._within_window(current, schedule["start_time"], schedule["end_time"]): continue
                if self._busy(schedule["id"]): continue
                last=schedule.get("last_run_at")
                if last:
                    try:
                        previous=datetime.fromisoformat(last).astimezone(); interval=max(5,int(schedule.get("interval_minutes") or 1440))
                        if now-previous < timedelta(minutes=interval): continue
                    except ValueError: pass
                try:
                    task=self.dispatch(schedule)
                except Exception as error:
                    self.database.audit("schedule.dispatch_failed", schedule["id"], {"error":str(error)}); continue
                self.database.update_schedule(schedule["id"], {"last_run_at":utcnow()})
                if task and task.get("id"): self._inflight[schedule["id"]]=task["id"]
'''

SERVER_V2 = r'''from __future__ import annotations

import hmac
import mimetypes
import os
import re
import urllib.parse
from http.server import ThreadingHTTPServer
from pathlib import Path

from .server import AIHubHandler, APIError


def create_server(app, host: str, port: int) -> ThreadingHTTPServer:
    if host not in {"127.0.0.1", "localhost", "::1"}:
        raise PermissionError("AI Hub Web 控制面預設只允許 loopback。遠端控制必須使用另外的已驗證通道。")
    class Handler(SecureAIHubHandler):
        application=app
    server=ThreadingHTTPServer((host,port),Handler); server.daemon_threads=True; return server


class SecureAIHubHandler(AIHubHandler):
    def _session_ok(self) -> bool:
        token=str(getattr(self.application,"session_token", ""))
        header=self.headers.get("X-AIHub-Session", "")
        cookie=self.headers.get("Cookie", "")
        cookie_token=""
        for part in cookie.split(";"):
            name, sep, value=part.strip().partition("=")
            if sep and name=="AIHUB_SESSION": cookie_token=value
        supplied=header or cookie_token
        return bool(token and supplied and hmac.compare_digest(token, supplied))
    def _guard_api(self):
        path,_=self._route()
        if path=="/api/health": return
        if not self._session_ok(): raise APIError(403,"AI Hub 本機 Session 驗證失敗。請從 AI Hub 控制面重新開啟。")
        origin=self.headers.get("Origin")
        host=self.headers.get("Host","")
        if origin:
            parsed=urllib.parse.urlparse(origin)
            if parsed.netloc != host: raise APIError(403,"拒絕跨來源 API 請求。")
    def do_GET(self):
        try:
            if self.path.startswith("/api/"): self._guard_api()
            return super().do_GET()
        except Exception as error: self._handle_error(error)
    def do_PATCH(self):
        try: self._guard_api(); return super().do_PATCH()
        except Exception as error: self._handle_error(error)
    def do_POST(self):
        try:
            self._guard_api(); path,_=self._route()
            if path in {"/api/models/sync","/api/models/pull","/api/integrations/play","/api/integrations/sites","/api/research/fetch","/api/maintenance/run"}:
                payload=self._json_body()
                if path=="/api/models/sync": self._send_json(self.application.sync_models(payload),202); return
                if path=="/api/models/pull": self._send_json(self.application.pull_model(payload),202); return
                if path=="/api/integrations/play": self._send_json(self.application.publish_play(payload),202); return
                if path=="/api/integrations/sites": self._send_json(self.application.open_sites(payload),202); return
                if path=="/api/research/fetch": self._send_json(self.application.research_fetch(payload),201); return
                if path=="/api/maintenance/run": self._send_json(self.application.run_maintenance(payload)); return
            return super().do_POST()
        except Exception as error: self._handle_error(error)
    def _serve_static(self, request_path: str) -> None:
        relative="index.html" if request_path in {"","/"} else urllib.parse.unquote(request_path.lstrip("/"))
        target=(self.application.paths.web/relative).resolve()
        try: target.relative_to(self.application.paths.web.resolve())
        except ValueError as error: raise APIError(403,"禁止存取。") from error
        if not target.is_file(): target=self.application.paths.web/"index.html"
        body=target.read_bytes(); content_type=mimetypes.guess_type(target.name)[0] or "application/octet-stream"
        self.send_response(200); self.send_header("Content-Type", f"{content_type}; charset=utf-8" if content_type.startswith("text/") or content_type in {"application/javascript","application/json"} else content_type)
        self.send_header("Content-Length",str(len(body))); self.send_header("Cache-Control","no-cache"); self.send_header("X-Content-Type-Options","nosniff")
        self.send_header("Content-Security-Policy","default-src 'self'; img-src 'self' data: blob:; style-src 'self' 'unsafe-inline'; script-src 'self'; connect-src 'self';")
        if target.name=="index.html":
            self.send_header("Set-Cookie", f"AIHUB_SESSION={self.application.session_token}; HttpOnly; SameSite=Strict; Path=/")
        self.end_headers(); self.wfile.write(body)
'''

HARDENING_TESTS = r'''from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from ai_hub.db import Database
from ai_hub.scheduler import Scheduler
from ai_hub.security import action_fingerprint, require_write_mode, validate_network_url, validate_workspace_command
from ai_hub.workspace_guard import ScopedWorkspaceGuard, ScopeViolation


class HardeningTests(unittest.TestCase):
    def test_observe_is_read_only(self):
        with self.assertRaises(PermissionError): require_write_mode("observe")

    def test_workspace_terminal_blocks_parent_escape(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)/"project"; root.mkdir()
            with self.assertRaises(PermissionError): validate_workspace_command("Get-Content ..\\secret.txt", root, "workspace")

    def test_selected_file_guard_rolls_back_out_of_scope_change(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory); allowed=root/"a.txt"; other=root/"b.txt"
            allowed.write_text("a",encoding="utf-8"); other.write_text("b",encoding="utf-8")
            guard=ScopedWorkspaceGuard(root,[str(allowed)], max_backup_bytes=1024*1024)
            try:
                allowed.write_text("new a",encoding="utf-8"); other.write_text("bad",encoding="utf-8")
                with self.assertRaises(ScopeViolation): guard.enforce()
                self.assertEqual(other.read_text(encoding="utf-8"),"b")
                self.assertEqual(allowed.read_text(encoding="utf-8"),"new a")
            finally: guard.close()

    def test_approval_is_consumed_once(self):
        with tempfile.TemporaryDirectory() as directory:
            db=Database(Path(directory)/"x.sqlite3"); payload={"x":1}; fp=action_fingerprint("system",payload)
            approval=db.create_approval("system","test",fp,payload); db.resolve_approval(approval["id"],True)
            self.assertTrue(db.approval_valid(approval["id"],fp)); self.assertFalse(db.approval_valid(approval["id"],fp))

    def test_scheduler_cross_midnight(self):
        self.assertTrue(Scheduler._within_window("23:30","22:00","02:00")); self.assertTrue(Scheduler._within_window("01:00","22:00","02:00")); self.assertFalse(Scheduler._within_window("12:00","22:00","02:00"))

    @mock.patch("socket.getaddrinfo", return_value=[(None,None,None,None,("127.0.0.1",80))])
    def test_public_research_blocks_loopback(self,_):
        with self.assertRaises(PermissionError): validate_network_url("http://example.test/")


if __name__=="__main__": unittest.main()
'''

CI = r'''name: CI
on:
  push:
    branches: [main]
  pull_request:
permissions:
  contents: read
jobs:
  test:
    strategy:
      matrix:
        os: [ubuntu-latest, windows-latest]
        python: ['3.11', '3.13']
    runs-on: ${{ matrix.os }}
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: ${{ matrix.python }}
      - run: python -m unittest discover -v
'''

WINDOWS_BUILD = r'''name: Windows Build
on:
  workflow_dispatch:
  push:
    branches: [main]
permissions:
  contents: read
jobs:
  build:
    runs-on: windows-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: '3.13'
      - run: python -m pip install --upgrade pyinstaller
      - shell: powershell
        run: ./build-desktop.ps1
      - uses: actions/upload-artifact@v4
        with:
          name: AIHub-Windows-${{ github.sha }}
          path: AIHub.exe
          if-no-files-found: error
'''

WATCHDOG = r'''param([int]$RestartDelaySeconds = 8,[switch]$Web)
$ErrorActionPreference='Continue'; $appRoot=Split-Path -Parent $MyInvocation.MyCommand.Path; $dataRoot=Join-Path $appRoot 'data'
$stopFile=Join-Path $dataRoot 'watchdog.stop'; $normalExit=Join-Path $dataRoot 'normal-exit.marker'; $logFile=Join-Path $dataRoot 'watchdog.log'
New-Item -ItemType Directory -Path $dataRoot -Force | Out-Null; Remove-Item $stopFile -Force -ErrorAction SilentlyContinue
function Write-WatchdogLog([string]$Message){
  if((Test-Path $logFile) -and (Get-Item $logFile).Length -gt 5MB){ Move-Item $logFile (Join-Path $dataRoot ("watchdog-"+(Get-Date -Format 'yyyyMMdd-HHmmss')+'.log')) -Force }
  Add-Content $logFile -Value "$(Get-Date -Format o) $Message" -Encoding UTF8
}
$crashes=New-Object System.Collections.Generic.List[datetime]; Write-WatchdogLog 'watchdog started'
while(-not (Test-Path $stopFile)){
  Remove-Item $normalExit -Force -ErrorAction SilentlyContinue
  try{
    $arguments=@('-NoProfile','-ExecutionPolicy','Bypass','-File',(Join-Path $appRoot 'start.ps1'),'-NoElevate'); if($Web){$arguments+='-Web'}
    $process=Start-Process powershell.exe -ArgumentList $arguments -WorkingDirectory $appRoot -PassThru; $process.WaitForExit(); Write-WatchdogLog "AI Hub exited code=$($process.ExitCode)"
  }catch{ Write-WatchdogLog "launch failed: $($_.Exception.Message)" }
  if(Test-Path $normalExit){ Write-WatchdogLog 'normal user shutdown detected; watchdog stops'; break }
  $now=Get-Date; $crashes.Add($now); for($i=$crashes.Count-1;$i-ge 0;$i--){if(($now-$crashes[$i]).TotalMinutes -gt 5){$crashes.RemoveAt($i)}}
  if($crashes.Count -ge 5){ Write-WatchdogLog 'crash loop protection: 5 exits within 5 minutes; manual recovery required'; break }
  if(-not (Test-Path $stopFile)){ Start-Sleep -Seconds ([Math]::Max(3,$RestartDelaySeconds)) }
}
Write-WatchdogLog 'watchdog stopped'
'''


def main() -> None:
    write("ai_hub/security.py", SECURITY)
    write("ai_hub/workspace_guard.py", WORKSPACE_GUARD)
    write("ai_hub/task_manager_v2.py", TASKS_V2)
    write("ai_hub/orchestrator_v2.py", ORCHESTRATOR_V2)
    write("ai_hub/hardware_v2.py", HARDWARE_V2)
    write("ai_hub/provider_registry_v2.py", PROVIDER_REGISTRY_V2)
    write("ai_hub/model_manager_v2.py", MODEL_MANAGER_V2)
    write("ai_hub/integrations.py", INTEGRATIONS)
    write("ai_hub/maintenance.py", MAINTENANCE)
    write("ai_hub/crawler.py", CRAWLER)
    write("ai_hub/scheduler.py", SCHEDULER)
    write("tests/test_hardening.py", HARDENING_TESTS)
    write(".github/workflows/ci.yml", CI)
    write(".github/workflows/windows-build.yml", WINDOWS_BUILD)
    write("watchdog.ps1", WATCHDOG)

    # Settings: add hardened defaults without exposing dangerous bypass in the UI.
    replace_once("ai_hub/config.py", '    "auto_peer_review": True,\n    "provider_config": {',
        '    "auto_peer_review": True,\n    "unsafe_full_cli": False,\n    "allow_private_research": False,\n    "maintenance_enabled": True,\n    "provider_config": {')

    # Approval records are now truly one-shot and expire quickly, without a schema migration.
    replace_once("ai_hub/db.py",
'''    def approval_valid(self, approval_id: str | None, fingerprint: str) -> bool:\n        if not approval_id:\n            return False\n        row = self.get_approval(approval_id)\n        return bool(row and row["status"] == "approved" and row["fingerprint"] == fingerprint)\n''',
'''    def approval_valid(self, approval_id: str | None, fingerprint: str) -> bool:\n        if not approval_id:\n            return False\n        row = self.get_approval(approval_id)\n        if not row or row["status"] != "approved" or row["fingerprint"] != fingerprint:\n            return False\n        try:\n            created = datetime.fromisoformat(row["created_at"])\n            if created.tzinfo is None:\n                created = created.replace(tzinfo=timezone.utc)\n            if datetime.now(timezone.utc) - created.astimezone(timezone.utc) > timedelta(minutes=5):\n                self._execute("UPDATE approvals SET status = 'expired', resolved_at = ? WHERE id = ?", (utcnow(), approval_id))\n                return False\n        except (TypeError, ValueError):\n            return False\n        self._execute("UPDATE approvals SET status = 'consumed', resolved_at = ? WHERE id = ? AND status = 'approved'", (utcnow(), approval_id))\n        return True\n''')
    replace_once("ai_hub/db.py", 'from datetime import datetime, timezone', 'from datetime import datetime, timedelta, timezone')

    # Safe CLI full mode: system-wide actions go through the broker/API approval layer.
    replace_once("ai_hub/providers.py",
'''    openai_bin = paths.runtime / "openai-cli"\n    if openai_bin.exists():\n        path_entries.append(str(openai_bin))\n''', '')
    replace_once("ai_hub/providers.py",
'''        if context.permission_mode == "full":\n            arguments.append("--dangerously-bypass-approvals-and-sandbox")\n        else:\n            arguments.extend(["--ask-for-approval", "never"])\n''',
'''        unsafe_full = os.environ.get("AI_HUB_UNSAFE_FULL_CLI") == "1"\n        if context.permission_mode == "full" and unsafe_full:\n            arguments.append("--dangerously-bypass-approvals-and-sandbox")\n        else:\n            arguments.extend(["--ask-for-approval", "never"])\n''')
    replace_once("ai_hub/providers.py",
'''        if context.permission_mode == "observe":\n            arguments.extend(["--sandbox", "read-only"])\n        elif context.permission_mode == "workspace":\n            arguments.extend(["--sandbox", "workspace-write"])\n''',
'''        if context.permission_mode == "observe":\n            arguments.extend(["--sandbox", "read-only"])\n        elif context.permission_mode in {"workspace", "full"} and not unsafe_full:\n            arguments.extend(["--sandbox", "workspace-write"])\n''')
    replace_once("ai_hub/providers.py",
'''        if context.permission_mode == "full":\n            arguments.append("--yolo")\n        elif context.permission_mode == "workspace":\n            arguments.extend(["--approval-mode", "auto_edit"])\n        else:\n            arguments.extend(["--approval-mode", "plan"])\n''',
'''        unsafe_full = os.environ.get("AI_HUB_UNSAFE_FULL_CLI") == "1"\n        if context.permission_mode == "full" and unsafe_full:\n            arguments.append("--yolo")\n        elif context.permission_mode in {"workspace", "full"}:\n            arguments.extend(["--approval-mode", "auto_edit"])\n        else:\n            arguments.extend(["--approval-mode", "plan"])\n''')
    # Kill process trees on cancellation on Windows.
    replace_once("ai_hub/providers.py",
'''            process.terminate()\n            try:\n                process.wait(timeout=5)\n            except subprocess.TimeoutExpired:\n                process.kill()\n''',
'''            if os.name == "nt":\n                subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"], capture_output=True,\n                               creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))\n            else:\n                process.terminate()\n            try:\n                process.wait(timeout=5)\n            except subprocess.TimeoutExpired:\n                process.kill()\n''')

    # Main application switches to hardened components and integrates account/model tools.
    app = read("ai_hub/application.py")
    app = app.replace("import json\n", "import json\nimport secrets\n", 1)
    app = app.replace("from .hardware import HardwareMonitor", "from .hardware_v2 import HardwareMonitor")
    app = app.replace("from .models import ModelManager", "from .model_manager_v2 import ModelManager")
    app = app.replace("from .orchestrator import CollaborationOrchestrator", "from .orchestrator_v2 import CollaborationOrchestrator")
    app = app.replace("from .providers import ProviderRegistry", "from .provider_registry_v2 import ProviderRegistry")
    app = app.replace("from .tasks import TaskManager", "from .task_manager_v2 import TaskManager\nfrom .integrations import IntegrationManager\nfrom .maintenance import DataMaintenance")
    app = app.replace("    requires_account_approval,\n    scoped_path,\n)", "    requires_account_approval,\n    scoped_path,\n    require_write_mode,\n    validate_workspace_command,\n)")
    app = app.replace("        self.paths = AppPaths.create(root)\n        self.settings = Settings(self.paths.settings)",
                      "        self.paths = AppPaths.create(root)\n        self.settings = Settings(self.paths.settings)\n        self.session_token = secrets.token_urlsafe(32)\n        os.environ['AI_HUB_UNSAFE_FULL_CLI'] = '1' if self.settings.get('unsafe_full_cli', False) else '0'")
    app = app.replace("            lambda: int(self.settings.get(\"max_parallel_agents\", 3)),\n        )",
                      "            lambda: self.hardware.recommended_parallelism(int(self.settings.get(\"max_parallel_agents\", 3))),\n        )")
    app = app.replace("        self.images = ImageGenerationManager(\n            self.paths, self.settings, self.database, self.tasks\n        )",
                      "        self.images = ImageGenerationManager(\n            self.paths, self.settings, self.database, self.tasks\n        )\n        self.integrations = IntegrationManager(self.paths, self.database, self.tasks)\n        self.maintenance = DataMaintenance(self.database, self.paths.data)\n        self._recovery_done = False")
    app = app.replace("    def start_background(self) -> None:\n        self.scheduler.start()",
                      "    def start_background(self) -> None:\n        if not self._recovery_done:\n            self._recovery_done = True\n            self.orchestrator.recover_incomplete()\n            self.tasks.recover_incomplete(exclude={'collaboration'})\n        self.scheduler.start()")
    app = app.replace("                self.hardware.update_performance_boost(\n                    bool(self.settings.get(\"adaptive_performance\", False)),\n                    int(self.settings.get(\"performance_memory_threshold\", 90)),\n                )",
                      "                self.hardware.update_performance_boost(\n                    bool(self.settings.get(\"adaptive_performance\", False)),\n                    int(self.settings.get(\"performance_memory_threshold\", 90)),\n                )\n                if self.settings.get('maintenance_enabled', True):\n                    self.maintenance.maybe_run()")
    app = app.replace("        from .server import create_server", "        from .server_v2 import create_server")
    app = app.replace("    def stop(self) -> None:\n        self.scheduler.stop()",
                      "    def stop(self) -> None:\n        try:\n            (self.paths.data / 'normal-exit.marker').write_text(utcnow() if 'utcnow' in globals() else datetime.now(timezone.utc).isoformat(), encoding='utf-8')\n        except OSError:\n            pass\n        self.scheduler.stop()")
    app = app.replace('            "research": self.database.list_research_documents(),\n        }',
                      '            "research": self.database.list_research_documents(),\n            "integrations": self.integrations.status(),\n            "resource_policy": self.hardware.resource_policy(int(self.settings.get("max_parallel_agents", 3))),\n        }')
    app = app.replace('            "max_parallel_agents", "auto_peer_review", "provider_config",\n',
                      '            "max_parallel_agents", "auto_peer_review", "provider_config",\n            "allow_private_research", "maintenance_enabled",\n')
    app = app.replace("        self.providers.invalidate()\n", "        os.environ['AI_HUB_UNSAFE_FULL_CLI'] = '1' if self.settings.get('unsafe_full_cli', False) else '0'\n        self.providers.invalidate()\n", 1)
    app = app.replace("                bool(payload.get(\"peer_review\", self.settings.get(\"auto_peer_review\", True))),\n            )",
                      "                bool(payload.get(\"peer_review\", self.settings.get(\"auto_peer_review\", True))),\n                selected_files,\n            )", 1)
    app = app.replace("        self._check_permission_mode(mode)\n        classification = classify_command(command)",
                      "        self._check_permission_mode(mode)\n        validate_workspace_command(command, project['path'], mode)\n        classification = classify_command(command)", 1)
    app = app.replace("        self._check_permission_mode(mode)\n        target = scoped_path(payload.get(\"path\", \"\"), project[\"path\"], full_access=mode == \"full\")",
                      "        self._check_permission_mode(mode)\n        require_write_mode(mode)\n        target = scoped_path(payload.get(\"path\", \"\"), project[\"path\"], full_access=mode == \"full\")", 1)
    app = app.replace("        self._check_permission_mode(mode)\n        target = scoped_path(\n            payload.get(\"path\", \"\"), project[\"path\"], full_access=mode == \"full\"\n        )",
                      "        self._check_permission_mode(mode)\n        require_write_mode(mode)\n        target = scoped_path(\n            payload.get(\"path\", \"\"), project[\"path\"], full_access=mode == \"full\"\n        )", 1)
    integration_methods = '''\n    def sync_models(self, payload: dict[str, Any]) -> dict[str, Any]:\n        project = self.get_project(payload.get("project_id"))\n        task = self.integrations.sync_models(project, payload.get("conversation_id"))\n        self.database.audit("model.sync.started", task["id"])\n        return {"task": task}\n\n    def pull_model(self, payload: dict[str, Any]) -> dict[str, Any]:\n        project = self.get_project(payload.get("project_id"))\n        mode = str(payload.get("permission_mode") or "workspace")\n        self._check_permission_mode(mode); require_write_mode(mode)\n        model_id = str(payload.get("model_id") or "")\n        approval_payload = {"model_id": model_id, "project_id": project["id"]}\n        self._require_approval("download", f"允許下載模型一次？\\n{model_id}", approval_payload, payload.get("approval_id"))\n        task = self.models.pull(model_id, project, payload.get("conversation_id"))\n        self.database.audit("model.pull.started", task["id"], approval_payload)\n        return {"task": task}\n\n    def publish_play(self, payload: dict[str, Any]) -> dict[str, Any]:\n        project = self.get_project(payload.get("project_id")); mode = str(payload.get("permission_mode") or "full")\n        self._check_permission_mode(mode)\n        if mode != "full": raise PermissionError("Google Play 發布需要完整權限模式。")\n        artifact = canonical_path(str(payload.get("artifact") or ""))\n        if not artifact.is_file() or artifact.suffix.lower() not in {".apk", ".aab"}: raise ValueError("請選擇存在的 APK/AAB。")\n        package = str(payload.get("package") or "").strip(); track = str(payload.get("track") or "internal"); status = str(payload.get("status") or "draft")\n        commit = bool(payload.get("commit")); approval_payload={"package":package,"artifact":str(artifact),"track":track,"status":status,"commit":commit}\n        self._require_approval("publish", "允許這一次 Google Play 驗證/發布操作？" + ("\\n包含 COMMIT" if commit else "\\n只驗證，不 COMMIT"), approval_payload, payload.get("approval_id"))\n        task=self.integrations.publish_play(project,package,artifact,track,status,commit,payload.get("conversation_id")); self.database.audit("play.publish.started",task["id"],approval_payload); return {"task":task}\n\n    def open_sites(self, payload: dict[str, Any]) -> dict[str, Any]:\n        project=self.get_project(payload.get("project_id")); title=str(payload.get("title") or "").strip()\n        if not title: raise ValueError("Sites 標題不可為空。")\n        approval_payload={"title":title,"profile":payload.get("profile"),"template_url":payload.get("template_url")}\n        self._require_approval("account", "允許開啟這一次 Google Sites 帳號建站工作階段？", approval_payload, payload.get("approval_id"))\n        task=self.integrations.open_sites(project,title,payload.get("profile"),payload.get("template_url"),payload.get("conversation_id")); self.database.audit("sites.session.started",task["id"],approval_payload); return {"task":task}\n\n    def research_fetch(self, payload: dict[str, Any]) -> dict[str, Any]:\n        if not self.settings.get("crawler_enabled", False): raise PermissionError("研究爬蟲目前停用。")\n        return self.crawler.fetch(str(payload.get("url") or ""))\n\n    def run_maintenance(self, payload: dict[str, Any]) -> dict[str, Any]:\n        mode=str(payload.get("permission_mode") or "workspace"); self._check_permission_mode(mode)\n        return self.maintenance.maybe_run(force=True) or {"ok":True}\n'''
    anchor = "    def list_files(self, project_id: str, path: str | None = None) -> dict[str, Any]:"
    if integration_methods.strip() not in app:
        app = app.replace(anchor, integration_methods + "\n" + anchor, 1)
    app = app.replace("    def _dispatch_schedule(self, schedule: dict[str, Any]) -> None:", "    def _dispatch_schedule(self, schedule: dict[str, Any]) -> dict[str, Any] | None:")
    app = app.replace("            timer.start()\n            return\n", "            timer.start()\n            return task\n", 1)
    app = app.replace("        timer.start()\n", "        timer.start()\n        return task\n", 1)
    write("ai_hub/application.py", app)

    # ComfyUI: no time-derived fake percentages; cancellation interrupts the backend queue.
    images = read("ai_hub/images.py")
    if "def _interrupt(" not in images:
        images = images.replace("    def _worker(\n", '''    @classmethod\n    def _interrupt(cls, base_url: str, prompt_id: str) -> None:\n        for endpoint, payload in (("/queue", {"delete": [prompt_id]}), ("/interrupt", {})):\n            try:\n                cls._request_json(base_url + endpoint, payload, timeout=3)\n            except Exception:\n                pass\n\n    def _worker(\n''', 1)
    images = images.replace('                progress = min(92, 8 + elapsed / max(1, metadata["steps"] * 5) * 78)\n                self.database.update_task(task_id, stage="生成圖片中", progress=progress)\n                if elapsed - last_event >= 12:\n                    self.database.add_task_event(\n                        task_id, f"ComfyUI 仍在生成，已等待 {int(elapsed)} 秒。", progress=progress\n                    )\n                    last_event = elapsed\n',
'''                self.database.update_task(task_id, stage="生成圖片中")\n                if elapsed - last_event >= 12:\n                    self.database.add_task_event(task_id, f"ComfyUI 仍在生成，已等待 {int(elapsed)} 秒；節點未提供可驗證百分比。", progress=None)\n                    last_event = elapsed\n''')
    images = images.replace('            if cancel.is_set():\n                raise InterruptedError("繪圖工作已停止。")',
                            '            if cancel.is_set():\n                self._interrupt(base_url, prompt_id)\n                raise InterruptedError("繪圖工作已停止，並已要求 ComfyUI 中斷佇列工作。")', 1)
    write("ai_hub/images.py", images)

    # Web UI must never turn elapsed time into fake completion percentage.
    web = read("web/app.js")
    old = '''function taskDisplayProgress(task) {\n  const actual = Number(task.progress || 0);\n  if (task.status === "completed") return 100;\n  if (!["running", "queued", "cancelling"].includes(task.status)) return actual;\n  if (!task.started_at || !task.predicted_seconds) return Math.max(actual, task.status === "queued" ? 0 : 3);\n  const elapsed = (Date.now() - new Date(task.started_at).getTime()) / 1000;\n  const estimated = Math.min(92, (elapsed / Number(task.predicted_seconds)) * 82);\n  return Math.max(actual, estimated);\n}\n'''
    new = '''function taskDisplayProgress(task) {\n  const actual = Number(task.progress || 0);\n  if (task.status === "completed") return 100;\n  return Math.max(0, Math.min(100, actual));\n}\n'''
    if old in web: web = web.replace(old,new,1)
    write("web/app.js", web)

    # Repository hygiene: runtime/generated data must never be committed accidentally.
    write(".gitignore", '''.runtime/\ndata/*\n!data/.gitkeep\n__pycache__/\n*.pyc\ntraining/output/\ntraining/cache/\n.build/\n*.log\n*.tmp\n''')
    tracked_temp = ROOT / "data" / "ai-hub-codex-84jz5quu.txt"
    if tracked_temp.exists(): tracked_temp.unlink()
    (ROOT / "data").mkdir(exist_ok=True); (ROOT / "data" / ".gitkeep").touch()

    append_once("README.md", "## Production hardening", '''## Production hardening\n\n目前主幹採 hardened runtime：Observe 為真正唯讀；選取檔案工作有回復式範圍守衛；Full AI CLI 預設仍限制在 workspace，系統/帳號動作改走 AI Hub 一次性核准層；核准 5 分鐘內只能消耗一次。Web 控制面使用 loopback session cookie + same-origin 驗證。Crash 後一般 Provider 會自動 retry，協作流程會從最近 checkpoint 恢復；Peer Review 是品質閘門，未通過不會標成完成。\n\n官方 Kimi/DeepSeek metadata 會直接合併到模型目錄；Google Play、Google Sites 與模型同步都已接入 Task/Audit backend。Modern Google Sites 仍受平台限制，採受核准的瀏覽器工作階段，不宣稱不存在的寫入 API。CI 會在 Windows/Linux 與 Python 3.11/3.13 跑單元測試；Windows Build workflow 產生最新 AIHub.exe artifact。''')
    write("docs/HARDENING.md", '''# AI Hub Production Hardening\n\n本輪將權限、任務復原、品質閘門、真實進度、模型生命週期、整合工作、SSRF 防護、Watchdog、資料生命週期與 CI 由「功能存在」提升成可驗證的產品機制。\n\n- Observe：唯讀；Workspace 終端機阻擋常見專案外路徑；選取檔案由 ScopedWorkspaceGuard 建立回復快照。\n- Full：Codex/Gemini 預設不再 bypass sandbox；只有明確設定 `unsafe_full_cli` 才會恢復 CLI 原生危險模式。\n- Approval：核准 5 分鐘內、同 fingerprint 僅可消耗一次。\n- Web：只接受 loopback，使用 HttpOnly SameSite session cookie 與 Origin 檢查。\n- Recovery：一般 Task crash 後 retry；協作 DAG 保存 checkpoint 並續跑未完成步驟。\n- QA：Peer Review `pass` 才能完成；失敗會進 remediation，最多三輪。\n- Progress：移除 elapsed-time 假百分比；沒有來源就只顯示 stage/ETA。\n- Models：`latest-models.json` 合併進主 Catalog，可下載與 QLoRA 前檢。\n- Integrations：Play/Sites/model sync 進入 Task + Audit。\n- Research：DNS/private/reserved IP 與 redirect 再驗證，預設阻擋 SSRF 到 LAN/localhost。\n- Reliability：Watchdog 辨識正常關閉、5 分鐘 5 次 crash loop 熔斷、log rotation。\n- Maintenance：每日 SQLite backup、保留 7 份、事件/audit/research 清理與生成圖片 2GB quota。\n- CI：Windows/Linux test matrix；Windows executable artifact build。\n''')


if __name__ == "__main__":
    main()
