from __future__ import annotations

import hashlib
import json
import re
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


DESTRUCTIVE_PATTERNS = [
    r"\bremove-item\b.*-recurse\b",
    r"\brm\s+(-[^\s]*r[^\s]*f|-[^\s]*f[^\s]*r)\b",
    r"\bdel\s+/(s|q)\b",
    r"\bformat(\.com)?\b",
    r"\bdiskpart\b",
    r"\bclean\s+all\b",
    r"\bgit\s+reset\s+--hard\b",
    r"\bgit\s+clean\s+-[^\s]*f",
    r"\breg\s+delete\b",
    r"\bbcdedit\b",
]

SYSTEM_PATTERNS = [
    r"\bpowercfg\b",
    r"\bset-service\b",
    r"\bsc(\.exe)?\s+(create|delete|config|stop)\b",
    r"\bschtasks\b",
    r"\bshutdown\b",
    r"\brestart-computer\b",
    r"\bwinget\s+(install|uninstall|upgrade)\b",
]

ACCOUNT_PATTERNS = [
    r"\b(deploy|publish|release)\b",
    r"\bsites?\b",
    r"\b(login|logout|oauth|sign[ -]?in)\b",
    r"\b(play console|app store|firebase|cloudflare|aws|azure|gcloud)\b",
    r"(部署|發布|上架|送審|公開網站|建立網站|建立\s*sites?|申請\s*apk|使用.*帳號|登入|登出|oauth|授權帳號)",
]

DOWNLOAD_PATTERNS = [
    r"\b(curl|wget|invoke-webrequest|invoke-restmethod|start-bitstransfer|bitsadmin)\b",
    r"\b(npm|pnpm|pip|uv|cargo)\s+(install|add)\b",
    r"\b(git\s+clone|ollama\s+pull)\b",
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


def action_fingerprint(kind: str, payload: dict[str, Any]) -> str:
    serialized = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(f"{kind}:{serialized}".encode("utf-8")).hexdigest()


def requires_account_approval(prompt: str) -> bool:
    return any(re.search(pattern, prompt, re.IGNORECASE) for pattern in ACCOUNT_PATTERNS)
