from __future__ import annotations

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
