from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any


DEFAULT_SETTINGS: dict[str, Any] = {
    "language": "zh-TW",
    "permission_mode": "workspace",
    "full_access_enabled": False,
    "full_access_unlocked_until": None,
    "web_access": True,
    "crawler_enabled": True,
    "crawler_allowlist": [],
    "adaptive_performance": False,
    "performance_memory_threshold": 90,
    "max_parallel_agents": 3,
    "auto_peer_review": True,
    "provider_config": {
        "openai": {
            "base_url": "https://api.openai.com/v1",
            "model": "",
            "api_key_env": "OPENAI_API_KEY",
        },
        "compatible": {
            "base_url": "http://127.0.0.1:8000/v1",
            "model": "",
            "api_key_env": "AI_HUB_API_KEY",
        },
        "comfyui": {
            "base_url": "http://127.0.0.1:8188",
            "checkpoint": "",
        },
    },
}


MODEL_CATALOG: list[dict[str, Any]] = [
    {
        "id": "deepseek-r1:1.5b",
        "family": "DeepSeek",
        "label": "DeepSeek R1 Distill 1.5B",
        "parameters_b": 1.5,
        "runtime": "ollama",
        "install": "deepseek-r1:1.5b",
        "ram_gb": 4,
        "disk_gb": 2,
        "recommended": True,
        "notes": "本機快速路由、規劃與離線備援",
    },
    {
        "id": "deepseek-r1:7b",
        "family": "DeepSeek",
        "label": "DeepSeek R1 Distill 7B",
        "parameters_b": 7,
        "runtime": "ollama",
        "install": "deepseek-r1:7b",
        "ram_gb": 8,
        "disk_gb": 5,
        "recommended": True,
        "notes": "這台電腦可實際使用的高品質上限建議",
        "training_model": "deepseek-ai/DeepSeek-R1-Distill-Qwen-7B",
    },
    {
        "id": "deepseek-ai/DeepSeek-R1-0528-Qwen3-8B",
        "family": "DeepSeek",
        "label": "DeepSeek R1 0528 Qwen3 8B",
        "parameters_b": 8,
        "runtime": "transformers/vLLM",
        "install": None,
        "ram_gb": 20,
        "disk_gb": 18,
        "recommended": False,
        "notes": "目前官方 50B 以下較新的通用推理權重；本機 RAM 不足，建議遠端 GPU",
        "source": "https://huggingface.co/deepseek-ai/DeepSeek-R1-0528-Qwen3-8B",
        "hf_repo": "deepseek-ai/DeepSeek-R1-0528-Qwen3-8B",
        "training_model": "deepseek-ai/DeepSeek-R1-0528-Qwen3-8B",
    },
    {
        "id": "deepseek-ai/DeepSeek-R1-Distill-Qwen-32B",
        "family": "DeepSeek",
        "label": "DeepSeek R1 Distill Qwen 32B",
        "parameters_b": 32,
        "runtime": "openai-compatible",
        "install": "deepseek-r1:32b",
        "ram_gb": 48,
        "disk_gb": 70,
        "recommended": False,
        "notes": "50B 上限內的官方完整尺寸；建議遠端 GPU 節點",
        "source": "https://huggingface.co/deepseek-ai/DeepSeek-R1-Distill-Qwen-32B",
        "hf_repo": "deepseek-ai/DeepSeek-R1-Distill-Qwen-32B",
        "training_model": "deepseek-ai/DeepSeek-R1-Distill-Qwen-32B",
    },
    {
        "id": "moonshotai/Kimi-Linear-48B-A3B-Instruct",
        "family": "Kimi",
        "label": "Kimi Linear 48B A3B Instruct",
        "parameters_b": 48,
        "runtime": "openai-compatible",
        "install": None,
        "ram_gb": 96,
        "disk_gb": 105,
        "recommended": False,
        "notes": "最新 Kimi 系列超過 50B；這是官方最新的純文字 Instruct ≤50B 權重，需 GPU 伺服器",
        "source": "https://huggingface.co/moonshotai/Kimi-Linear-48B-A3B-Instruct",
        "hf_repo": "moonshotai/Kimi-Linear-48B-A3B-Instruct",
        "training_model": "moonshotai/Kimi-Linear-48B-A3B-Instruct",
    },
    {
        "id": "comfyui",
        "family": "Image",
        "label": "ComfyUI 繪圖節點",
        "parameters_b": None,
        "runtime": "comfyui",
        "install": None,
        "ram_gb": 16,
        "disk_gb": 20,
        "recommended": False,
        "notes": "可連接本機或遠端 FLUX / Stable Diffusion 工作流",
    },
]


@dataclass(frozen=True)
class AppPaths:
    root: Path
    data: Path
    web: Path
    runtime: Path
    downloads: Path
    database: Path
    settings: Path

    @classmethod
    def create(cls, root: Path) -> "AppPaths":
        root = root.resolve()
        data = root / "data"
        runtime = root / ".runtime"
        downloads = data / "downloads"
        for directory in (data, runtime, downloads):
            directory.mkdir(parents=True, exist_ok=True)
        return cls(
            root=root,
            data=data,
            web=root / "web",
            runtime=runtime,
            downloads=downloads,
            database=data / "ai-hub.sqlite3",
            settings=data / "settings.json",
        )


class Settings:
    def __init__(self, path: Path):
        self.path = path
        self._values = self._load()

    def _load(self) -> dict[str, Any]:
        loaded: dict[str, Any] = {}
        if self.path.exists():
            try:
                loaded = json.loads(self.path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                loaded = {}
        return _deep_merge(DEFAULT_SETTINGS, loaded)

    def get(self, key: str, default: Any = None) -> Any:
        return self._values.get(key, default)

    def all(self) -> dict[str, Any]:
        return json.loads(json.dumps(self._values))

    def update(self, values: dict[str, Any]) -> dict[str, Any]:
        self._values = _deep_merge(self._values, values)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(
            json.dumps(self._values, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        os.replace(temporary, self.path)
        return self.all()


def _deep_merge(base: dict[str, Any], overlay: dict[str, Any]) -> dict[str, Any]:
    result = json.loads(json.dumps(base))
    for key, value in overlay.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result
