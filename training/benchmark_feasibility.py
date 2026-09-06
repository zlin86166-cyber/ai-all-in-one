from __future__ import annotations

import argparse
import csv
import json
import math
from pathlib import Path
from typing import Any


def brier(rows: list[dict[str, Any]], key: str) -> float:
    return sum((float(row[key]) - float(row["outcome"])) ** 2 for row in rows) / max(1, len(rows))


def ece(rows: list[dict[str, Any]], key: str, bins: int = 10) -> float:
    total = len(rows)
    error = 0.0
    for index in range(bins):
        low, high = index / bins, (index + 1) / bins
        bucket = [row for row in rows if low <= float(row[key]) < high or (index == bins - 1 and float(row[key]) == 1.0)]
        if not bucket:
            continue
        confidence = sum(float(row[key]) for row in bucket) / len(bucket)
        accuracy = sum(float(row["outcome"]) for row in bucket) / len(bucket)
        error += abs(confidence - accuracy) * len(bucket) / total
    return error


def log_loss(rows: list[dict[str, Any]], key: str) -> float:
    eps = 1e-9
    total = 0.0
    for row in rows:
        p = min(1 - eps, max(eps, float(row[key])))
        y = float(row["outcome"])
        total += -(y * math.log(p) + (1 - y) * math.log(1 - p))
    return total / max(1, len(rows))


def load_csv(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        required = {"outcome", "ai_hub", "baseline"}
        if not required.issubset(set(reader.fieldnames or [])):
            raise ValueError("CSV 必須包含 outcome, ai_hub, baseline 三欄，機率使用 0~1。")
        for raw in reader:
            row = {key: float(raw[key]) for key in required}
            if row["outcome"] not in {0.0, 1.0}:
                raise ValueError("outcome 只能是 0 或 1。")
            if not all(0 <= row[key] <= 1 for key in ("ai_hub", "baseline")):
                raise ValueError("ai_hub/baseline 機率必須在 0~1。")
            rows.append(row)
    if len(rows) < 20:
        raise ValueError("至少需要 20 筆同題測試資料；建議 100 筆以上。")
    return rows


def main() -> int:
    parser = argparse.ArgumentParser(description="Head-to-head feasibility benchmark")
    parser.add_argument("csv")
    parser.add_argument("--output", default="data/feasibility-benchmark.json")
    args = parser.parse_args()
    rows = load_csv(Path(args.csv).resolve())
    metrics = {}
    for key in ("ai_hub", "baseline"):
        metrics[key] = {
            "brier": round(brier(rows, key), 6),
            "ece": round(ece(rows, key), 6),
            "log_loss": round(log_loss(rows, key), 6),
        }
    metrics["ai_hub_better"] = bool(
        metrics["ai_hub"]["brier"] < metrics["baseline"]["brier"]
        and metrics["ai_hub"]["ece"] <= metrics["baseline"]["ece"]
    )
    payload = {"samples": len(rows), "metrics": metrics}
    output = Path(args.output)
    if not output.is_absolute():
        output = Path(__file__).resolve().parents[1] / output
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if metrics["ai_hub_better"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
