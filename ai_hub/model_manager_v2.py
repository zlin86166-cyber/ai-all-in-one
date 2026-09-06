from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .models import ModelManager as BaseModelManager


class ModelManager(BaseModelManager):
    def _dynamic_entries(self) -> list[dict[str, Any]]:
        path = self.paths.data / "latest-models.json"
        if not path.is_file(): return []
        try: payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError): return []
        result = []
        for family, info in (payload.get("families") or {}).items():
            seen = set()
            for key in ("latest_eligible", "largest_eligible"):
                row = info.get(key) if isinstance(info, dict) else None
                if not isinstance(row, dict) or not row.get("id") or row["id"] in seen: continue
                seen.add(row["id"])
                p = float(row.get("parameters_b") or 0)
                if not (0 < p <= 50): continue
                ram = 20 if p <= 8 else (32 if p <= 16 else (64 if p <= 32 else 96))
                disk = max(8, round(p * 2.2))
                result.append({"id": row["id"], "family": family,
                    "label": f"{row['id'].split('/')[-1]} · {'最新' if key == 'latest_eligible' else '最大'} ≤50B",
                    "parameters_b": p, "runtime": "openai-compatible", "install": None,
                    "ram_gb": ram, "disk_gb": disk, "recommended": key == "latest_eligible",
                    "notes": "由官方 Hugging Face organization metadata 動態同步",
                    "source": row.get("source"), "hf_repo": row["id"], "training_model": row["id"],
                    "dynamic": True, "last_modified": row.get("last_modified")})
        return result

    def catalog(self) -> list[dict[str, Any]]:
        static = super().catalog()
        existing = {item["id"] for item in static}
        snapshot = self.hardware.snapshot(); disk = float(snapshot.get("disk", {}).get("free_gb") or 0)
        for item in self._dynamic_entries():
            if item["id"] in existing: continue
            target = self.paths.downloads / "models" / item["id"].replace("/", "--")
            installed = (target / ".aihub-download-complete.json").is_file() and (target / "config.json").is_file()
            item["installed"] = installed; item["download_path"] = str(target)
            if installed: state, reason = "downloaded", "官方權重已下載；可接 vLLM/SGLang 或進行 QLoRA"
            elif disk < float(item["disk_gb"]) + 10: state, reason = "blocked", "磁碟安全空間不足"
            else: state, reason = "available", "官方動態目錄項目可下載"
            item["compatibility"] = {"state": state, "reason": reason}; static.append(item)
        return static

    def _find_any(self, model_id: str) -> dict[str, Any] | None:
        return next((item for item in self.catalog() if item["id"] == model_id), None)

    def pull(self, model_id: str, project: dict[str, Any], conversation_id: str | None = None) -> dict[str, Any]:
        dynamic = next((item for item in self._dynamic_entries() if item["id"] == model_id), None)
        if not dynamic: return super().pull(model_id, project, conversation_id)
        item = self._find_any(model_id) or dynamic
        if item.get("installed"): raise ValueError("模型已下載。")
        if item.get("compatibility", {}).get("state") == "blocked": raise ValueError(item["compatibility"]["reason"])
        target = self.paths.downloads / "models" / model_id.replace("/", "--")
        return self.tasks.launch("hf-model-manager", f"下載 {item['label']}",
            json.dumps({"repository": model_id, "target": str(target)}, ensure_ascii=False), project,
            conversation_id, "workspace", max(600, int(float(item.get("disk_gb") or 1) * 160)),
            web_access=True, metadata={"model_id": model_id, "download": True, "repository": model_id},
            publish_message=bool(conversation_id))

    def training_preflight(self, model_id: str, dataset_path: str) -> dict[str, Any]:
        dynamic = next((item for item in self._dynamic_entries() if item["id"] == model_id), None)
        if not dynamic: return super().training_preflight(model_id, dataset_path)
        parameters = float(dynamic["parameters_b"]); dataset = self._validate_dataset(Path(dataset_path).expanduser().resolve())
        requirements = self._training_requirements(parameters); hardware = self.hardware.snapshot(); cuda = self._cuda_probe()
        ram = float(hardware.get("memory", {}).get("total_gb") or 0); disk = float(hardware.get("disk", {}).get("free_gb") or 0)
        blockers = []
        if not dataset["valid"]: blockers.append(str(dataset["error"]))
        if not cuda["available"]: blockers.append("未偵測到可用 NVIDIA CUDA GPU")
        elif float(cuda["vram_gb"]) < requirements["vram_gb"]: blockers.append(f"VRAM 需要至少 {requirements['vram_gb']:.0f} GB")
        if ram < requirements["ram_gb"]: blockers.append(f"RAM 需要至少 {requirements['ram_gb']:.0f} GB，目前 {ram:.1f} GB")
        if disk < requirements["disk_gb"]: blockers.append(f"可用磁碟需要至少 {requirements['disk_gb']:.0f} GB，目前 {disk:.1f} GB")
        return {"ready": not blockers, "model_id": model_id, "training_model": model_id, "parameters_b": parameters,
                "dataset": dataset, "cuda": cuda, "requirements": requirements, "detected": {"ram_gb": ram, "disk_gb": disk}, "blockers": blockers}

    def readiness(self) -> dict[str, Any]:
        value = super().readiness(); sync = self.paths.data / "latest-models.json"
        value["official_model_sync"] = {"available": sync.is_file(), "path": str(sync),
            "detail": "主模型目錄會直接合併同步結果" if sync.is_file() else "尚未同步官方模型 metadata"}
        return value
