from __future__ import annotations

import json
import sqlite3
import threading
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def make_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:16]}"


class Database:
    def __init__(self, path: Path):
        self.path = path
        self._write_lock = threading.RLock()
        self._fts_enabled = False
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 30000")
        return connection

    @contextmanager
    def _session(self):
        connection = self._connect()
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def _initialize(self) -> None:
        with self._session() as connection:
            connection.executescript(
                """
                PRAGMA journal_mode = WAL;
                CREATE TABLE IF NOT EXISTS projects (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    path TEXT NOT NULL UNIQUE,
                    created_at TEXT NOT NULL,
                    last_opened_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS conversations (
                    id TEXT PRIMARY KEY,
                    project_id TEXT REFERENCES projects(id) ON DELETE SET NULL,
                    title TEXT NOT NULL,
                    archived INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS messages (
                    id TEXT PRIMARY KEY,
                    conversation_id TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
                    role TEXT NOT NULL,
                    provider_id TEXT,
                    content TEXT NOT NULL,
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS tasks (
                    id TEXT PRIMARY KEY,
                    conversation_id TEXT REFERENCES conversations(id) ON DELETE SET NULL,
                    project_id TEXT REFERENCES projects(id) ON DELETE SET NULL,
                    parent_task_id TEXT REFERENCES tasks(id) ON DELETE CASCADE,
                    provider_id TEXT NOT NULL,
                    title TEXT NOT NULL,
                    prompt TEXT NOT NULL,
                    status TEXT NOT NULL,
                    stage TEXT NOT NULL,
                    progress REAL NOT NULL DEFAULT 0,
                    predicted_seconds INTEGER,
                    predicted_end_at TEXT,
                    session_id TEXT,
                    result TEXT,
                    error TEXT,
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL,
                    started_at TEXT,
                    completed_at TEXT
                );
                CREATE TABLE IF NOT EXISTS task_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    task_id TEXT NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
                    level TEXT NOT NULL,
                    message TEXT NOT NULL,
                    progress REAL,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS approvals (
                    id TEXT PRIMARY KEY,
                    kind TEXT NOT NULL,
                    summary TEXT NOT NULL,
                    fingerprint TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    resolved_at TEXT
                );
                CREATE TABLE IF NOT EXISTS schedules (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    prompt TEXT NOT NULL,
                    project_id TEXT REFERENCES projects(id) ON DELETE CASCADE,
                    provider_ids_json TEXT NOT NULL,
                    start_time TEXT NOT NULL,
                    end_time TEXT NOT NULL,
                    duration_minutes INTEGER NOT NULL,
                    interval_minutes INTEGER NOT NULL DEFAULT 1440,
                    weekdays_json TEXT NOT NULL,
                    mode TEXT NOT NULL,
                    enabled INTEGER NOT NULL DEFAULT 1,
                    last_run_at TEXT,
                    next_run_at TEXT,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS provider_metrics (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    provider_id TEXT NOT NULL,
                    workload TEXT NOT NULL,
                    predicted_seconds INTEGER,
                    duration_seconds REAL NOT NULL,
                    success INTEGER NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS task_feedback (
                    task_id TEXT PRIMARY KEY REFERENCES tasks(id) ON DELETE CASCADE,
                    success INTEGER NOT NULL,
                    note TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS research_documents (
                    id TEXT PRIMARY KEY,
                    url TEXT NOT NULL,
                    title TEXT NOT NULL,
                    text TEXT NOT NULL,
                    fetched_at TEXT NOT NULL,
                    metadata_json TEXT NOT NULL DEFAULT '{}'
                );
                CREATE TABLE IF NOT EXISTS audit_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    action TEXT NOT NULL,
                    resource TEXT NOT NULL,
                    details_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_messages_conversation ON messages(conversation_id, created_at);
                CREATE INDEX IF NOT EXISTS idx_tasks_conversation ON tasks(conversation_id, created_at);
                CREATE INDEX IF NOT EXISTS idx_events_task ON task_events(task_id, id);
                """
            )
            schedule_columns = {
                row[1] for row in connection.execute("PRAGMA table_info(schedules)").fetchall()
            }
            if "interval_minutes" not in schedule_columns:
                connection.execute(
                    "ALTER TABLE schedules ADD COLUMN interval_minutes INTEGER NOT NULL DEFAULT 1440"
                )
            self._initialize_search(connection)

    def _initialize_search(self, connection: sqlite3.Connection) -> None:
        """Create the local full-text index and backfill it once per schema version."""
        try:
            connection.execute(
                """CREATE VIRTUAL TABLE IF NOT EXISTS search_index USING fts5(
                    kind UNINDEXED,
                    ref_id UNINDEXED,
                    title,
                    content,
                    metadata_json UNINDEXED,
                    updated_at UNINDEXED,
                    tokenize='trigram'
                )"""
            )
            connection.execute(
                "CREATE TABLE IF NOT EXISTS search_state(key TEXT PRIMARY KEY, value TEXT NOT NULL)"
            )
            self._fts_enabled = True
            version = connection.execute(
                "SELECT value FROM search_state WHERE key = 'schema_version'"
            ).fetchone()
            if not version or version[0] != "1":
                self._rebuild_search_index(connection)
                connection.execute(
                    """INSERT INTO search_state(key,value) VALUES('schema_version','1')
                       ON CONFLICT(key) DO UPDATE SET value=excluded.value"""
                )
        except sqlite3.OperationalError:
            # The rest of AI Hub remains usable on Python builds without FTS5.
            self._fts_enabled = False

    @staticmethod
    def _put_search_row(
        connection: sqlite3.Connection,
        kind: str,
        ref_id: str,
        title: str,
        content: str,
        metadata: dict[str, Any] | None,
        updated_at: str,
    ) -> None:
        connection.execute(
            "DELETE FROM search_index WHERE kind = ? AND ref_id = ?", (kind, ref_id)
        )
        connection.execute(
            """INSERT INTO search_index(kind,ref_id,title,content,metadata_json,updated_at)
               VALUES(?,?,?,?,?,?)""",
            (
                kind,
                ref_id,
                title,
                content,
                json.dumps(metadata or {}, ensure_ascii=False),
                updated_at,
            ),
        )

    def _rebuild_search_index(self, connection: sqlite3.Connection) -> None:
        connection.execute("DELETE FROM search_index")
        for row in connection.execute("SELECT * FROM projects"):
            self._put_search_row(
                connection,
                "project",
                row["id"],
                row["name"],
                row["path"],
                {"project_id": row["id"], "path": row["path"]},
                row["last_opened_at"],
            )
        for row in connection.execute("SELECT * FROM conversations"):
            self._put_search_row(
                connection,
                "conversation",
                row["id"],
                row["title"],
                "",
                {"conversation_id": row["id"], "project_id": row["project_id"]},
                row["updated_at"],
            )
        for row in connection.execute("SELECT * FROM messages"):
            self._put_search_row(
                connection,
                "message",
                row["id"],
                f"{row['role']} · {row['provider_id'] or 'AI Hub'}",
                row["content"],
                {"conversation_id": row["conversation_id"]},
                row["created_at"],
            )
        for row in connection.execute("SELECT * FROM tasks"):
            body = "\n".join(
                part for part in (row["prompt"], row["result"], row["error"], row["stage"]) if part
            )
            self._put_search_row(
                connection,
                "task",
                row["id"],
                row["title"],
                body,
                {
                    "task_id": row["id"],
                    "conversation_id": row["conversation_id"],
                    "project_id": row["project_id"],
                    "status": row["status"],
                },
                row["completed_at"] or row["started_at"] or row["created_at"],
            )
        for row in connection.execute("SELECT * FROM research_documents"):
            self._put_search_row(
                connection,
                "research",
                row["id"],
                row["title"],
                f"{row['url']}\n{row['text']}",
                {"url": row["url"]},
                row["fetched_at"],
            )
        for row in connection.execute("SELECT * FROM audit_log"):
            self._put_search_row(
                connection,
                "audit",
                str(row["id"]),
                row["action"],
                f"{row['resource']}\n{row['details_json']}",
                {"resource": row["resource"]},
                row["created_at"],
            )

    def _index(
        self,
        kind: str,
        ref_id: str,
        title: str,
        content: str = "",
        metadata: dict[str, Any] | None = None,
        updated_at: str | None = None,
    ) -> None:
        if not self._fts_enabled:
            return
        with self._write_lock, self._session() as connection:
            self._put_search_row(
                connection,
                kind,
                ref_id,
                title,
                content,
                metadata,
                updated_at or utcnow(),
            )

    def search(self, query: str, limit: int = 80) -> list[dict[str, Any]]:
        """Search projects, chats, messages, tasks, research, and audit data."""
        clean = " ".join(str(query).split()).strip()
        if not clean:
            return []
        limit = max(1, min(int(limit), 200))
        if not self._fts_enabled:
            return self._search_without_fts(clean, limit)
        try:
            if len(clean) >= 3:
                terms = [term for term in clean.split(" ") if term]
                phrase = " AND ".join(
                    '"' + term.replace('"', '""') + '"' for term in terms
                )
                rows = self._all(
                    """SELECT kind,ref_id,title,
                              snippet(search_index,3,'[',']',' … ',24) AS excerpt,
                              metadata_json,updated_at,bm25(search_index) AS rank
                       FROM search_index WHERE search_index MATCH ?
                       ORDER BY rank, updated_at DESC LIMIT ?""",
                    (phrase, limit),
                )
            else:
                pattern = f"%{clean}%"
                rows = self._all(
                    """SELECT kind,ref_id,title,substr(content,1,600) AS excerpt,
                              metadata_json,updated_at,0 AS rank
                       FROM search_index WHERE title LIKE ? OR content LIKE ?
                       ORDER BY updated_at DESC LIMIT ?""",
                    (pattern, pattern, limit),
                )
        except sqlite3.OperationalError:
            return self._search_without_fts(clean, limit)
        return [self._decode(row) or {} for row in rows]

    def _search_without_fts(self, query: str, limit: int) -> list[dict[str, Any]]:
        pattern = f"%{query}%"
        rows = self._all(
            """SELECT 'message' AS kind,m.id AS ref_id,
                      m.role || ' · ' || COALESCE(m.provider_id,'AI Hub') AS title,
                      substr(m.content,1,600) AS excerpt,m.created_at AS updated_at,
                      json_object('conversation_id',m.conversation_id) AS metadata_json
               FROM messages m WHERE m.content LIKE ?
               UNION ALL
               SELECT 'task',t.id,t.title,substr(COALESCE(t.result,t.prompt),1,600),
                      COALESCE(t.completed_at,t.created_at),
                      json_object('task_id',t.id,'conversation_id',t.conversation_id)
               FROM tasks t WHERE t.title LIKE ? OR t.prompt LIKE ? OR t.result LIKE ?
               ORDER BY updated_at DESC LIMIT ?""",
            (pattern, pattern, pattern, pattern, limit),
        )
        return [self._decode(row) or {} for row in rows]

    def _execute(self, sql: str, values: Iterable[Any] = ()) -> None:
        with self._write_lock, self._session() as connection:
            connection.execute(sql, tuple(values))

    def _one(self, sql: str, values: Iterable[Any] = ()) -> dict[str, Any] | None:
        with self._session() as connection:
            row = connection.execute(sql, tuple(values)).fetchone()
        return dict(row) if row else None

    def _all(self, sql: str, values: Iterable[Any] = ()) -> list[dict[str, Any]]:
        with self._session() as connection:
            rows = connection.execute(sql, tuple(values)).fetchall()
        return [dict(row) for row in rows]

    @staticmethod
    def _decode(row: dict[str, Any] | None) -> dict[str, Any] | None:
        if row is None:
            return None
        for key in list(row):
            if key.endswith("_json"):
                target = key[:-5]
                try:
                    row[target] = json.loads(row.pop(key) or "null")
                except json.JSONDecodeError:
                    row[target] = None
        for key in ("archived", "enabled"):
            if key in row:
                row[key] = bool(row[key])
        return row

    def ensure_project(self, path: str, name: str | None = None) -> dict[str, Any]:
        normalized = str(Path(path).resolve())
        existing = self._one("SELECT * FROM projects WHERE path = ?", (normalized,))
        if existing:
            now = utcnow()
            self._execute(
                "UPDATE projects SET last_opened_at = ? WHERE id = ?",
                (now, existing["id"]),
            )
            self._index(
                "project",
                existing["id"],
                existing["name"],
                normalized,
                {"project_id": existing["id"], "path": normalized},
                now,
            )
            return self.get_project(existing["id"]) or {}
        project_id = make_id("prj")
        now = utcnow()
        self._execute(
            "INSERT INTO projects(id,name,path,created_at,last_opened_at) VALUES(?,?,?,?,?)",
            (project_id, name or Path(normalized).name or normalized, normalized, now, now),
        )
        self._index(
            "project",
            project_id,
            name or Path(normalized).name or normalized,
            normalized,
            {"project_id": project_id, "path": normalized},
            now,
        )
        return self.get_project(project_id) or {}

    def list_projects(self) -> list[dict[str, Any]]:
        return [self._decode(row) or {} for row in self._all(
            "SELECT * FROM projects ORDER BY last_opened_at DESC"
        )]

    def get_project(self, project_id: str) -> dict[str, Any] | None:
        return self._decode(self._one("SELECT * FROM projects WHERE id = ?", (project_id,)))

    def create_conversation(self, project_id: str | None, title: str = "新對話") -> dict[str, Any]:
        conversation_id = make_id("chat")
        now = utcnow()
        clean_title = title[:120] or "新對話"
        self._execute(
            "INSERT INTO conversations(id,project_id,title,created_at,updated_at) VALUES(?,?,?,?,?)",
            (conversation_id, project_id, clean_title, now, now),
        )
        self._index(
            "conversation",
            conversation_id,
            clean_title,
            "",
            {"conversation_id": conversation_id, "project_id": project_id},
            now,
        )
        return self.get_conversation(conversation_id) or {}

    def get_conversation(self, conversation_id: str) -> dict[str, Any] | None:
        return self._decode(self._one(
            "SELECT * FROM conversations WHERE id = ?", (conversation_id,)
        ))

    def list_conversations(self, include_archived: bool = False) -> list[dict[str, Any]]:
        where = "" if include_archived else "WHERE archived = 0"
        rows = self._all(
            f"SELECT * FROM conversations {where} ORDER BY updated_at DESC LIMIT 200"
        )
        return [self._decode(row) or {} for row in rows]

    def rename_conversation(self, conversation_id: str, title: str) -> None:
        now = utcnow()
        self._execute(
            "UPDATE conversations SET title = ?, updated_at = ? WHERE id = ?",
            (title[:120], now, conversation_id),
        )
        conversation = self.get_conversation(conversation_id)
        if conversation:
            self._index(
                "conversation",
                conversation_id,
                conversation["title"],
                "",
                {
                    "conversation_id": conversation_id,
                    "project_id": conversation.get("project_id"),
                },
                now,
            )

    def archive_conversation(self, conversation_id: str, archived: bool) -> None:
        self._execute(
            "UPDATE conversations SET archived = ?, updated_at = ? WHERE id = ?",
            (int(archived), utcnow(), conversation_id),
        )

    def add_message(
        self,
        conversation_id: str,
        role: str,
        content: str,
        provider_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        message_id = make_id("msg")
        now = utcnow()
        self._execute(
            "INSERT INTO messages(id,conversation_id,role,provider_id,content,metadata_json,created_at) VALUES(?,?,?,?,?,?,?)",
            (message_id, conversation_id, role, provider_id, content, json.dumps(metadata or {}), now),
        )
        self._index(
            "message",
            message_id,
            f"{role} · {provider_id or 'AI Hub'}",
            content,
            {"conversation_id": conversation_id, "provider_id": provider_id},
            now,
        )
        self._execute(
            "UPDATE conversations SET updated_at = ? WHERE id = ?", (now, conversation_id)
        )
        if role == "user":
            conversation = self.get_conversation(conversation_id)
            if conversation and conversation["title"] == "新對話":
                clean = " ".join(content.split())
                self.rename_conversation(conversation_id, clean[:42] or "新對話")
        return self._decode(self._one("SELECT * FROM messages WHERE id = ?", (message_id,))) or {}

    def list_messages(self, conversation_id: str) -> list[dict[str, Any]]:
        return [self._decode(row) or {} for row in self._all(
            "SELECT * FROM messages WHERE conversation_id = ? ORDER BY created_at, rowid",
            (conversation_id,),
        )]

    def create_task(
        self,
        provider_id: str,
        title: str,
        prompt: str,
        conversation_id: str | None,
        project_id: str | None,
        predicted_seconds: int | None,
        predicted_end_at: str | None,
        parent_task_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        task_id = make_id("task")
        self._execute(
            """INSERT INTO tasks(
                id,conversation_id,project_id,parent_task_id,provider_id,title,prompt,status,stage,
                progress,predicted_seconds,predicted_end_at,metadata_json,created_at
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                task_id, conversation_id, project_id, parent_task_id, provider_id, title[:160],
                prompt, "queued", "等待執行", 0, predicted_seconds, predicted_end_at,
                json.dumps(metadata or {}), utcnow(),
            ),
        )
        task = self.get_task(task_id) or {}
        self._index_task(task)
        return task

    def update_task(self, task_id: str, **values: Any) -> None:
        allowed = {
            "status", "stage", "progress", "predicted_seconds", "predicted_end_at",
            "session_id", "result", "error", "metadata_json", "started_at", "completed_at",
        }
        assignments: list[str] = []
        parameters: list[Any] = []
        for key, value in values.items():
            if key not in allowed:
                continue
            if key == "metadata_json" and not isinstance(value, str):
                value = json.dumps(value)
            assignments.append(f"{key} = ?")
            parameters.append(value)
        if assignments:
            parameters.append(task_id)
            self._execute(
                f"UPDATE tasks SET {', '.join(assignments)} WHERE id = ?", parameters
            )
            task = self.get_task(task_id)
            if task:
                self._index_task(task)

    def _index_task(self, task: dict[str, Any]) -> None:
        if not task:
            return
        body = "\n".join(
            str(part)
            for part in (
                task.get("prompt"),
                task.get("result"),
                task.get("error"),
                task.get("stage"),
            )
            if part
        )
        self._index(
            "task",
            task["id"],
            task.get("title") or "工作",
            body,
            {
                "task_id": task["id"],
                "conversation_id": task.get("conversation_id"),
                "project_id": task.get("project_id"),
                "status": task.get("status"),
                "provider_id": task.get("provider_id"),
            },
            task.get("completed_at") or task.get("started_at") or task.get("created_at"),
        )

    def get_task(self, task_id: str) -> dict[str, Any] | None:
        return self._decode(self._one("SELECT * FROM tasks WHERE id = ?", (task_id,)))

    def list_tasks(
        self, conversation_id: str | None = None, active_only: bool = False, limit: int = 100
    ) -> list[dict[str, Any]]:
        conditions: list[str] = []
        values: list[Any] = []
        if conversation_id:
            conditions.append("conversation_id = ?")
            values.append(conversation_id)
        if active_only:
            conditions.append("status IN ('queued','running','cancelling')")
        where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        values.append(limit)
        rows = self._all(
            f"SELECT * FROM tasks {where} ORDER BY created_at DESC LIMIT ?", values
        )
        return [self._decode(row) or {} for row in rows]

    def add_task_event(
        self, task_id: str, message: str, level: str = "info", progress: float | None = None
    ) -> None:
        self._execute(
            "INSERT INTO task_events(task_id,level,message,progress,created_at) VALUES(?,?,?,?,?)",
            (task_id, level, message[-6000:], progress, utcnow()),
        )

    def list_task_events(self, task_id: str, after: int = 0) -> list[dict[str, Any]]:
        return self._all(
            "SELECT * FROM task_events WHERE task_id = ? AND id > ? ORDER BY id LIMIT 500",
            (task_id, after),
        )

    def create_approval(
        self, kind: str, summary: str, fingerprint: str, payload: dict[str, Any]
    ) -> dict[str, Any]:
        existing = self._one(
            "SELECT * FROM approvals WHERE fingerprint = ? AND status = 'pending' ORDER BY created_at DESC LIMIT 1",
            (fingerprint,),
        )
        if existing:
            return self._decode(existing) or {}
        approval_id = make_id("approval")
        self._execute(
            "INSERT INTO approvals(id,kind,summary,fingerprint,payload_json,status,created_at) VALUES(?,?,?,?,?,?,?)",
            (approval_id, kind, summary, fingerprint, json.dumps(payload), "pending", utcnow()),
        )
        return self.get_approval(approval_id) or {}

    def get_approval(self, approval_id: str) -> dict[str, Any] | None:
        return self._decode(self._one("SELECT * FROM approvals WHERE id = ?", (approval_id,)))

    def resolve_approval(self, approval_id: str, approved: bool) -> dict[str, Any] | None:
        self._execute(
            "UPDATE approvals SET status = ?, resolved_at = ? WHERE id = ? AND status = 'pending'",
            ("approved" if approved else "rejected", utcnow(), approval_id),
        )
        return self.get_approval(approval_id)

    def approval_valid(self, approval_id: str | None, fingerprint: str) -> bool:
        if not approval_id:
            return False
        row = self.get_approval(approval_id)
        if not row or row["status"] != "approved" or row["fingerprint"] != fingerprint:
            return False
        try:
            created = datetime.fromisoformat(row["created_at"])
            if created.tzinfo is None:
                created = created.replace(tzinfo=timezone.utc)
            if datetime.now(timezone.utc) - created.astimezone(timezone.utc) > timedelta(minutes=5):
                self._execute("UPDATE approvals SET status = 'expired', resolved_at = ? WHERE id = ?", (utcnow(), approval_id))
                return False
        except (TypeError, ValueError):
            return False
        self._execute("UPDATE approvals SET status = 'consumed', resolved_at = ? WHERE id = ? AND status = 'approved'", (utcnow(), approval_id))
        return True

    def pending_approvals(self) -> list[dict[str, Any]]:
        return [self._decode(row) or {} for row in self._all(
            "SELECT * FROM approvals WHERE status = 'pending' ORDER BY created_at DESC"
        )]

    def add_metric(
        self,
        provider_id: str,
        workload: str,
        predicted_seconds: int | None,
        duration_seconds: float,
        success: bool,
    ) -> None:
        self._execute(
            "INSERT INTO provider_metrics(provider_id,workload,predicted_seconds,duration_seconds,success,created_at) VALUES(?,?,?,?,?,?)",
            (provider_id, workload, predicted_seconds, duration_seconds, int(success), utcnow()),
        )

    def provider_metrics(self, provider_id: str) -> dict[str, Any]:
        row = self._one(
            """SELECT COUNT(*) AS samples,
               AVG(duration_seconds) AS average_seconds,
               AVG(success) AS success_rate,
               AVG(ABS(duration_seconds - predicted_seconds)) AS mean_eta_error
               FROM provider_metrics WHERE provider_id = ?""",
            (provider_id,),
        )
        return row or {"samples": 0, "average_seconds": None, "success_rate": None, "mean_eta_error": None}

    def set_task_feedback(self, task_id: str, success: bool, note: str = "") -> dict[str, Any]:
        if not self.get_task(task_id):
            raise ValueError("找不到工作。")
        self._execute(
            """INSERT INTO task_feedback(task_id,success,note,created_at) VALUES(?,?,?,?)
               ON CONFLICT(task_id) DO UPDATE SET success=excluded.success,note=excluded.note,created_at=excluded.created_at""",
            (task_id, int(success), note[:1000], utcnow()),
        )
        row = self._one("SELECT * FROM task_feedback WHERE task_id = ?", (task_id,)) or {}
        row["success"] = bool(row.get("success"))
        task = self.get_task(task_id)
        if task and note:
            task["result"] = f"{task.get('result') or ''}\n使用者驗證：{note}".strip()
            self._index_task(task)
        return row

    def feasibility_examples(self, limit: int = 500) -> list[dict[str, Any]]:
        rows = self._all(
            """SELECT t.id,t.status,t.metadata_json,f.success AS feedback_success
               FROM tasks t LEFT JOIN task_feedback f ON f.task_id=t.id
               WHERE t.status IN ('completed','failed')
               ORDER BY t.created_at DESC LIMIT ?""",
            (limit,),
        )
        examples: list[dict[str, Any]] = []
        for row in rows:
            try:
                metadata = json.loads(row.get("metadata_json") or "{}")
            except json.JSONDecodeError:
                continue
            feasibility = metadata.get("feasibility")
            factors = feasibility.get("factors") if isinstance(feasibility, dict) else None
            if not isinstance(factors, list):
                continue
            scores = {
                str(item.get("key")): float(item.get("score", 50))
                for item in factors
                if isinstance(item, dict) and item.get("key")
            }
            examples.append(
                {
                    "task_id": row["id"],
                    "factors": scores,
                    "success": bool(row["feedback_success"])
                    if row["feedback_success"] is not None
                    else row["status"] == "completed",
                    "verified": row["feedback_success"] is not None,
                }
            )
        return examples

    def audit(self, action: str, resource: str, details: dict[str, Any] | None = None) -> None:
        now = utcnow()
        serialized = json.dumps(details or {})
        with self._write_lock, self._session() as connection:
            cursor = connection.execute(
                "INSERT INTO audit_log(action,resource,details_json,created_at) VALUES(?,?,?,?)",
                (action, resource, serialized, now),
            )
            if self._fts_enabled:
                self._put_search_row(
                    connection,
                    "audit",
                    str(cursor.lastrowid),
                    action,
                    f"{resource}\n{json.dumps(details or {}, ensure_ascii=False)}",
                    {"resource": resource},
                    now,
                )

    def list_audit(self, limit: int = 100) -> list[dict[str, Any]]:
        return [self._decode(row) or {} for row in self._all(
            "SELECT * FROM audit_log ORDER BY id DESC LIMIT ?", (limit,)
        )]

    def create_schedule(self, payload: dict[str, Any]) -> dict[str, Any]:
        schedule_id = make_id("schedule")
        self._execute(
            """INSERT INTO schedules(
                id,name,prompt,project_id,provider_ids_json,start_time,end_time,duration_minutes,
                interval_minutes,weekdays_json,mode,enabled,created_at
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                schedule_id, payload["name"], payload["prompt"], payload["project_id"],
                json.dumps(payload["provider_ids"]), payload.get("start_time", "00:00"),
                payload.get("end_time", "23:59"), int(payload.get("duration_minutes", 60)),
                max(5, int(payload.get("interval_minutes", 1440))),
                json.dumps(payload.get("weekdays", [0, 1, 2, 3, 4, 5, 6])),
                payload.get("mode", "improve"), int(payload.get("enabled", True)), utcnow(),
            ),
        )
        return self.get_schedule(schedule_id) or {}

    def get_schedule(self, schedule_id: str) -> dict[str, Any] | None:
        return self._decode(self._one("SELECT * FROM schedules WHERE id = ?", (schedule_id,)))

    def list_schedules(self) -> list[dict[str, Any]]:
        return [self._decode(row) or {} for row in self._all(
            "SELECT * FROM schedules ORDER BY created_at DESC"
        )]

    def update_schedule(self, schedule_id: str, values: dict[str, Any]) -> None:
        allowed = {
            "name", "prompt", "start_time", "end_time", "duration_minutes", "interval_minutes", "mode",
            "enabled", "last_run_at", "next_run_at", "provider_ids_json", "weekdays_json",
        }
        assignments: list[str] = []
        parameters: list[Any] = []
        for key, value in values.items():
            if key not in allowed:
                continue
            if key in {"provider_ids_json", "weekdays_json"} and not isinstance(value, str):
                value = json.dumps(value)
            if key == "enabled":
                value = int(bool(value))
            assignments.append(f"{key} = ?")
            parameters.append(value)
        if assignments:
            parameters.append(schedule_id)
            self._execute(f"UPDATE schedules SET {', '.join(assignments)} WHERE id = ?", parameters)

    def delete_schedule(self, schedule_id: str) -> None:
        self._execute("DELETE FROM schedules WHERE id = ?", (schedule_id,))

    def save_research_document(
        self, url: str, title: str, text: str, metadata: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        document_id = make_id("doc")
        now = utcnow()
        self._execute(
            "INSERT INTO research_documents(id,url,title,text,fetched_at,metadata_json) VALUES(?,?,?,?,?,?)",
            (document_id, url, title, text, now, json.dumps(metadata or {})),
        )
        self._index(
            "research",
            document_id,
            title,
            f"{url}\n{text}",
            {"url": url},
            now,
        )
        return self._decode(self._one(
            "SELECT * FROM research_documents WHERE id = ?", (document_id,)
        )) or {}

    def list_research_documents(self, limit: int = 100) -> list[dict[str, Any]]:
        rows = self._all(
            "SELECT id,url,title,substr(text,1,500) AS excerpt,fetched_at,metadata_json FROM research_documents ORDER BY fetched_at DESC LIMIT ?",
            (limit,),
        )
        return [self._decode(row) or {} for row in rows]

    def search_research_documents(self, query: str, limit: int = 4) -> list[dict[str, Any]]:
        words = [word for word in query.replace("\n", " ").split(" ") if len(word.strip()) >= 3][:8]
        if not words:
            return []
        conditions = " OR ".join("text LIKE ? OR title LIKE ?" for _ in words)
        values: list[Any] = []
        for word in words:
            pattern = f"%{word.strip()}%"
            values.extend([pattern, pattern])
        values.append(limit)
        rows = self._all(
            f"SELECT id,url,title,substr(text,1,5000) AS text,fetched_at,metadata_json "
            f"FROM research_documents WHERE {conditions} ORDER BY fetched_at DESC LIMIT ?",
            values,
        )
        return [self._decode(row) or {} for row in rows]
