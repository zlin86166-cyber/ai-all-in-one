from __future__ import annotations

import json
import hashlib
import os
import queue
import shutil
import subprocess
import tempfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from .config import AppPaths, Settings


Emit = Callable[[str, str, float | None, str], None]


@dataclass
class ProviderContext:
    prompt: str
    project_path: Path
    permission_mode: str
    selected_files: list[str] = field(default_factory=list)
    history: list[dict[str, Any]] = field(default_factory=list)
    web_access: bool = True
    model: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class ProviderResult:
    text: str
    session_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


class ProviderError(RuntimeError):
    pass


def _runtime_environment(paths: AppPaths) -> dict[str, str]:
    environment = os.environ.copy()
    path_entries: list[str] = []
    cli_bin = paths.runtime / "cli" / "node_modules" / ".bin"
    if cli_bin.exists():
        path_entries.append(str(cli_bin))
    openai_bin = paths.runtime / "openai-cli"
    if openai_bin.exists():
        path_entries.append(str(openai_bin))
    portable_node = paths.runtime / "node"
    if portable_node.exists():
        for executable in portable_node.rglob("node.exe"):
            path_entries.append(str(executable.parent))
            break
    bundled = Path(
        os.environ.get(
            "AI_HUB_BUNDLED_NODE",
            r"C:\Users\ASUS\.cache\codex-runtimes\codex-primary-runtime\dependencies\node\bin",
        )
    )
    if bundled.exists():
        path_entries.append(str(bundled))
    environment["PATH"] = os.pathsep.join(path_entries + [environment.get("PATH", "")])
    environment["PYTHONUTF8"] = "1"
    environment["NO_COLOR"] = "1"
    return environment


def _find_command(name: str, paths: AppPaths) -> Path | None:
    explicit = os.environ.get(f"AI_HUB_{name.upper()}_PATH")
    candidates: list[Path] = []
    if explicit:
        candidates.append(Path(explicit))
    for extension in (".cmd", ".exe", ".ps1", ""):
        candidates.append(paths.runtime / "cli" / "node_modules" / ".bin" / f"{name}{extension}")
    found = shutil.which(name, path=_runtime_environment(paths).get("PATH"))
    if found:
        candidates.append(Path(found))
    for candidate in candidates:
        if candidate.exists() and candidate.is_file():
            return candidate
    return None


def _codex_authenticated() -> bool:
    auth_file = Path(os.environ.get("CODEX_HOME", str(Path.home() / ".codex"))) / "auth.json"
    return bool(os.environ.get("OPENAI_API_KEY") or os.environ.get("CODEX_API_KEY") or auth_file.is_file())


def _gemini_authenticated() -> bool:
    if any(
        os.environ.get(name)
        for name in (
            "GEMINI_API_KEY",
            "GOOGLE_API_KEY",
            "GOOGLE_GENAI_USE_VERTEXAI",
            "GOOGLE_GENAI_USE_GCA",
        )
    ):
        return True
    gemini_home = Path.home() / ".gemini"
    credential_names = ("oauth_creds.json", "google_accounts.json")
    if any((gemini_home / name).is_file() for name in credential_names):
        return True
    settings_file = gemini_home / "settings.json"
    if not settings_file.is_file():
        return False
    try:
        settings = json.loads(settings_file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False

    def has_auth(value: Any, key: str = "") -> bool:
        if isinstance(value, dict):
            return any(
                has_auth(item, f"{key}.{name}" if key else str(name))
                for name, item in value.items()
            )
        if isinstance(value, list):
            return any(has_auth(item, key) for item in value)
        return "auth" in key.lower() and bool(value)

    return has_auth(settings)


def _process_command(executable: Path, arguments: list[str]) -> list[str]:
    suffix = executable.suffix.lower()
    if suffix == ".cmd" or suffix == ".bat":
        command_line = subprocess.list2cmdline([str(executable), *arguments])
        return ["cmd.exe", "/d", "/s", "/c", command_line]
    if suffix == ".ps1":
        return ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(executable), *arguments]
    return [str(executable), *arguments]


def _run_process(
    command: list[str],
    cwd: Path,
    environment: dict[str, str],
    emit: Emit,
    cancel: threading.Event,
    stdin_text: str | None = None,
    parse_line: Callable[[str], None] | None = None,
) -> tuple[int, list[str]]:
    creation_flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0
    try:
        process = subprocess.Popen(
            command,
            cwd=str(cwd),
            env=environment,
            stdin=subprocess.PIPE if stdin_text is not None else subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
            creationflags=creation_flags,
        )
    except OSError as error:
        raise ProviderError(f"無法啟動 {command[0]}：{error}") from error
    if stdin_text is not None and process.stdin:
        try:
            process.stdin.write(stdin_text)
            process.stdin.close()
        except OSError:
            pass
    output_queue: queue.Queue[str | None] = queue.Queue()

    def read_output() -> None:
        assert process.stdout is not None
        for raw_line in process.stdout:
            output_queue.put(raw_line.rstrip("\r\n"))
        output_queue.put(None)

    reader = threading.Thread(target=read_output, daemon=True)
    reader.start()
    lines: list[str] = []
    finished_output = False
    last_heartbeat = time.monotonic()
    while process.poll() is None or not finished_output:
        if cancel.is_set() and process.poll() is None:
            emit("正在停止", "已送出停止訊號", None, "warning")
            if os.name == "nt":
                subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"], capture_output=True,
                               creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            else:
                process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
        try:
            item = output_queue.get(timeout=0.35)
        except queue.Empty:
            if time.monotonic() - last_heartbeat > 5:
                emit("模型仍在執行", "等待下一個進度事件…", None, "debug")
                last_heartbeat = time.monotonic()
            continue
        if item is None:
            finished_output = True
            continue
        lines.append(item)
        if parse_line:
            parse_line(item)
        else:
            emit("執行中", item, None, "output")
    reader.join(timeout=1)
    return process.returncode or 0, lines


class BaseProvider:
    id = "base"
    label = "Base"
    kind = "cli"

    def run(self, context: ProviderContext, emit: Emit, cancel: threading.Event) -> ProviderResult:
        raise NotImplementedError


class CodexProvider(BaseProvider):
    id = "codex"
    label = "Codex"
    kind = "cli"

    def __init__(self, paths: AppPaths):
        self.paths = paths

    @property
    def command(self) -> Path | None:
        return _find_command("codex", self.paths)

    def run(self, context: ProviderContext, emit: Emit, cancel: threading.Event) -> ProviderResult:
        executable = self.command
        if not executable:
            raise ProviderError("找不到 Codex CLI。請到「模型與連線」執行 CLI 安裝。")
        output_file = Path(tempfile.mkstemp(prefix="ai-hub-codex-", suffix=".txt", dir=self.paths.data)[1])
        arguments: list[str] = []
        if context.web_access:
            arguments.append("--search")
        unsafe_full = os.environ.get("AI_HUB_UNSAFE_FULL_CLI") == "1"
        if context.permission_mode == "full" and unsafe_full:
            arguments.append("--dangerously-bypass-approvals-and-sandbox")
        else:
            arguments.extend(["--ask-for-approval", "never"])
        arguments.extend([
            "exec",
            "--json",
            "--color",
            "never",
            "--skip-git-repo-check",
            "--output-last-message",
            str(output_file),
            "-C",
            str(context.project_path),
        ])
        if context.permission_mode == "observe":
            arguments.extend(["--sandbox", "read-only"])
        elif context.permission_mode in {"workspace", "full"} and not unsafe_full:
            arguments.extend(["--sandbox", "workspace-write"])
        arguments.append("-")
        session_id: str | None = None
        final_fragments: list[str] = []
        tool_count = 0

        def parse(line: str) -> None:
            nonlocal session_id, tool_count
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                if line.strip():
                    emit("Codex", line, None, "output")
                return
            event_type = event.get("type", "event")
            if event_type in {"thread.started", "session.started"}:
                session_id = event.get("thread_id") or event.get("session_id")
                emit("工作階段已建立", session_id or "Codex session", 8, "info")
                return
            item = event.get("item") or {}
            item_type = item.get("type")
            if item_type in {"agent_message", "message"} and item.get("text"):
                final_fragments.append(str(item["text"]))
                emit("產生回覆", str(item["text"]), 88, "message")
            elif item_type in {"command_execution", "mcp_tool_call", "file_change"}:
                tool_count += 1
                label = item.get("command") or item.get("name") or item_type
                emit("執行工具", str(label)[:500], min(82, 18 + tool_count * 6), "tool")
            elif event_type == "turn.completed":
                emit("收尾與驗證", "Codex 已完成本輪工作", 96, "info")
            elif event_type.endswith("failed"):
                emit("Codex 錯誤", json.dumps(event, ensure_ascii=False)[:1500], None, "error")
            else:
                emit("Codex 執行中", event_type, None, "debug")

        emit("啟動 Codex", "使用 JSONL 事件串流", 3, "info")
        prompt = _prompt_with_history(context)
        try:
            code, lines = _run_process(
                _process_command(executable, arguments),
                context.project_path,
                _runtime_environment(self.paths),
                emit,
                cancel,
                stdin_text=prompt,
                parse_line=parse,
            )
            text = output_file.read_text(encoding="utf-8", errors="replace").strip() if output_file.exists() else ""
        finally:
            try:
                output_file.unlink(missing_ok=True)
            except OSError:
                pass
        if cancel.is_set():
            raise ProviderError("工作已由使用者停止。")
        if code != 0:
            detail = "\n".join(lines[-20:])
            raise ProviderError(f"Codex CLI 結束碼 {code}\n{detail[-5000:]}")
        if not text:
            text = "\n\n".join(final_fragments).strip()
        return ProviderResult(text=text or "Codex 已完成，但沒有文字輸出。", session_id=session_id, metadata={"tool_calls": tool_count})


class GeminiProvider(BaseProvider):
    id = "gemini"
    label = "Gemini CLI"
    kind = "cli"

    def __init__(self, paths: AppPaths):
        self.paths = paths

    @property
    def command(self) -> Path | None:
        return _find_command("gemini", self.paths)

    def run(self, context: ProviderContext, emit: Emit, cancel: threading.Event) -> ProviderResult:
        executable = self.command
        if not executable:
            raise ProviderError("找不到 Gemini CLI。請到「模型與連線」執行 CLI 安裝。")
        arguments = ["--skip-trust", "--output-format", "json"]
        if context.model:
            arguments.extend(["--model", context.model])
        unsafe_full = os.environ.get("AI_HUB_UNSAFE_FULL_CLI") == "1"
        if context.permission_mode == "full" and unsafe_full:
            arguments.append("--yolo")
        elif context.permission_mode in {"workspace", "full"}:
            arguments.extend(["--approval-mode", "auto_edit"])
        else:
            arguments.extend(["--approval-mode", "plan"])
        emit("啟動 Gemini", "等待 Gemini CLI 回傳結構化結果", 4, "info")
        code, lines = _run_process(
            _process_command(executable, arguments),
            context.project_path,
            _runtime_environment(self.paths),
            emit,
            cancel,
            stdin_text=_prompt_with_history(context),
        )
        if cancel.is_set():
            raise ProviderError("工作已由使用者停止。")
        raw = "\n".join(lines).strip()
        if code != 0:
            raise ProviderError(f"Gemini CLI 結束碼 {code}\n{raw[-5000:]}")
        try:
            payload = json.loads(raw)
            response = payload.get("response") or payload.get("text") or raw
            stats = payload.get("stats") or {}
        except json.JSONDecodeError:
            response, stats = raw, {}
        emit("Gemini 完成", "已解析回覆與使用統計", 96, "info")
        return ProviderResult(text=str(response), metadata={"stats": stats})


class OllamaProvider(BaseProvider):
    kind = "local"

    def __init__(self, model: str, base_url: str = "http://127.0.0.1:11434"):
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.id = f"ollama:{model}"
        self.label = model

    def run(self, context: ProviderContext, emit: Emit, cancel: threading.Event) -> ProviderResult:
        messages = []
        for item in context.history[-16:]:
            if item.get("role") in {"user", "assistant"}:
                messages.append({"role": item["role"], "content": item.get("content", "")})
        messages.append({"role": "user", "content": context.prompt})
        body = json.dumps({"model": self.model, "messages": messages, "stream": True}).encode("utf-8")
        request = urllib.request.Request(
            f"{self.base_url}/api/chat", body, {"Content-Type": "application/json"}, method="POST"
        )
        fragments: list[str] = []
        emit("啟動本機模型", f"載入 {self.model}", 3, "info")
        try:
            with urllib.request.urlopen(request, timeout=1800) as response:
                for raw_line in response:
                    if cancel.is_set():
                        raise ProviderError("工作已由使用者停止。")
                    try:
                        event = json.loads(raw_line.decode("utf-8"))
                    except json.JSONDecodeError:
                        continue
                    fragment = (event.get("message") or {}).get("content") or event.get("response") or ""
                    if fragment:
                        fragments.append(fragment)
                        if len(fragments) % 12 == 0:
                            emit("本機推論中", "".join(fragments[-12:]), None, "message-delta")
                    if event.get("done"):
                        emit("本機模型完成", f"輸出 {event.get('eval_count', 0)} tokens", 96, "info")
                        metadata = {
                            "eval_count": event.get("eval_count"),
                            "eval_duration": event.get("eval_duration"),
                            "total_duration": event.get("total_duration"),
                        }
                        return ProviderResult(text="".join(fragments).strip(), metadata=metadata)
        except urllib.error.URLError as error:
            raise ProviderError(f"Ollama 連線失敗：{error}") from error
        return ProviderResult(text="".join(fragments).strip())


class OpenAICompatibleProvider(BaseProvider):
    kind = "api"

    def __init__(
        self,
        provider_id: str,
        label: str,
        base_url: str,
        model: str,
        api_key_env: str,
    ):
        self.id = provider_id
        self.label = label
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.api_key_env = api_key_env

    def run(self, context: ProviderContext, emit: Emit, cancel: threading.Event) -> ProviderResult:
        model = context.model or self.model
        if not model:
            raise ProviderError(f"尚未設定 {self.label} 的模型名稱。")
        key = os.environ.get(self.api_key_env, "")
        if not key and "127.0.0.1" not in self.base_url and "localhost" not in self.base_url:
            raise ProviderError(f"環境變數 {self.api_key_env} 尚未設定。")
        messages = []
        for item in context.history[-20:]:
            if item.get("role") in {"user", "assistant", "system"}:
                messages.append({"role": item["role"], "content": item.get("content", "")})
        messages.append({"role": "user", "content": context.prompt})
        payload = {"model": model, "messages": messages, "stream": False}
        headers = {"Content-Type": "application/json"}
        if key:
            headers["Authorization"] = f"Bearer {key}"
        request = urllib.request.Request(
            f"{self.base_url}/chat/completions",
            json.dumps(payload).encode("utf-8"),
            headers,
            method="POST",
        )
        emit("連接模型 API", f"{self.label} · {model}", 8, "info")
        try:
            with urllib.request.urlopen(request, timeout=1800) as response:
                if cancel.is_set():
                    raise ProviderError("工作已由使用者停止。")
                result = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as error:
            detail = error.read().decode("utf-8", errors="replace")
            raise ProviderError(f"{self.label} API {error.code}：{detail[-4000:]}") from error
        except (urllib.error.URLError, json.JSONDecodeError) as error:
            raise ProviderError(f"{self.label} API 連線或回應錯誤：{error}") from error
        choices = result.get("choices") or []
        text = ((choices[0].get("message") or {}).get("content") if choices else None) or result.get("response") or ""
        emit("API 回覆完成", "已收到完整結果", 96, "info")
        return ProviderResult(text=str(text), metadata={"usage": result.get("usage") or {}})


class ShellProvider(BaseProvider):
    id = "terminal"
    label = "PowerShell"
    kind = "system"

    def __init__(self, paths: AppPaths):
        self.paths = paths

    def run(self, context: ProviderContext, emit: Emit, cancel: threading.Event) -> ProviderResult:
        emit("啟動終端機", context.prompt[:300], 5, "tool")
        code, lines = _run_process(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", context.prompt],
            context.project_path,
            _runtime_environment(self.paths),
            emit,
            cancel,
        )
        text = "\n".join(lines)
        if cancel.is_set():
            raise ProviderError("命令已由使用者停止。")
        if code != 0:
            raise ProviderError(f"PowerShell 結束碼 {code}\n{text[-5000:]}")
        return ProviderResult(text=text or "命令執行完成（無輸出）。", metadata={"exit_code": code})


class ModelPullProvider(BaseProvider):
    id = "model-manager"
    label = "模型下載器"
    kind = "system"

    def __init__(self, paths: AppPaths):
        self.paths = paths

    def run(self, context: ProviderContext, emit: Emit, cancel: threading.Event) -> ProviderResult:
        executable = _find_command("ollama", self.paths)
        if not executable:
            found = shutil.which("ollama")
            executable = Path(found) if found else None
        if not executable:
            raise ProviderError("找不到 Ollama。")
        model = context.prompt.strip()
        emit("下載模型", model, 2, "info")
        progress = 2.0

        def parse(line: str) -> None:
            nonlocal progress
            progress = min(94, progress + 0.35)
            emit("下載模型", line, progress, "output")

        code, lines = _run_process(
            _process_command(executable, ["pull", model]),
            context.project_path,
            _runtime_environment(self.paths),
            emit,
            cancel,
            parse_line=parse,
        )
        if cancel.is_set():
            raise ProviderError("模型下載已停止。")
        if code != 0:
            raise ProviderError(f"Ollama pull 結束碼 {code}\n" + "\n".join(lines[-20:]))
        return ProviderResult(text=f"模型 {model} 已下載並完成完整性驗證。")


class HuggingFacePullProvider(BaseProvider):
    id = "hf-model-manager"
    label = "Hugging Face 官方權重下載器"
    kind = "system"

    def __init__(self, paths: AppPaths):
        self.paths = paths

    def run(self, context: ProviderContext, emit: Emit, cancel: threading.Event) -> ProviderResult:
        try:
            payload = json.loads(context.prompt)
        except json.JSONDecodeError as error:
            raise ProviderError("Hugging Face 下載工作格式無效。") from error
        repository = str(payload.get("repository") or "").strip()
        target = Path(str(payload.get("target") or "")).resolve()
        if not repository or repository.count("/") != 1:
            raise ProviderError("Hugging Face repository ID 無效。")
        try:
            target.relative_to(self.paths.downloads.resolve())
        except ValueError as error:
            raise ProviderError("模型權重只能下載到 AI Hub 的受控下載資料夾。") from error
        executable = _find_command("hf", self.paths)
        legacy = False
        if not executable:
            executable = _find_command("huggingface-cli", self.paths)
            legacy = True
        if not executable:
            raise ProviderError("找不到 Hugging Face `hf` CLI；請先安裝 huggingface_hub。")
        target.mkdir(parents=True, exist_ok=True)
        arguments = (["download"] if legacy else ["download"]) + [repository, "--local-dir", str(target)]
        emit("下載官方模型權重", repository, 2, "info")
        progress = 2.0

        def parse(line: str) -> None:
            nonlocal progress
            progress = min(96, progress + 0.18)
            if line.strip():
                emit("Hugging Face 下載中", line[-1500:], progress, "output")

        code, lines = _run_process(
            _process_command(executable, arguments),
            context.project_path,
            _runtime_environment(self.paths),
            emit,
            cancel,
            parse_line=parse,
        )
        if cancel.is_set():
            raise ProviderError("模型權重下載已停止。")
        if code != 0:
            raise ProviderError(f"Hugging Face CLI 結束碼 {code}\n" + "\n".join(lines[-30:]))
        marker = target / ".aihub-download-complete.json"
        marker.write_text(
            json.dumps({"repository": repository, "completed_at": time.time()}, ensure_ascii=False),
            encoding="utf-8",
        )
        return ProviderResult(
            text=f"官方模型權重已下載到 {target}",
            metadata={"repository": repository, "path": str(target)},
        )


class URLDownloadProvider(BaseProvider):
    id = "download-manager"
    label = "檔案下載器"
    kind = "system"

    def run(self, context: ProviderContext, emit: Emit, cancel: threading.Event) -> ProviderResult:
        try:
            payload = json.loads(context.prompt)
        except json.JSONDecodeError as error:
            raise ProviderError("下載工作格式無效。") from error
        url = str(payload.get("url") or "").strip()
        target = Path(str(payload.get("target") or "")).resolve()
        parsed = urllib.parse.urlparse(url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise ProviderError("下載只支援有效的 HTTP/HTTPS 網址。")
        if context.permission_mode != "full":
            try:
                target.relative_to(context.project_path.resolve())
            except ValueError as error:
                raise ProviderError("專案權限模式只能下載到目前專案內。") from error
        if target.exists() and not payload.get("overwrite"):
            raise ProviderError(f"目標檔案已存在：{target}")
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_name(f".{target.name}.aihub-{os.getpid()}-{threading.get_ident()}.part")
        request = urllib.request.Request(
            url,
            headers={"User-Agent": "AIHubLocalDownloader/1.0", "Accept": "*/*"},
        )
        downloaded = 0
        digest = hashlib.sha256()
        started = time.monotonic()
        emit("建立下載連線", parsed.hostname, 2, "info")
        try:
            with urllib.request.urlopen(request, timeout=60) as response, temporary.open("wb") as handle:
                total = int(response.headers.get("Content-Length") or 0)
                while True:
                    if cancel.is_set():
                        raise ProviderError("下載已由使用者停止。")
                    chunk = response.read(1024 * 1024)
                    if not chunk:
                        break
                    handle.write(chunk)
                    digest.update(chunk)
                    downloaded += len(chunk)
                    elapsed = max(0.1, time.monotonic() - started)
                    if total:
                        progress = min(96, 3 + downloaded / total * 92)
                        detail = f"{downloaded / 1024**2:.1f}/{total / 1024**2:.1f} MB · {downloaded / elapsed / 1024**2:.1f} MB/s"
                    else:
                        progress = min(90, 3 + elapsed / 8)
                        detail = f"{downloaded / 1024**2:.1f} MB · {downloaded / elapsed / 1024**2:.1f} MB/s"
                    emit("下載中", detail, progress, "output")
            os.replace(temporary, target)
        except urllib.error.HTTPError as error:
            detail = error.read().decode("utf-8", errors="replace")
            raise ProviderError(f"下載失敗 HTTP {error.code}：{detail[-2000:]}") from error
        except urllib.error.URLError as error:
            raise ProviderError(f"下載連線失敗：{error}") from error
        finally:
            if temporary.exists():
                try:
                    temporary.unlink()
                except OSError:
                    pass
        return ProviderResult(
            text=f"已下載 {downloaded / 1024**2:.2f} MB 到 {target}",
            metadata={"path": str(target), "bytes": downloaded, "sha256": digest.hexdigest()},
        )


class FileTransferProvider(BaseProvider):
    id = "file-transfer"
    label = "資料匯入匯出"
    kind = "system"

    def run(self, context: ProviderContext, emit: Emit, cancel: threading.Event) -> ProviderResult:
        try:
            payload = json.loads(context.prompt)
        except json.JSONDecodeError as error:
            raise ProviderError("資料傳輸工作格式無效。") from error
        source = Path(str(payload.get("source") or "")).resolve()
        target = Path(str(payload.get("target") or "")).resolve()
        if not source.is_file():
            raise ProviderError(f"來源檔案不存在：{source}")
        if context.permission_mode != "full":
            root = context.project_path.resolve()
            try:
                source.relative_to(root)
                target.relative_to(root)
            except ValueError as error:
                raise ProviderError("跨專案、外接裝置或網路路徑傳輸需要完整權限。") from error
        if target.exists() and not payload.get("overwrite"):
            raise ProviderError(f"目標檔案已存在：{target}")
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_name(f".{target.name}.aihub-{os.getpid()}-{threading.get_ident()}.part")
        total = source.stat().st_size
        copied = 0
        digest = hashlib.sha256()
        emit("準備資料傳輸", f"{source} → {target}", 2, "info")
        try:
            with source.open("rb") as reader, temporary.open("wb") as writer:
                while True:
                    if cancel.is_set():
                        raise ProviderError("資料傳輸已由使用者停止。")
                    chunk = reader.read(1024 * 1024)
                    if not chunk:
                        break
                    writer.write(chunk)
                    digest.update(chunk)
                    copied += len(chunk)
                    progress = 96 if not total else min(96, 3 + copied / total * 92)
                    emit("資料傳輸中", f"{copied / 1024**2:.1f}/{total / 1024**2:.1f} MB", progress, "output")
            os.replace(temporary, target)
        finally:
            if temporary.exists():
                try:
                    temporary.unlink()
                except OSError:
                    pass
        return ProviderResult(
            text=f"資料傳輸完成：{target}",
            metadata={"source": str(source), "path": str(target), "bytes": copied, "sha256": digest.hexdigest()},
        )


class TrainingProvider(BaseProvider):
    id = "training-manager"
    label = "QLoRA 訓練器"
    kind = "system"

    def __init__(self, paths: AppPaths):
        self.paths = paths

    def run(self, context: ProviderContext, emit: Emit, cancel: threading.Event) -> ProviderResult:
        try:
            payload = json.loads(context.prompt)
        except json.JSONDecodeError as error:
            raise ProviderError("訓練工作格式無效。") from error
        dataset = Path(str(payload.get("dataset") or "")).resolve()
        output = Path(str(payload.get("output") or "")).resolve()
        model = str(payload.get("model") or "").strip()
        if not dataset.is_file() or not model:
            raise ProviderError("訓練模型或 JSONL 資料集不存在。")
        if context.permission_mode != "full":
            try:
                dataset.relative_to(context.project_path.resolve())
                output.relative_to(context.project_path.resolve())
            except ValueError as error:
                raise ProviderError("專案權限模式只能使用目前專案內的資料集與輸出資料夾。") from error
        script = self.paths.root / "training" / "train_lora.py"
        python = os.environ.get("AI_HUB_TRAINING_PYTHON") or shutil.which("python")
        if not script.is_file() or not python:
            raise ProviderError("找不到訓練腳本或 Python；可用 AI_HUB_TRAINING_PYTHON 指定 CUDA 環境。")
        arguments = [
            str(script), "--model", model, "--dataset", str(dataset), "--output", str(output),
            "--epochs", str(payload.get("epochs", 1.0)), "--lora-rank", str(payload.get("lora_rank", 16)),
            "--max-seq-length", str(payload.get("max_seq_length", 2048)),
        ]
        if payload.get("revision"):
            arguments.extend(["--revision", str(payload["revision"])])
        emit("啟動 QLoRA", f"{model} · {dataset.name}", 2, "info")
        progress = 3.0

        def parse(line: str) -> None:
            nonlocal progress
            progress = min(96, progress + 0.4)
            if line.strip():
                emit("QLoRA 訓練中", line[-1500:], progress, "output")

        code, lines = _run_process(
            [python, *arguments],
            context.project_path,
            _runtime_environment(self.paths),
            emit,
            cancel,
            parse_line=parse,
        )
        if cancel.is_set():
            raise ProviderError("訓練已由使用者停止。")
        raw = "\n".join(lines).strip()
        if code != 0:
            raise ProviderError(f"QLoRA 結束碼 {code}\n{raw[-5000:]}")
        return ProviderResult(text=raw or f"QLoRA adapter 已輸出到 {output}", metadata={"output": str(output), "model": model})


class ProviderRegistry:
    def __init__(self, paths: AppPaths, settings: Settings):
        self.paths = paths
        self.settings = settings
        self._status_cache: tuple[float, list[dict[str, Any]]] | None = None

    def _ollama_models(self) -> list[str]:
        try:
            with urllib.request.urlopen("http://127.0.0.1:11434/api/tags", timeout=1.2) as response:
                data = json.loads(response.read().decode("utf-8"))
            return [item.get("name") for item in data.get("models", []) if item.get("name")]
        except (OSError, urllib.error.URLError, json.JSONDecodeError):
            return []

    def providers(self, include_hidden: bool = False) -> dict[str, BaseProvider]:
        config = self.settings.get("provider_config", {})
        compatible = config.get("compatible", {})
        providers: dict[str, BaseProvider] = {
            "codex": CodexProvider(self.paths),
            "gemini": GeminiProvider(self.paths),
            "compatible": OpenAICompatibleProvider(
                "compatible",
                "OpenAI-compatible",
                compatible.get("base_url", "http://127.0.0.1:8000/v1"),
                compatible.get("model", ""),
                compatible.get("api_key_env", "AI_HUB_API_KEY"),
            ),
        }
        for model in self._ollama_models():
            provider = OllamaProvider(model)
            providers[provider.id] = provider
        if include_hidden:
            providers["terminal"] = ShellProvider(self.paths)
            providers["model-manager"] = ModelPullProvider(self.paths)
            providers["hf-model-manager"] = HuggingFacePullProvider(self.paths)
            providers["download-manager"] = URLDownloadProvider()
            providers["file-transfer"] = FileTransferProvider()
            providers["training-manager"] = TrainingProvider(self.paths)
        return providers

    def get(self, provider_id: str) -> BaseProvider:
        provider = self.providers(include_hidden=True).get(provider_id)
        if not provider:
            raise ProviderError(f"未知模型或執行器：{provider_id}")
        return provider

    def status(self, force: bool = False) -> list[dict[str, Any]]:
        now = time.monotonic()
        if not force and self._status_cache and now - self._status_cache[0] < 3:
            return self._status_cache[1]
        config = self.settings.get("provider_config", {})
        codex_command = _find_command("codex", self.paths)
        gemini_command = _find_command("gemini", self.paths)
        items: list[dict[str, Any]] = [
            {
                "id": "codex",
                "label": "Codex",
                "kind": "cli",
                "installed": bool(codex_command),
                "authenticated": _codex_authenticated(),
                "available": bool(codex_command and _codex_authenticated()),
                "detail": (
                    f"已登入 · {codex_command}"
                    if codex_command and _codex_authenticated()
                    else (f"CLI 已安裝，尚未登入 · {codex_command}" if codex_command else "尚未安裝 CLI")
                ),
            },
            {
                "id": "gemini",
                "label": "Gemini CLI",
                "kind": "cli",
                "installed": bool(gemini_command),
                "authenticated": _gemini_authenticated(),
                "available": bool(gemini_command and _gemini_authenticated()),
                "detail": (
                    f"已設定驗證 · {gemini_command}"
                    if gemini_command and _gemini_authenticated()
                    else (f"CLI 已安裝，尚未登入 · {gemini_command}" if gemini_command else "尚未安裝 CLI")
                ),
            },
        ]
        compatible = config.get("compatible", {})
        items.append(
            {
                "id": "compatible",
                "label": "OpenAI-compatible",
                "kind": "api",
                "available": bool(compatible.get("base_url") and compatible.get("model")),
                "detail": f"{compatible.get('model') or '未設定模型'} · {compatible.get('base_url')}",
            }
        )
        models = self._ollama_models()
        for model in models:
            items.append(
                {
                    "id": f"ollama:{model}",
                    "label": model,
                    "kind": "local",
                    "available": True,
                    "detail": "Ollama 本機模型",
                }
            )
        if not models:
            items.append(
                {
                    "id": "ollama:empty",
                    "label": "Ollama",
                    "kind": "local",
                    "available": False,
                    "detail": "服務已安裝，但尚無模型",
                }
            )
        self._status_cache = (now, items)
        return items

    def status_map(self) -> dict[str, dict[str, Any]]:
        return {item["id"]: item for item in self.status()}

    def invalidate(self) -> None:
        self._status_cache = None


def _prompt_with_history(context: ProviderContext) -> str:
    if not context.history:
        return context.prompt
    lines: list[str] = []
    total = 0
    for item in reversed(context.history[-20:]):
        content = str(item.get("content") or "")
        if not content:
            continue
        fragment = f"{item.get('role', 'message')}: {content}"
        if total + len(fragment) > 14_000:
            break
        lines.append(fragment)
        total += len(fragment)
    lines.reverse()
    return (
        "以下是 AI Hub 保存在本機的同一對話近期內容，用來延續上下文：\n"
        + "\n\n".join(lines)
        + "\n\n目前使用者要求：\n"
        + context.prompt
    )
