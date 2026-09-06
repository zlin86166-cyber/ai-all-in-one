from __future__ import annotations

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
