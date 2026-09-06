from __future__ import annotations

import argparse
import json
import math
from pathlib import Path


KEYS = ["scope", "providers", "hardware", "permissions", "data", "testability", "reversibility", "history"]


def main() -> int:
    parser = argparse.ArgumentParser(description="Train AI Hub success calibrator from labelled run feedback")
    parser.add_argument("--dataset", required=True, type=Path)
    parser.add_argument("--output", default=Path("data/feasibility-calibration.json"), type=Path)
    args = parser.parse_args()
    rows = [json.loads(line) for line in args.dataset.read_text(encoding="utf-8").splitlines() if line.strip()]
    if len(rows) < 20:
        raise SystemExit("至少需要 20 筆包含 factors 與 success 的真實標註執行紀錄。")
    examples = []
    for row in rows:
        factors = row.get("factors") or {}
        examples.append(([float(factors.get(key, 50)) / 100 for key in KEYS], 1.0 if row.get("success") else 0.0))
    weights = [0.0] * len(KEYS)
    bias = 0.0
    rate = 0.08
    regularization = 0.002
    for _ in range(4000):
        gradients = [0.0] * len(weights)
        bias_gradient = 0.0
        for features, label in examples:
            raw = max(-20, min(20, bias + sum(weight * value for weight, value in zip(weights, features))))
            prediction = 1 / (1 + math.exp(-raw))
            error = prediction - label
            bias_gradient += error
            for index, value in enumerate(features):
                gradients[index] += error * value
        bias -= rate * bias_gradient / len(examples)
        weights = [
            weight - rate * (gradients[index] / len(examples) + regularization * weight)
            for index, weight in enumerate(weights)
        ]
    predictions = []
    for features, label in examples:
        prediction = 1 / (1 + math.exp(-(bias + sum(weight * value for weight, value in zip(weights, features)))))
        predictions.append((prediction, label))
    brier = sum((prediction - label) ** 2 for prediction, label in predictions) / len(predictions)
    output = {"version": 1, "samples": len(rows), "keys": KEYS, "bias": bias, "weights": weights, "brier_score": brier}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(output, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
