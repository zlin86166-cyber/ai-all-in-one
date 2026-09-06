from __future__ import annotations

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
