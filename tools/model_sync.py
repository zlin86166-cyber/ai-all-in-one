from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ORG_FAMILIES = {"Kimi": "moonshotai", "DeepSeek": "deepseek-ai"}
TEXT_TAGS = {"text-generation", "conversational", "text2text-generation"}
SIZE_PATTERN = re.compile(r"(?<![\d.])(\d+(?:\.\d+)?)\s*[Bb](?![A-Za-z])")


def request_json(url: str) -> Any:
    req = urllib.request.Request(url, headers={"User-Agent": "AIHubModelSync/1.0", "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as response:
        return json.loads(response.read().decode("utf-8"))


def parameters_b(model: dict[str, Any]) -> float | None:
    safetensors = model.get("safetensors") or {}
    total = safetensors.get("total")
    if isinstance(total, (int, float)) and total > 0:
        return round(float(total) / 1_000_000_000, 2)
    model_id = str(model.get("id") or "")
    values = [float(value) for value in SIZE_PATTERN.findall(model_id)]
    return max(values) if values else None


def is_text_model(model: dict[str, Any]) -> bool:
    pipeline = str(model.get("pipeline_tag") or "").lower()
    tags = {str(tag).lower() for tag in model.get("tags") or []}
    return pipeline in TEXT_TAGS or bool(tags & TEXT_TAGS)


def eligible_models(family: str, org: str, limit_b: float) -> list[dict[str, Any]]:
    query = urllib.parse.urlencode({"author": org, "sort": "lastModified", "direction": "-1", "limit": 100, "full": "true"})
    payload = request_json(f"https://huggingface.co/api/models?{query}")
    rows: list[dict[str, Any]] = []
    for item in payload if isinstance(payload, list) else []:
        size = parameters_b(item)
        if not size or size > limit_b or not is_text_model(item):
            continue
        model_id = str(item.get("id") or "")
        lowered = model_id.lower()
        if any(marker in lowered for marker in ("base", "eagle3", "dflash", "dspark", "ocr", "vision", "audio")):
            continue
        rows.append({
            "family": family,
            "id": model_id,
            "parameters_b": size,
            "last_modified": item.get("lastModified"),
            "revision": item.get("sha"),
            "downloads": item.get("downloads"),
            "likes": item.get("likes"),
            "pipeline_tag": item.get("pipeline_tag"),
            "source": f"https://huggingface.co/{model_id}",
        })
    rows.sort(key=lambda row: str(row.get("last_modified") or ""), reverse=True)
    return rows


def select_models(limit_b: float) -> dict[str, Any]:
    result: dict[str, Any] = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "parameter_limit_b": limit_b,
        "families": {},
    }
    for family, org in ORG_FAMILIES.items():
        rows = eligible_models(family, org, limit_b)
        result["families"][family] = {
            "organization": org,
            "latest_eligible": rows[0] if rows else None,
            "largest_eligible": max(rows, key=lambda row: float(row["parameters_b"]), default=None),
            "eligible": rows[:30],
        }
    return result


def find_hf() -> str | None:
    return shutil.which("hf") or shutil.which("huggingface-cli")


def download_model(model_id: str, target_root: Path) -> Path:
    executable = find_hf()
    if not executable:
        raise RuntimeError("找不到 Hugging Face CLI。請執行 setup.ps1 安裝 huggingface_hub。")
    target = target_root / model_id.replace("/", "--")
    target.mkdir(parents=True, exist_ok=True)
    command = [executable, "download", model_id, "--local-dir", str(target)]
    print("RUN:", subprocess.list2cmdline(command), flush=True)
    completed = subprocess.run(command, check=False)
    if completed.returncode:
        raise RuntimeError(f"Hugging Face 下載失敗，結束碼 {completed.returncode}")
    (target / ".aihub-download-complete.json").write_text(
        json.dumps({"repository": model_id, "completed_at": datetime.now(timezone.utc).isoformat()}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return target


def train_model(model_id: str, dataset: Path, output: Path, epochs: float, rank: int) -> None:
    root = Path(__file__).resolve().parents[1]
    script = root / "training" / "train_lora.py"
    command = [sys.executable, str(script), "--model", model_id, "--dataset", str(dataset), "--output", str(output), "--epochs", str(epochs), "--lora-rank", str(rank), "--max-seq-length", "2048"]
    print("RUN:", subprocess.list2cmdline(command), flush=True)
    completed = subprocess.run(command, check=False)
    if completed.returncode:
        raise RuntimeError(f"QLoRA 訓練失敗，結束碼 {completed.returncode}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Sync official Kimi/DeepSeek models under a parameter limit")
    parser.add_argument("--limit-b", type=float, default=50.0)
    parser.add_argument("--output", default="data/latest-models.json")
    parser.add_argument("--download", choices=["Kimi", "DeepSeek"])
    parser.add_argument("--prefer-largest", action="store_true")
    parser.add_argument("--dataset")
    parser.add_argument("--train-output")
    parser.add_argument("--epochs", type=float, default=1.0)
    parser.add_argument("--lora-rank", type=int, default=16)
    parser.add_argument("--approve-download", action="store_true")
    parser.add_argument("--approve-training", action="store_true")
    args = parser.parse_args()

    root = Path(__file__).resolve().parents[1]
    output = (root / args.output).resolve() if not Path(args.output).is_absolute() else Path(args.output)
    payload = select_models(max(1.0, min(args.limit_b, 50.0)))
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False, indent=2))

    if args.download:
        if not args.approve_download:
            raise SystemExit("拒絕下載：請確認磁碟/網路成本後加入 --approve-download。")
        family = payload["families"][args.download]
        selected = family["largest_eligible" if args.prefer_largest else "latest_eligible"]
        if not selected:
            raise RuntimeError(f"沒有找到符合 ≤{args.limit_b}B 的 {args.download} 官方文字模型。")
        target = download_model(selected["id"], root / "data" / "downloads" / "models")
        print(f"DOWNLOADED: {target}")
        if args.dataset:
            if not args.approve_training:
                raise SystemExit("模型已下載，但拒絕訓練：QLoRA 必須另外加入 --approve-training。")
            train_output = Path(args.train_output or (root / "training" / "output" / selected["id"].replace("/", "--")))
            train_model(selected["id"], Path(args.dataset).resolve(), train_output.resolve(), args.epochs, args.lora_rank)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
