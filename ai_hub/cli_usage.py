"""Read account quota snapshots through the installed Codex CLI app-server."""

from __future__ import annotations

import json
import os
import queue
import subprocess
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from .config import APP_VERSION, AppPaths
from .providers import _find_command, _process_command, _runtime_environment


class CliUsageError(RuntimeError):
    """A CLI-native quota query failed or returned no account limits."""


def _await_response(
    messages: queue.Queue[dict[str, Any] | None],
    response_id: str,
    timeout: float,
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise CliUsageError("Codex CLI 用量查詢逾時。")
        try:
            message = messages.get(timeout=remaining)
        except queue.Empty as error:
            raise CliUsageError("Codex CLI 用量查詢逾時。") from error
        if message is None:
            raise CliUsageError("Codex CLI 在回傳用量前已結束。")
        if message.get("id") != response_id:
            continue
        rpc_error = message.get("error")
        if isinstance(rpc_error, dict):
            code = rpc_error.get("code")
            suffix = f"（錯誤碼 {code}）" if code is not None else ""
            raise CliUsageError(f"Codex CLI 無法讀取帳號用量{suffix}。")
        result = message.get("result")
        if not isinstance(result, dict):
            raise CliUsageError("Codex CLI 回傳的用量資料格式不完整。")
        return result


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def _window_label(duration_minutes: float | None, role: str) -> str:
    if duration_minutes == 300:
        return "5H"
    if duration_minutes == 10080:
        return "7D"
    if duration_minutes and duration_minutes > 0:
        hours = duration_minutes / 60
        return f"{hours:g}H" if hours >= 1 else f"{duration_minutes:g}M"
    return role.upper()


def _normalise_rate_limits(payload: dict[str, Any]) -> dict[str, Any]:
    buckets = payload.get("rateLimitsByLimitId")
    bucket = buckets.get("codex") if isinstance(buckets, dict) else None
    if not isinstance(bucket, dict):
        bucket = payload.get("rateLimits")
    if not isinstance(bucket, dict):
        raise CliUsageError("Codex CLI 尚未回報可用的帳號剩餘用量。")

    windows: list[dict[str, Any]] = []
    for role in ("primary", "secondary"):
        item = bucket.get(role)
        if not isinstance(item, dict):
            continue
        used = _number(item.get("usedPercent"))
        if used is None:
            continue
        duration = _number(item.get("windowDurationMins"))
        reset = _number(item.get("resetsAt"))
        windows.append(
            {
                "key": role,
                "label": _window_label(duration, role),
                "remaining_percent": round(max(0.0, min(100.0, 100.0 - used)), 1),
                "resets_at": reset,
            }
        )
    if not windows:
        raise CliUsageError("Codex CLI 尚未回報可用的帳號剩餘用量。")
    return {
        "windows": windows,
        "checked_at": datetime.now().astimezone().isoformat(timespec="seconds"),
    }


def query_codex_usage(paths: AppPaths, cwd: Path, timeout: float = 18.0) -> dict[str, Any]:
    """Ask Codex's local app-server for the same rate-limit snapshot its CLI uses.

    This uses the user's already-installed CLI and login; it does not read or
    export the CLI credential files and does not call a separate billing API.
    """
    executable = _find_command("codex", paths)
    if executable is None:
        raise CliUsageError("找不到 Codex CLI。")

    command = _process_command(executable, ["app-server", "--stdio"])
    create_flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0
    try:
        process = subprocess.Popen(
            command,
            cwd=str(cwd),
            env=_runtime_environment(paths),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
            creationflags=create_flags,
        )
    except OSError as error:
        raise CliUsageError("無法啟動 Codex CLI 用量查詢。") from error

    messages: queue.Queue[dict[str, Any] | None] = queue.Queue()

    def read_messages() -> None:
        assert process.stdout is not None
        try:
            for line in process.stdout:
                try:
                    message = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(message, dict):
                    messages.put(message)
        finally:
            messages.put(None)

    reader = threading.Thread(target=read_messages, daemon=True, name="codex-usage-reader")
    reader.start()
    try:
        assert process.stdin is not None
        initialize = {
            "method": "initialize",
            "id": "aihub-initialize",
            "params": {
                "clientInfo": {
                    "name": "ai_hub_usage_panel",
                    "title": "AI Hub Usage Panel",
                    "version": APP_VERSION,
                }
            },
        }
        process.stdin.write(json.dumps(initialize, ensure_ascii=False) + "\n")
        process.stdin.flush()
        _await_response(messages, "aihub-initialize", min(timeout, 8.0))

        process.stdin.write(json.dumps({"method": "initialized", "params": {}}) + "\n")
        request_id = "aihub-rate-limits"
        process.stdin.write(
            json.dumps({"method": "account/rateLimits/read", "id": request_id, "params": {}})
            + "\n"
        )
        process.stdin.flush()
        result = _await_response(messages, request_id, timeout)
        return _normalise_rate_limits(result)
    except (BrokenPipeError, OSError) as error:
        raise CliUsageError("Codex CLI 用量查詢連線中斷。") from error
    finally:
        if process.stdin and not process.stdin.closed:
            try:
                process.stdin.close()
            except OSError:
                pass
        try:
            process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            if os.name == "nt":
                try:
                    subprocess.run(
                        ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                        check=False,
                        timeout=5,
                        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                    )
                except (OSError, subprocess.TimeoutExpired):
                    process.kill()
            else:
                process.terminate()
            try:
                process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                process.kill()
