from __future__ import annotations

import json
import shutil
import subprocess
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from .config import MODEL_CATALOG, AppPaths
from .hardware import HardwareMonitor
from .tasks import TaskManager


class ModelManager:
    def __init__(self, paths: AppPaths, hardware: HardwareMonitor, tasks: TaskManager):
        self.paths = paths
        self.hardware = hardware
        self.tasks = tasks

    def installed(self) -> list[dict[str, Any]]:
        try:
            with urllib.request.urlopen("http://127.0.0.1:11434/api/tags", timeout=1.5) as response:
                payload = json.loads(response.read().decode("utf-8"))
            return [
                {
                    "name": item.get("name"),
                    "model": item.get("model"),
                    "size_gb": round((item.get("size") or 0) / 1024**3, 2),
                    "modified_at": item.get("modified_at"),
                    "details": item.get("details") or {},
                }
                for item in payload.get("models", [])
            ]
        except (OSError, urllib.error.URLError, json.JSONDecodeError):
            return []

    def catalog(self) -> list[dict[str, Any]]:
        snapshot = self.hardware.snapshot()
        ram = float(snapshot.get("memory", {}).get("total_gb") or 0)
        disk = float(snapshot.get("disk", {}).get("free_gb") or 0)
        installed_names = {item["name"] for item in self.installed()}
        result: list[dict[str, Any]] = []
        for source in MODEL_CATALOG:
            item = dict(source)
            install_name = item.get("install")
            ollama_installed = bool(
                install_name
                and any(name == install_name or name.startswith(f"{install_name}:") for name in installed_names)
            )
            hf_repository = item.get("hf_repo")
            hf_target = self.paths.downloads / "models" / str(hf_repository or "").replace("/", "--")
            hf_installed = bool(
                hf_repository
                and (hf_target / ".aihub-download-complete.json").is_file()
                and (hf_target / "config.json").is_file()
                and any(hf_target.rglob("*.safetensors"))
            )
            item["installed"] = ollama_installed or hf_installed
            if hf_repository:
                item["download_path"] = str(hf_target)
            if ollama_installed:
                state, reason = "ready", "已安裝，可直接選用"
            elif hf_installed:
                state, reason = "downloaded", "官方權重已下載；請用 vLLM/SGLang 啟動後接到相容端點"
            elif hf_repository:
                if disk < float(item.get("disk_gb") or 0) + 10:
                    state, reason = "blocked", f"官方權重約需 {item.get('disk_gb')} GB，另需 10 GB 安全空間"
                else:
                    state, reason = "available", f"可下載官方權重；本機推論建議至少 {item.get('ram_gb')} GB RAM"
            elif item.get("runtime") in {"openai-compatible", "comfyui"} and not install_name:
                state, reason = "remote", "請連接符合需求的本機伺服器或遠端 GPU 節點"
            elif ram < float(item.get("ram_gb") or 0):
                state, reason = "remote", f"需要約 {item.get('ram_gb')} GB RAM；本機只有 {ram:.1f} GB"
            elif disk < float(item.get("disk_gb") or 0) + 10:
                state, reason = "blocked", f"磁碟需保留至少 {item.get('disk_gb')} GB 加 10 GB 安全空間"
            else:
                state, reason = "available", "硬體基本條件可下載"
            item["compatibility"] = {"state": state, "reason": reason}
            result.append(item)
        return result

    def pull(
        self,
        model_id: str,
        project: dict[str, Any],
        conversation_id: str | None = None,
    ) -> dict[str, Any]:
        item = next((entry for entry in self.catalog() if entry["id"] == model_id), None)
        if not item:
            raise ValueError("模型不在經過驗證的目錄中。")
        install_name = item.get("install")
        hf_repository = item.get("hf_repo")
        if item.get("installed"):
            raise ValueError("模型已下載或安裝。")
        if item["compatibility"]["state"] in {"remote", "blocked"}:
            raise ValueError(item["compatibility"]["reason"])
        if hf_repository:
            target = self.paths.downloads / "models" / str(hf_repository).replace("/", "--")
            task = self.tasks.launch(
                provider_id="hf-model-manager",
                title=f"下載 {item['label']}",
                prompt=json.dumps({"repository": hf_repository, "target": str(target)}, ensure_ascii=False),
                project=project,
                conversation_id=conversation_id,
                permission_mode="workspace",
                predicted_seconds=max(600, int(float(item.get("disk_gb") or 1) * 160)),
                web_access=True,
                metadata={"model_id": model_id, "download": True, "repository": hf_repository},
                publish_message=bool(conversation_id),
            )
            return task
        if not install_name:
            raise ValueError(item["compatibility"]["reason"])
        task = self.tasks.launch(
            provider_id="model-manager",
            title=f"下載 {item['label']}",
            prompt=install_name,
            project=project,
            conversation_id=conversation_id,
            permission_mode="workspace",
            predicted_seconds=max(120, int(float(item.get("disk_gb") or 1) * 100)),
            web_access=True,
            metadata={"model_id": model_id, "download": True},
            publish_message=bool(conversation_id),
        )
        return task

    @staticmethod
    def _training_requirements(parameters_b: float) -> dict[str, float]:
        if parameters_b <= 8:
            return {"vram_gb": 16, "ram_gb": 32, "disk_gb": 35}
        if parameters_b <= 14:
            return {"vram_gb": 24, "ram_gb": 48, "disk_gb": 55}
        if parameters_b <= 32:
            return {"vram_gb": 48, "ram_gb": 64, "disk_gb": 90}
        return {"vram_gb": 80, "ram_gb": 96, "disk_gb": 140}

    @staticmethod
    def _cuda_probe() -> dict[str, Any]:
        executable = shutil.which("nvidia-smi")
        if not executable:
            return {"available": False, "name": "未偵測到 NVIDIA CUDA GPU", "vram_gb": 0.0}
        try:
            result = subprocess.run(
                [
                    executable,
                    "--query-gpu=name,memory.total",
                    "--format=csv,noheader,nounits",
                ],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=8,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            first = next((line.strip() for line in result.stdout.splitlines() if line.strip()), "")
            name, memory = [part.strip() for part in first.rsplit(",", 1)]
            return {
                "available": result.returncode == 0,
                "name": name,
                "vram_gb": round(float(memory) / 1024, 1),
            }
        except (OSError, subprocess.SubprocessError, ValueError):
            return {"available": False, "name": "CUDA 探測失敗", "vram_gb": 0.0}

    @staticmethod
    def _validate_dataset(dataset: Path) -> dict[str, Any]:
        if not dataset.is_file():
            return {"valid": False, "examples": 0, "error": "找不到 JSONL 資料集"}
        examples = 0
        try:
            with dataset.open("r", encoding="utf-8") as handle:
                for line_number, line in enumerate(handle, 1):
                    if not line.strip():
                        continue
                    if examples >= 100_000:
                        return {"valid": False, "examples": examples, "error": "資料集超過 100,000 筆安全上限"}
                    item = json.loads(line)
                    messages = item.get("messages") if isinstance(item, dict) else None
                    if not isinstance(messages, list) or not messages:
                        return {
                            "valid": False,
                            "examples": examples,
                            "error": f"第 {line_number} 行缺少 messages 陣列",
                        }
                    if any(
                        not isinstance(message, dict)
                        or message.get("role") not in {"system", "user", "assistant"}
                        or not isinstance(message.get("content"), str)
                        for message in messages
                    ):
                        return {
                            "valid": False,
                            "examples": examples,
                            "error": f"第 {line_number} 行的 role/content 格式無效",
                        }
                    examples += 1
        except (OSError, UnicodeError, json.JSONDecodeError) as error:
            return {"valid": False, "examples": examples, "error": str(error)}
        if examples < 8:
            return {"valid": False, "examples": examples, "error": "至少需要 8 筆可驗證訓練樣本"}
        return {"valid": True, "examples": examples, "error": None}

    def training_preflight(self, model_id: str, dataset_path: str) -> dict[str, Any]:
        item = next((entry for entry in MODEL_CATALOG if entry["id"] == model_id), None)
        if not item or not item.get("training_model"):
            raise ValueError("此項目不是可進行 QLoRA 的文字模型。")
        parameters = float(item.get("parameters_b") or 0)
        if parameters <= 0 or parameters > 50:
            raise ValueError("訓練模型必須是 50B 以下的文字模型。")
        dataset = self._validate_dataset(Path(dataset_path).expanduser().resolve())
        requirements = self._training_requirements(parameters)
        hardware = self.hardware.snapshot()
        cuda = self._cuda_probe()
        ram = float(hardware.get("memory", {}).get("total_gb") or 0)
        disk = float(hardware.get("disk", {}).get("free_gb") or 0)
        blockers: list[str] = []
        if not dataset["valid"]:
            blockers.append(str(dataset["error"]))
        if not cuda["available"]:
            blockers.append("未偵測到可用 NVIDIA CUDA GPU")
        elif float(cuda["vram_gb"]) < requirements["vram_gb"]:
            blockers.append(f"VRAM 需要至少 {requirements['vram_gb']:.0f} GB，目前 {cuda['vram_gb']:.1f} GB")
        if ram < requirements["ram_gb"]:
            blockers.append(f"RAM 需要至少 {requirements['ram_gb']:.0f} GB，目前 {ram:.1f} GB")
        if disk < requirements["disk_gb"]:
            blockers.append(f"可用磁碟需要至少 {requirements['disk_gb']:.0f} GB，目前 {disk:.1f} GB")
        return {
            "ready": not blockers,
            "model_id": model_id,
            "training_model": item["training_model"],
            "parameters_b": parameters,
            "dataset": dataset,
            "cuda": cuda,
            "requirements": requirements,
            "detected": {"ram_gb": ram, "disk_gb": disk},
            "blockers": blockers,
        }

    def train(
        self,
        model_id: str,
        dataset_path: str,
        output_path: str,
        project: dict[str, Any],
        conversation_id: str | None,
        permission_mode: str,
        epochs: float = 1.0,
        lora_rank: int = 16,
    ) -> dict[str, Any]:
        preflight = self.training_preflight(model_id, dataset_path)
        if not preflight["ready"]:
            raise ValueError("QLoRA 前檢未通過：" + "；".join(preflight["blockers"]))
        output = Path(output_path).expanduser().resolve()
        payload = {
            "model": preflight["training_model"],
            "dataset": str(Path(dataset_path).expanduser().resolve()),
            "output": str(output),
            "epochs": max(0.1, min(float(epochs), 20.0)),
            "lora_rank": max(4, min(int(lora_rank), 256)),
            "max_seq_length": 2048,
            "revision": preflight.get("revision"),
        }
        predicted = max(1800, int(preflight["parameters_b"] * 900 * payload["epochs"]))
        return self.tasks.launch(
            provider_id="training-manager",
            title=f"QLoRA · {preflight['training_model']}",
            prompt=json.dumps(payload, ensure_ascii=False),
            project=project,
            conversation_id=conversation_id,
            permission_mode=permission_mode,
            predicted_seconds=predicted,
            web_access=True,
            metadata={"training": True, "preflight": preflight},
            publish_message=bool(conversation_id),
        )

    def readiness(self) -> dict[str, Any]:
        snapshot = self.hardware.snapshot()
        ram = float(snapshot.get("memory", {}).get("total_gb") or 0)
        cuda = self._cuda_probe()
        vram = float(cuda.get("vram_gb") or 0)
        free_disk = float(snapshot.get("disk", {}).get("free_gb") or 0)
        return {
            "inference": {
                "deepseek_7b": ram >= 8 and free_disk >= 8,
                "deepseek_latest_8b": ram >= 20 and free_disk >= 28,
                "deepseek_32b": ram >= 48 and free_disk >= 80,
                "kimi_48b": ram >= 96 and free_disk >= 115,
            },
            "lora_training": {
                "ready": bool(cuda.get("available") and vram >= 16 and ram >= 32 and free_disk >= 35),
                "requires": "8B 至少 16 GB VRAM；32B 建議 48 GB；48B 建議 80 GB，並需 CUDA 訓練環境",
                "detected": f"CUDA {cuda.get('name')} · {vram:.1f} GB VRAM / {ram:.1f} GB RAM / {free_disk:.1f} GB 可用磁碟",
            },
            "note": "模型下載不等於訓練；介面會把 LoRA/QLoRA 與執行期校準分開標示。",
        }
