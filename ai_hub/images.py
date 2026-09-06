from __future__ import annotations

import json
import mimetypes
import random
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path
from typing import Any

from .config import AppPaths, Settings
from .db import Database, utcnow
from .tasks import TaskManager, future_iso


class ImageGenerationManager:
    """Submit and monitor standard ComfyUI API workflows without extra packages."""

    def __init__(
        self,
        paths: AppPaths,
        settings: Settings,
        database: Database,
        tasks: TaskManager,
    ):
        self.paths = paths
        self.settings = settings
        self.database = database
        self.tasks = tasks
        self.output_dir = paths.data / "generated"
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def _configuration(self) -> dict[str, Any]:
        config = self.settings.get("provider_config", {}).get("comfyui", {})
        return {
            "base_url": str(config.get("base_url") or "http://127.0.0.1:8188").rstrip("/"),
            "checkpoint": str(config.get("checkpoint") or ""),
        }

    @staticmethod
    def _request_json(
        url: str,
        payload: dict[str, Any] | None = None,
        timeout: float = 10,
    ) -> dict[str, Any]:
        body = json.dumps(payload).encode("utf-8") if payload is not None else None
        request = urllib.request.Request(
            url,
            body,
            {"Content-Type": "application/json"} if body is not None else {},
            method="POST" if body is not None else "GET",
        )
        with urllib.request.urlopen(request, timeout=timeout) as response:
            value = json.loads(response.read().decode("utf-8"))
        if not isinstance(value, dict):
            raise ValueError("ComfyUI 回傳格式不是 JSON 物件。")
        return value

    def status(self) -> dict[str, Any]:
        config = self._configuration()
        base_url = config["base_url"]
        parsed = urllib.parse.urlparse(base_url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            return {
                "available": False,
                "base_url": base_url,
                "checkpoints": [],
                "selected_checkpoint": config["checkpoint"],
                "detail": "ComfyUI URL 無效。",
            }
        try:
            self._request_json(f"{base_url}/system_stats", timeout=1.8)
            objects = self._request_json(
                f"{base_url}/object_info/CheckpointLoaderSimple", timeout=2.5
            )
            required = (
                objects.get("CheckpointLoaderSimple", {})
                .get("input", {})
                .get("required", {})
            )
            raw = required.get("ckpt_name") or []
            checkpoints = raw[0] if raw and isinstance(raw[0], list) else []
            checkpoints = [str(item) for item in checkpoints]
            selected = config["checkpoint"] if config["checkpoint"] in checkpoints else ""
            if not selected and checkpoints:
                selected = checkpoints[0]
            return {
                "available": True,
                "base_url": base_url,
                "checkpoints": checkpoints,
                "selected_checkpoint": selected,
                "detail": (
                    f"已連線，找到 {len(checkpoints)} 個 checkpoint"
                    if checkpoints
                    else "已連線，但尚未安裝 checkpoint"
                ),
            }
        except (OSError, urllib.error.URLError, urllib.error.HTTPError, ValueError, json.JSONDecodeError) as error:
            return {
                "available": False,
                "base_url": base_url,
                "checkpoints": [],
                "selected_checkpoint": config["checkpoint"],
                "detail": f"尚未連線：{error}",
            }

    @staticmethod
    def _dimension(value: Any, default: int) -> int:
        try:
            number = int(value)
        except (TypeError, ValueError):
            number = default
        number = max(256, min(number, 2048))
        return max(256, (number // 64) * 64)

    @staticmethod
    def _steps(value: Any) -> int:
        try:
            number = int(value)
        except (TypeError, ValueError):
            number = 24
        return max(1, min(number, 80))

    @staticmethod
    def _workflow(
        prompt: str,
        negative: str,
        checkpoint: str,
        width: int,
        height: int,
        steps: int,
        seed: int,
    ) -> dict[str, Any]:
        return {
            "3": {
                "class_type": "KSampler",
                "inputs": {
                    "seed": seed,
                    "steps": steps,
                    "cfg": 7.0,
                    "sampler_name": "euler",
                    "scheduler": "normal",
                    "denoise": 1.0,
                    "model": ["4", 0],
                    "positive": ["6", 0],
                    "negative": ["7", 0],
                    "latent_image": ["5", 0],
                },
            },
            "4": {
                "class_type": "CheckpointLoaderSimple",
                "inputs": {"ckpt_name": checkpoint},
            },
            "5": {
                "class_type": "EmptyLatentImage",
                "inputs": {"width": width, "height": height, "batch_size": 1},
            },
            "6": {
                "class_type": "CLIPTextEncode",
                "inputs": {"text": prompt, "clip": ["4", 1]},
            },
            "7": {
                "class_type": "CLIPTextEncode",
                "inputs": {"text": negative, "clip": ["4", 1]},
            },
            "8": {
                "class_type": "VAEDecode",
                "inputs": {"samples": ["3", 0], "vae": ["4", 2]},
            },
            "9": {
                "class_type": "SaveImage",
                "inputs": {"filename_prefix": "AIHub", "images": ["8", 0]},
            },
        }

    def launch(
        self,
        payload: dict[str, Any],
        project: dict[str, Any],
        conversation_id: str | None,
    ) -> dict[str, Any]:
        prompt = str(payload.get("prompt") or "").strip()
        if not prompt:
            raise ValueError("請輸入繪圖提示。")
        status = self.status()
        if not status["available"]:
            raise ValueError(status["detail"])
        checkpoint = str(payload.get("checkpoint") or status.get("selected_checkpoint") or "")
        if not checkpoint:
            raise ValueError("ComfyUI 尚未安裝可用的 checkpoint。")
        if checkpoint not in status["checkpoints"]:
            raise ValueError("選取的 checkpoint 不存在於目前 ComfyUI 節點。")
        width = self._dimension(payload.get("width"), 768)
        height = self._dimension(payload.get("height"), 768)
        steps = self._steps(payload.get("steps"))
        seed = int(payload.get("seed") or random.SystemRandom().randrange(1, 2**63 - 1))
        negative = str(payload.get("negative") or "low quality, blurry, distorted")[:4000]
        predicted_seconds = max(45, steps * 5)
        metadata = {
            "image": True,
            "prompt": prompt,
            "negative": negative,
            "checkpoint": checkpoint,
            "width": width,
            "height": height,
            "steps": steps,
            "seed": seed,
        }
        task = self.database.create_task(
            provider_id="comfyui-image",
            title="生成圖片",
            prompt=prompt,
            conversation_id=conversation_id,
            project_id=project.get("id"),
            predicted_seconds=predicted_seconds,
            predicted_end_at=future_iso(predicted_seconds),
            metadata=metadata,
        )
        cancel = threading.Event()
        thread = threading.Thread(
            target=self._worker,
            args=(task["id"], status["base_url"], metadata, conversation_id, cancel),
            name=f"image-{task['id']}",
            daemon=True,
        )
        self.tasks.register_parent(task["id"], cancel, thread)
        thread.start()
        return task

    @classmethod
    def _interrupt(cls, base_url: str, prompt_id: str) -> None:
        for endpoint, payload in (("/queue", {"delete": [prompt_id]}), ("/interrupt", {})):
            try:
                cls._request_json(base_url + endpoint, payload, timeout=3)
            except Exception:
                pass

    def _worker(
        self,
        task_id: str,
        base_url: str,
        metadata: dict[str, Any],
        conversation_id: str | None,
        cancel: threading.Event,
    ) -> None:
        started = time.monotonic()
        self.database.update_task(
            task_id,
            status="running",
            stage="送往 ComfyUI",
            progress=0,
            started_at=utcnow(),
        )
        self.database.add_task_event(task_id, "正在建立 ComfyUI 工作流。", progress=None)
        try:
            workflow = self._workflow(
                metadata["prompt"],
                metadata["negative"],
                metadata["checkpoint"],
                metadata["width"],
                metadata["height"],
                metadata["steps"],
                metadata["seed"],
            )
            queued = self._request_json(
                f"{base_url}/prompt",
                {"prompt": workflow, "client_id": f"ai-hub-{uuid.uuid4().hex}"},
                timeout=20,
            )
            prompt_id = str(queued.get("prompt_id") or "")
            if not prompt_id:
                raise ValueError(f"ComfyUI 未回傳 prompt_id：{queued}")
            self.database.update_task(task_id, stage="等待繪圖節點", progress=0)
            self.database.add_task_event(task_id, f"已排入 ComfyUI：{prompt_id}", progress=None)
            history: dict[str, Any] | None = None
            last_event = 0.0
            while not cancel.wait(1.5):
                elapsed = time.monotonic() - started
                if elapsed > 14_400:
                    raise TimeoutError("ComfyUI 繪圖超過 4 小時，已停止等待。")
                try:
                    response = self._request_json(
                        f"{base_url}/history/{urllib.parse.quote(prompt_id)}", timeout=5
                    )
                except (OSError, urllib.error.URLError, urllib.error.HTTPError):
                    continue
                if prompt_id in response:
                    history = response[prompt_id]
                    break
                self.database.update_task(task_id, stage="生成圖片中")
                if elapsed - last_event >= 12:
                    self.database.add_task_event(task_id, f"ComfyUI 仍在生成，已等待 {int(elapsed)} 秒；節點未提供可驗證百分比。", progress=None)
                    last_event = elapsed
            if cancel.is_set():
                self._interrupt(base_url, prompt_id)
                raise InterruptedError("繪圖工作已停止，並已要求 ComfyUI 中斷佇列工作。")
            if history is None:
                raise ValueError("ComfyUI 沒有回傳歷史結果。")
            status = history.get("status") or {}
            if status.get("status_str") == "error":
                raise ValueError(f"ComfyUI 工作失敗：{status}")
            image_records: list[dict[str, Any]] = []
            for output in (history.get("outputs") or {}).values():
                for item in output.get("images") or []:
                    filename = Path(str(item.get("filename") or "image.png")).name
                    query = urllib.parse.urlencode(
                        {
                            "filename": filename,
                            "subfolder": str(item.get("subfolder") or ""),
                            "type": str(item.get("type") or "output"),
                        }
                    )
                    with urllib.request.urlopen(f"{base_url}/view?{query}", timeout=90) as response:
                        content = response.read()
                        content_type = response.headers.get_content_type()
                    suffix = Path(filename).suffix or mimetypes.guess_extension(content_type) or ".png"
                    local_name = f"{task_id}-{len(image_records) + 1}{suffix.lower()}"
                    target = self.output_dir / local_name
                    target.write_bytes(content)
                    image_records.append(
                        {
                            "name": local_name,
                            "url": f"/api/images/file/{urllib.parse.quote(local_name)}",
                            "size": len(content),
                        }
                    )
            if not image_records:
                raise ValueError("ComfyUI 已完成，但工作流沒有輸出圖片。")
            completed_metadata = {
                **metadata,
                "prompt_id": prompt_id,
                "images": image_records,
                "duration_seconds": round(time.monotonic() - started, 1),
            }
            result = f"已完成 {len(image_records)} 張圖片，seed {metadata['seed']}。"
            self.database.update_task(
                task_id,
                status="completed",
                stage="圖片已保存",
                progress=100,
                result=result,
                metadata_json=completed_metadata,
                completed_at=utcnow(),
            )
            self.database.add_task_event(task_id, result, progress=100)
            if conversation_id:
                self.database.add_message(
                    conversation_id,
                    "assistant",
                    result,
                    provider_id="comfyui-image",
                    metadata={"task_id": task_id, **completed_metadata},
                )
            self.database.audit(
                "image.generated", task_id, {"count": len(image_records), "checkpoint": metadata["checkpoint"]}
            )
        except Exception as error:
            cancelled = isinstance(error, InterruptedError) or cancel.is_set()
            self.database.update_task(
                task_id,
                status="cancelled" if cancelled else "failed",
                stage="已停止" if cancelled else "繪圖失敗",
                error=str(error),
                completed_at=utcnow(),
            )
            self.database.add_task_event(
                task_id, str(error), level="warning" if cancelled else "error"
            )
            if conversation_id and not cancelled:
                self.database.add_message(
                    conversation_id,
                    "assistant",
                    f"繪圖失敗：{error}",
                    provider_id="comfyui-image",
                    metadata={"task_id": task_id, "error": True, "image": True},
                )
        finally:
            self.tasks.unregister_parent(task_id)

    def resolve_output(self, name: str) -> Path:
        decoded = urllib.parse.unquote(name)
        if not decoded or Path(decoded).name != decoded:
            raise PermissionError("圖片路徑無效。")
        target = (self.output_dir / decoded).resolve()
        try:
            target.relative_to(self.output_dir.resolve())
        except ValueError as error:
            raise PermissionError("禁止存取圖片路徑。") from error
        if not target.is_file():
            raise FileNotFoundError("找不到圖片。")
        return target
