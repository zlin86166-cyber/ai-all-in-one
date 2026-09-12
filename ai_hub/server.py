from __future__ import annotations

import base64
import hmac
import ipaddress
import json
import mimetypes
import re
import traceback
import urllib.parse
from http import HTTPStatus
from http.cookies import CookieError, SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from .application import AIHubApplication, ApprovalRequired
from .config import APP_VERSION


class APIError(RuntimeError):
    def __init__(self, status: int, message: str, details: dict[str, Any] | None = None):
        super().__init__(message)
        self.status = status
        self.details = details or {}


def _is_loopback_host(host: str) -> bool:
    normalized = str(host or "").strip().lower().strip("[]")
    if normalized == "localhost":
        return True
    try:
        return bool(ipaddress.ip_address(normalized).is_loopback)
    except ValueError:
        return False


def create_server(app: AIHubApplication, host: str, port: int) -> ThreadingHTTPServer:
    if not _is_loopback_host(host):
        raise ValueError("AI Hub 本機 API 只允許繫結到 loopback 位址。")
    class Handler(AIHubHandler):
        application = app

    server = ThreadingHTTPServer((host, port), Handler)
    server.daemon_threads = True
    return server


class AIHubHandler(BaseHTTPRequestHandler):
    application: AIHubApplication
    server_version = f"AIHub/{APP_VERSION}"

    def log_message(self, format_string: str, *args: Any) -> None:
        if self.path.startswith("/api/") and not self.path.startswith("/api/health"):
            super().log_message(format_string, *args)

    def _json_body(self, limit: int = 12_000_000) -> dict[str, Any]:
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError as error:
            raise APIError(400, "Content-Length 無效。") from error
        if length > limit:
            raise APIError(413, "請求內容過大。")
        if not length:
            return {}
        try:
            value = json.loads(self.rfile.read(length).decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise APIError(400, "JSON 格式無效。") from error
        if not isinstance(value, dict):
            raise APIError(400, "JSON 根節點必須是物件。")
        return value

    def _send_json(self, payload: Any, status: int = 200) -> None:
        body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(body)

    def _send_file(self, target: Path, download_name: str | None = None) -> None:
        body = target.read_bytes()
        content_type = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "private, max-age=31536000, immutable")
        self.send_header("X-Content-Type-Options", "nosniff")
        if download_name:
            quoted = urllib.parse.quote(download_name)
            self.send_header("Content-Disposition", f"attachment; filename*=UTF-8''{quoted}")
        self.end_headers()
        self.wfile.write(body)

    def _send_download(self, body: bytes, name: str, content_type: str) -> None:
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header(
            "Content-Disposition", f"attachment; filename*=UTF-8''{urllib.parse.quote(name)}"
        )
        self.end_headers()
        self.wfile.write(body)

    def _route(self) -> tuple[str, dict[str, list[str]]]:
        parsed = urllib.parse.urlparse(self.path)
        return parsed.path, urllib.parse.parse_qs(parsed.query)

    def _require_api_session(self) -> None:
        cookie = SimpleCookie()
        try:
            cookie.load(self.headers.get("Cookie", ""))
        except CookieError as error:
            raise APIError(400, "Cookie 格式無效。") from error
        session = cookie.get("ai_hub_session")
        if not session or not hmac.compare_digest(session.value, self.application.session_token):
            raise APIError(401, "需要本機工作階段；請從 AI Hub 入口頁重新載入。")
        origin = self.headers.get("Origin")
        if origin:
            parsed = urllib.parse.urlparse(origin)
            expected_host = self.headers.get("Host", "")
            if (
                parsed.scheme not in {"http", "https"}
                or parsed.netloc.lower() != expected_host.lower()
            ):
                raise APIError(403, "拒絕跨來源 API 請求。")

    def do_GET(self) -> None:
        try:
            path, query = self._route()
            if path.startswith("/api/") and path != "/api/health":
                self._require_api_session()
            if path == "/api/health":
                self._send_json({"ok": True, "version": APP_VERSION})
                return
            if path == "/api/bootstrap":
                self._send_json(self.application.bootstrap())
                return
            if path == "/api/system":
                self._send_json(self.application.hardware.snapshot())
                return
            if path == "/api/providers":
                self._send_json(self.application.providers.status(force=True))
                return
            if path == "/api/models":
                self._send_json({"catalog": self.application.models.catalog(), "readiness": self.application.models.readiness()})
                return
            if path == "/api/projects":
                self._send_json(self.application.database.list_projects())
                return
            if path == "/api/conversations":
                self._send_json(self.application.database.list_conversations(query.get("archived") == ["1"]))
                return
            match = re.fullmatch(r"/api/conversations/([^/]+)", path)
            if match:
                conversation_id = match.group(1)
                conversation = self.application.database.get_conversation(conversation_id)
                if not conversation:
                    raise APIError(404, "找不到對話。")
                self._send_json(
                    {
                        "conversation": conversation,
                        "messages": self.application.database.list_messages(conversation_id),
                        "tasks": self.application.database.list_tasks(conversation_id=conversation_id),
                    }
                )
                return
            match = re.fullmatch(r"/api/conversations/([^/]+)/export", path)
            if match:
                name, body = self.application.export_conversation(match.group(1))
                self._send_download(body, name, "text/markdown; charset=utf-8")
                return
            if path == "/api/tasks":
                conversation_id = (query.get("conversation_id") or [None])[0]
                self._send_json(self.application.database.list_tasks(conversation_id=conversation_id))
                return
            match = re.fullmatch(r"/api/tasks/([^/]+)/events", path)
            if match:
                after = int((query.get("after") or ["0"])[0])
                self._send_json(self.application.database.list_task_events(match.group(1), after))
                return
            if path == "/api/files":
                project_id = (query.get("project_id") or [""])[0]
                target = (query.get("path") or [None])[0]
                self._send_json(self.application.list_files(project_id, target))
                return
            if path == "/api/file":
                project_id = (query.get("project_id") or [""])[0]
                target = (query.get("path") or [""])[0]
                self._send_json(self.application.read_file(project_id, target))
                return
            if path == "/api/schedules":
                self._send_json(self.application.database.list_schedules())
                return
            if path == "/api/approvals":
                self._send_json(self.application.database.pending_approvals())
                return
            if path == "/api/audit":
                self._send_json(self.application.database.list_audit())
                return
            if path == "/api/research":
                self._send_json(self.application.database.list_research_documents())
                return
            if path == "/api/images/status":
                self._send_json(self.application.images.status())
                return
            match = re.fullmatch(r"/api/images/file/([^/]+)", path)
            if match:
                self._send_file(self.application.images.resolve_output(match.group(1)))
                return
            self._serve_static(path)
        except Exception as error:
            self._handle_error(error)

    def do_POST(self) -> None:
        try:
            path, _query = self._route()
            if path.startswith("/api/") and path != "/api/health":
                self._require_api_session()
            payload = self._json_body(15_000_000 if path == "/api/files/import" else 12_000_000)
            if path == "/api/projects":
                self._send_json(self.application.add_project(str(payload.get("path") or ""), payload.get("name")), 201)
                return
            if path == "/api/dialog/folder":
                selected = self.application.choose_folder()
                self._send_json({"path": selected})
                return
            if path == "/api/conversations":
                self._send_json(
                    self.application.create_conversation(payload.get("project_id"), str(payload.get("title") or "新對話")),
                    201,
                )
                return
            if path == "/api/run":
                self._send_json(self.application.run_prompt(payload), 202)
                return
            if path == "/api/terminal":
                self._send_json(self.application.run_terminal(payload), 202)
                return
            if path == "/api/settings":
                self._send_json(self.application.update_settings(payload))
                return
            if path == "/api/full-access/unlock":
                self._send_json(self.application.unlock_full_access(str(payload.get("phrase") or ""), int(payload.get("minutes", 30))))
                return
            if path == "/api/full-access/lock":
                self._send_json(self.application.lock_full_access())
                return
            match = re.fullmatch(r"/api/tasks/([^/]+)/cancel", path)
            if match:
                stopped = self.application.tasks.cancel(match.group(1))
                self._send_json({"cancel_requested": stopped}, 202 if stopped else 404)
                return
            match = re.fullmatch(r"/api/tasks/([^/]+)/feedback", path)
            if match:
                if "success" not in payload:
                    raise APIError(400, "缺少 success。")
                feedback = self.application.database.set_task_feedback(
                    match.group(1), bool(payload["success"]), str(payload.get("note") or "")
                )
                self.application.database.audit(
                    "task.feedback", match.group(1), {"success": feedback["success"]}
                )
                self._send_json(feedback)
                return
            match = re.fullmatch(r"/api/approvals/([^/]+)/(approve|reject)", path)
            if match:
                resolved = self.application.database.resolve_approval(match.group(1), match.group(2) == "approve")
                if not resolved:
                    raise APIError(404, "找不到核准項目。")
                self.application.database.audit("approval.resolved", match.group(1), {"status": resolved["status"]})
                self._send_json(resolved)
                return
            if path == "/api/file":
                self._send_json(self.application.write_file(payload))
                return
            if path == "/api/files/import":
                encoded = str(payload.get("base64") or "")
                try:
                    content = base64.b64decode(encoded, validate=True)
                except ValueError as error:
                    raise APIError(400, "Base64 檔案內容無效。") from error
                if len(content) > 10_000_000:
                    raise APIError(413, "單檔匯入上限為 10 MB。")
                self._send_json(self.application.import_file(payload, content))
                return
            if path == "/api/open-path":
                self._send_json(self.application.open_in_explorer(str(payload.get("project_id") or ""), payload.get("path")))
                return
            if path == "/api/models/pull":
                project = self.application.get_project(payload.get("project_id"))
                self._send_json(
                    self.application.pull_model(payload),
                    202,
                )
                self.application.providers.invalidate()
                return
            if path == "/api/research/fetch":
                self._send_json(self.application.research_fetch(payload), 201)
                return
            if path == "/api/images/generate":
                project = self.application.get_project(payload.get("project_id"))
                self._send_json(
                    self.application.images.launch(
                        payload, project, payload.get("conversation_id")
                    ),
                    202,
                )
                return
            if path == "/api/schedules":
                project = self.application.get_project(payload.get("project_id"))
                payload["project_id"] = project["id"]
                provider_ids = [str(item) for item in payload.get("provider_ids", [])]
                if payload.get("mode") == "image":
                    image_status = self.application.images.status()
                    if not image_status["available"] or not image_status["checkpoints"]:
                        raise ValueError("繪圖排程需要已連線且已安裝 checkpoint 的 ComfyUI。")
                    provider_ids = []
                else:
                    if not provider_ids:
                        raise ValueError("改善排程至少需要一個可用 AI。")
                    self.application._provider_status_for(provider_ids)
                payload["provider_ids"] = provider_ids
                self._send_json(self.application.database.create_schedule(payload), 201)
                return
            match = re.fullmatch(r"/api/schedules/([^/]+)/(toggle|delete)", path)
            if match:
                schedule = self.application.database.get_schedule(match.group(1))
                if not schedule:
                    raise APIError(404, "找不到排程。")
                if match.group(2) == "delete":
                    self.application.database.delete_schedule(match.group(1))
                    self._send_json({"deleted": True})
                else:
                    self.application.database.update_schedule(match.group(1), {"enabled": not schedule["enabled"]})
                    self._send_json(self.application.database.get_schedule(match.group(1)))
                return
            raise APIError(404, "找不到 API。")
        except Exception as error:
            self._handle_error(error)

    def do_PATCH(self) -> None:
        try:
            path, _query = self._route()
            if path.startswith("/api/") and path != "/api/health":
                self._require_api_session()
            payload = self._json_body()
            match = re.fullmatch(r"/api/conversations/([^/]+)", path)
            if match:
                if "title" in payload:
                    self.application.database.rename_conversation(match.group(1), str(payload["title"]))
                if "archived" in payload:
                    self.application.database.archive_conversation(match.group(1), bool(payload["archived"]))
                self._send_json(self.application.database.get_conversation(match.group(1)))
                return
            raise APIError(404, "找不到 API。")
        except Exception as error:
            self._handle_error(error)

    def _serve_static(self, request_path: str) -> None:
        relative = "index.html" if request_path in {"", "/"} else urllib.parse.unquote(request_path.lstrip("/"))
        target = (self.application.paths.web / relative).resolve()
        try:
            target.relative_to(self.application.paths.web.resolve())
        except ValueError as error:
            raise APIError(403, "禁止存取。") from error
        if not target.is_file():
            target = self.application.paths.web / "index.html"
        body = target.read_bytes()
        content_type = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
        self.send_response(200)
        self.send_header("Content-Type", f"{content_type}; charset=utf-8" if content_type.startswith("text/") or content_type in {"application/javascript", "application/json"} else content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-cache")
        self.send_header(
            "Set-Cookie",
            f"ai_hub_session={self.application.session_token}; HttpOnly; SameSite=Strict; Path=/",
        )
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Security-Policy", "default-src 'self'; img-src 'self' data: blob:; style-src 'self' 'unsafe-inline'; script-src 'self'; connect-src 'self';")
        self.end_headers()
        self.wfile.write(body)

    def _handle_error(self, error: Exception) -> None:
        if isinstance(error, ApprovalRequired):
            self._send_json(
                {"error": str(error), "code": "approval_required", "approval": error.approval},
                HTTPStatus.CONFLICT,
            )
            return
        if isinstance(error, APIError):
            self._send_json({"error": str(error), **error.details}, error.status)
            return
        if isinstance(error, (ValueError, FileNotFoundError, NotADirectoryError)):
            self._send_json({"error": str(error)}, HTTPStatus.BAD_REQUEST)
            return
        if isinstance(error, PermissionError):
            self._send_json({"error": str(error)}, HTTPStatus.FORBIDDEN)
            return
        traceback.print_exc()
        self._send_json({"error": f"伺服器錯誤：{error}"}, HTTPStatus.INTERNAL_SERVER_ERROR)
