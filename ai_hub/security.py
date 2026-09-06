from __future__ import annotations

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
        normalized = value.replace("\\", "/")
        target = canonical_path(root / normalized) if normalized.startswith("..") else canonical_path(value)
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
