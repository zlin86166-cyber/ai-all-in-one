from __future__ import annotations

import math
import re
from dataclasses import dataclass, asdict
from typing import Any

from .db import Database


ACTION_WORDS = re.compile(
    r"(建立|新增|修改|刪除|下載|安裝|訓練|部署|發布|爬蟲|監控|匯入|匯出|"
    r"build|create|add|modify|delete|download|install|train|deploy|publish|crawl|monitor|import|export)",
    re.IGNORECASE,
)
EXTERNAL_WORDS = re.compile(
    r"(帳號|登入|oauth|sites|app store|play console|網路|藍芽|bluetooth|api|雲端|cloud)",
    re.IGNORECASE,
)
RISK_WORDS = re.compile(
    r"(大權限|完整權限|管理員|超頻|刪除|付款|購買|公開發布|醫療|金融|"
    r"administrator|full access|overclock|payment|production)",
    re.IGNORECASE,
)
TEST_WORDS = re.compile(
    r"(測試|驗證|完成條件|驗收|lint|test|benchmark|acceptance|verify)", re.IGNORECASE
)
DATA_WORDS = re.compile(
    r"(私有資料|即時資料|專有|爬蟲|全網|大數據|private data|real.?time|proprietary|crawl)",
    re.IGNORECASE,
)

BASELINE_WEIGHTS = {
    "scope": 0.18,
    "providers": 0.16,
    "hardware": 0.13,
    "permissions": 0.12,
    "data": 0.10,
    "testability": 0.12,
    "reversibility": 0.09,
    "history": 0.10,
}


@dataclass
class Factor:
    key: str
    label: str
    score: int
    evidence: str


class FeasibilityEvaluator:
    """Evidence-weighted preflight that calibrates ETA and reliability from completed runs."""

    def __init__(self, database: Database):
        self.database = database
        self._calibration_cache: tuple[int, dict[str, Any] | None] = (-1, None)

    @staticmethod
    def _sigmoid(value: float) -> float:
        value = max(-20.0, min(20.0, value))
        return 1.0 / (1.0 + math.exp(-value))

    def _calibration(self) -> dict[str, Any] | None:
        all_examples = self.database.feasibility_examples()
        examples = [item for item in all_examples if item.get("verified")]
        signature = len(all_examples) + len(examples) * 7
        if signature == self._calibration_cache[0]:
            return self._calibration_cache[1]
        if len(examples) < 20:
            self._calibration_cache = (signature, None)
            return None
        keys = ["scope", "providers", "hardware", "permissions", "data", "testability", "reversibility", "history"]
        training = [item for index, item in enumerate(examples) if index % 5 != 0]
        validation = [item for index, item in enumerate(examples) if index % 5 == 0]
        weights = [0.0] * len(keys)
        bias = 0.0
        rate = 0.12
        for _ in range(900):
            gradients = [0.0] * len(keys)
            bias_gradient = 0.0
            total_weight = 0.0
            for item in training:
                features = [(float(item["factors"].get(key, 50)) - 50.0) / 50.0 for key in keys]
                label = 1.0 if item["success"] else 0.0
                sample_weight = 1.0
                prediction = self._sigmoid(bias + sum(weight * value for weight, value in zip(weights, features)))
                error = (prediction - label) * sample_weight
                bias_gradient += error
                for index, value in enumerate(features):
                    gradients[index] += error * value
                total_weight += sample_weight
            divisor = max(1.0, total_weight)
            bias -= rate * bias_gradient / divisor
            weights = [
                weight - rate * (gradients[index] / divisor + 0.004 * weight)
                for index, weight in enumerate(weights)
            ]
        scored = validation or training
        brier = 0.0
        baseline_brier = 0.0
        calibration_error = 0.0
        for item in scored:
            features = [(float(item["factors"].get(key, 50)) - 50.0) / 50.0 for key in keys]
            prediction = self._sigmoid(bias + sum(weight * value for weight, value in zip(weights, features)))
            label = 1.0 if item["success"] else 0.0
            baseline_prediction = sum(
                float(item["factors"].get(key, 50)) * BASELINE_WEIGHTS[key] for key in keys
            ) / 100.0
            brier += (prediction - label) ** 2
            baseline_brier += (baseline_prediction - label) ** 2
            calibration_error += abs(prediction - label)
        learned_brier = round(brier / max(1, len(scored)), 4)
        raw_baseline_brier = round(baseline_brier / max(1, len(scored)), 4)
        result = {
            "keys": keys,
            "weights": weights,
            "bias": bias,
            "samples": len(examples),
            "verified_samples": sum(1 for item in examples if item["verified"]),
            "validation_samples": len(scored),
            "validation_brier": learned_brier,
            "baseline_brier": raw_baseline_brier,
            "mean_calibration_error": round(calibration_error / max(1, len(scored)), 4),
            "beats_baseline": bool(len(scored) >= 4 and learned_brier < raw_baseline_brier),
        }
        self._calibration_cache = (signature, result)
        return result

    def evaluate(
        self,
        prompt: str,
        provider_ids: list[str],
        provider_status: dict[str, dict[str, Any]],
        hardware: dict[str, Any],
        permission_mode: str,
        selected_files: list[str] | None = None,
    ) -> dict[str, Any]:
        selected_files = selected_files or []
        action_count = len(ACTION_WORDS.findall(prompt))
        prompt_length = len(prompt)
        scope = max(20, min(94, 94 - max(0, action_count - 3) * 4 - max(0, prompt_length - 800) // 90))
        available = sum(1 for item in provider_ids if provider_status.get(item, {}).get("available"))
        provider_score = 88 if available == len(provider_ids) and provider_ids else 36 + available * 14
        ram = float(hardware.get("memory", {}).get("total_gb") or 0)
        local_heavy = any(item.startswith("ollama:") and any(size in item for size in ("32b", "48b", "70b")) for item in provider_ids)
        hardware_score = 24 if local_heavy and ram < 32 else (78 if ram >= 16 else 55)
        external_count = len(EXTERNAL_WORDS.findall(prompt))
        permission_score = 90 if permission_mode == "full" else max(38, 88 - external_count * 8)
        data_score = max(30, 90 - len(DATA_WORDS.findall(prompt)) * 10)
        test_score = min(94, 60 + len(TEST_WORDS.findall(prompt)) * 9 + min(len(selected_files), 4) * 2)
        risk_score = max(28, 92 - len(RISK_WORDS.findall(prompt)) * 9)
        history_scores: list[float] = []
        history_samples = 0
        historical_seconds: list[float] = []
        for provider_id in provider_ids:
            metric = self.database.provider_metrics(provider_id)
            samples = int(metric.get("samples") or 0)
            history_samples += samples
            if samples:
                history_scores.append(float(metric.get("success_rate") or 0) * 100)
                if metric.get("average_seconds"):
                    historical_seconds.append(float(metric["average_seconds"]))
        history_score = sum(history_scores) / len(history_scores) if history_scores else 62
        factors = [
            Factor("scope", "範圍可控度", round(scope), f"辨識到 {action_count} 個主要動作"),
            Factor("providers", "模型可用性", round(provider_score), f"{available}/{len(provider_ids)} 個已就緒"),
            Factor("hardware", "硬體適配", round(hardware_score), f"可用記憶體基準 {ram:.1f} GB"),
            Factor("permissions", "權限與整合", round(permission_score), f"目前為 {permission_mode} 模式"),
            Factor("data", "資料可取得性", round(data_score), "依外部/私有資料依賴估算"),
            Factor("testability", "可驗證性", round(test_score), f"選取 {len(selected_files)} 個檔案"),
            Factor("reversibility", "變更可回復性", round(risk_score), "依系統、帳號與不可逆動作估算"),
            Factor("history", "實際歷史可靠度", round(history_score), f"來自 {history_samples} 次本機執行"),
        ]
        baseline_score = sum(item.score * BASELINE_WEIGHTS[item.key] for item in factors)
        calibration = self._calibration()
        collection_examples = [] if calibration else self.database.feasibility_examples()
        if calibration:
            score_map = {item.key: item.score for item in factors}
            features = [
                (float(score_map.get(key, 50)) - 50.0) / 50.0
                for key in calibration["keys"]
            ]
            learned = self._sigmoid(
                calibration["bias"]
                + sum(weight * value for weight, value in zip(calibration["weights"], features))
            ) * 100
            blend = min(0.72, 0.35 + calibration["verified_samples"] * 0.025)
            score = round(baseline_score * (1 - blend) + learned * blend)
        else:
            score = round(baseline_score)
        score = max(1, min(99, score))
        confidence = min(
            96,
            round(
                54
                + min(history_samples, 20) * 1.3
                + available * 4
                + (6 if selected_files else 0)
                + (min(calibration["verified_samples"], 12) if calibration else 0)
            ),
        )
        if score >= 76:
            verdict = "high"
            label = "成功機率高"
        elif score >= 52:
            verdict = "medium"
            label = "可行，但需分階段"
        else:
            verdict = "low"
            label = "目前條件不足"
        complexity = 35 + action_count * 28 + max(0, prompt_length - 250) * 0.16
        parallelism = max(1, min(len(provider_ids), 3))
        estimated = int(complexity / math.sqrt(parallelism))
        if historical_seconds:
            estimated = round(estimated * 0.45 + (sum(historical_seconds) / len(historical_seconds)) * 0.55)
        estimated = max(20, min(estimated, 8 * 3600))
        blockers = [item.evidence for item in sorted(factors, key=lambda item: item.score)[:3] if item.score < 65]
        return {
            "score": score,
            "confidence": confidence,
            "verdict": verdict,
            "label": label,
            "estimated_seconds": estimated,
            "factors": [asdict(item) for item in factors],
            "blockers": blockers,
            "method": "adaptive-evidence-v3",
            "history_samples": history_samples,
            "calibration": {
                "state": "trained" if calibration else "collecting",
                "required_samples": 20,
                "samples": calibration["samples"] if calibration else len(collection_examples),
                "verified_samples": calibration["verified_samples"] if calibration else sum(1 for item in collection_examples if item["verified"]),
                "validation_brier": calibration["validation_brier"] if calibration else None,
                "baseline_brier": calibration["baseline_brier"] if calibration else None,
                "validation_samples": calibration["validation_samples"] if calibration else 0,
                "quality": (
                    "measured-better"
                    if calibration and calibration["beats_baseline"]
                    else ("measured-not-better" if calibration else "not-yet-measured")
                ),
            },
        }
