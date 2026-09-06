from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def patch(path: str, old: str, new: str) -> None:
    target = ROOT / path
    text = target.read_text(encoding="utf-8")
    if new in text:
        return
    if old not in text:
        raise RuntimeError(f"finalizer anchor missing: {path}: {old[:100]!r}")
    target.write_text(text.replace(old, new, 1), encoding="utf-8")


# Cross-platform Windows-style parent path handling.
security = ROOT / "ai_hub" / "security.py"
text = security.read_text(encoding="utf-8")
text = text.replace(
    '        target = canonical_path(root / value) if value.startswith("..") else canonical_path(value)\n',
    '        normalized = value.replace("\\\\", "/")\n        target = canonical_path(root / normalized) if normalized.startswith("..") else canonical_path(value)\n',
)
security.write_text(text, encoding="utf-8")

# Normalize the schedule-return migration if the first-stage transformer is rerun.
application = ROOT / "ai_hub" / "application.py"
text = application.read_text(encoding="utf-8")
text = text.replace(
    "            timer.start()\n        return task\n            return task\n",
    "            timer.start()\n            return task\n",
)
text = re.sub(
    r"(\n        timer\.daemon = True\n        timer\.start\(\)\n)\s*$",
    r"\1        return task\n",
    text,
)
application.write_text(text, encoding="utf-8")

# Calibration learns only from explicit human/acceptance labels. A provider returning
# exit-code 0 is execution success, not proof that the requested outcome was correct.
patch(
    "ai_hub/evaluator.py",
    '''        examples = self.database.feasibility_examples()\n        signature = len(examples) + sum(3 if item["verified"] else 1 for item in examples)\n        if signature == self._calibration_cache[0]:\n            return self._calibration_cache[1]\n        if len(examples) < 20:\n            self._calibration_cache = (signature, None)\n            return None\n        keys = ["scope", "providers", "hardware", "permissions", "data", "testability", "reversibility", "history"]\n        training = [item for index, item in enumerate(examples) if index % 5 != 0]\n        validation = [item for index, item in enumerate(examples) if index % 5 == 0]\n''',
    '''        all_examples = self.database.feasibility_examples()\n        examples = [item for item in all_examples if item.get("verified")]\n        signature = len(all_examples) + len(examples) * 7\n        if signature == self._calibration_cache[0]:\n            return self._calibration_cache[1]\n        if len(examples) < 20:\n            self._calibration_cache = (signature, None)\n            return None\n        keys = ["scope", "providers", "hardware", "permissions", "data", "testability", "reversibility", "history"]\n        training = [item for index, item in enumerate(examples) if index % 5 != 0]\n        validation = [item for index, item in enumerate(examples) if index % 5 == 0]\n''',
)
patch(
    "ai_hub/evaluator.py",
    '''                sample_weight = 2.5 if item["verified"] else 0.65\n                prediction = self._sigmoid(bias + sum(weight * value for weight, value in zip(weights, features)))\n''',
    '''                sample_weight = 1.0\n                prediction = self._sigmoid(bias + sum(weight * value for weight, value in zip(weights, features)))\n''',
)

# Remove development-machine-specific runtime paths. Production discovery now uses
# the private runtime, explicit env override, or PATH only.
providers = ROOT / "ai_hub" / "providers.py"
text = providers.read_text(encoding="utf-8")
text = re.sub(
    r'''    bundled = Path\(\n        os\.environ\.get\(\n            "AI_HUB_BUNDLED_NODE",\n            r"C:\\\\Users\\\\ASUS\\\\\.cache\\\\codex-runtimes\\\\codex-primary-runtime\\\\dependencies\\\\node\\\\bin",\n        \)\n    \)\n    if bundled\.exists\(\):\n        path_entries\.append\(str\(bundled\)\)\n''',
    '''    bundled_override = os.environ.get("AI_HUB_BUNDLED_NODE")\n    if bundled_override:\n        bundled = Path(bundled_override)\n        if bundled.exists():\n            path_entries.append(str(bundled))\n''',
    text,
)
providers.write_text(text, encoding="utf-8")

build = ROOT / "build-desktop.ps1"
text = build.read_text(encoding="utf-8")
text = text.replace(
    "    'C:\\Users\\ASUS\\AppData\\Local\\Programs\\Python\\Python313\\python.exe',\n",
    "",
)
build.write_text(text, encoding="utf-8")

# Pin tested stable CLI versions. Operators may override deliberately through env
# variables, but unattended setup is reproducible rather than floating on @latest.
patch(
    "setup.ps1",
    '''    Write-Host 'Installing Codex CLI and Gemini CLI into the private project runtime...'\n    & $npmCommand --prefix $cliRoot install --no-audit --no-fund '@openai/codex@latest' '@google/gemini-cli@latest'\n''',
    '''    $codexVersion = if ($env:AI_HUB_CODEX_VERSION) { $env:AI_HUB_CODEX_VERSION } else { '0.153.4' }\n    $geminiVersion = if ($env:AI_HUB_GEMINI_VERSION) { $env:AI_HUB_GEMINI_VERSION } else { '0.58.0' }\n    Write-Host "Installing tested CLI versions: Codex $codexVersion / Gemini $geminiVersion"\n    & $npmCommand --prefix $cliRoot install --save-exact --no-audit --no-fund "@openai/codex@$codexVersion" "@google/gemini-cli@$geminiVersion"\n''',
)

# Preserve exact Hugging Face repository revision in model metadata so model
# downloads/training can be tied to the version that was evaluated.
patch(
    "tools/model_sync.py",
    '''            "last_modified": item.get("lastModified"),\n            "downloads": item.get("downloads"),\n''',
    '''            "last_modified": item.get("lastModified"),\n            "revision": item.get("sha"),\n            "downloads": item.get("downloads"),\n''',
)
patch(
    "ai_hub/model_manager_v2.py",
    '''                    "dynamic": True, "last_modified": row.get("last_modified")})\n''',
    '''                    "dynamic": True, "last_modified": row.get("last_modified"), "revision": row.get("revision")})\n''',
)
patch(
    "ai_hub/model_manager_v2.py",
    '''        return {"ready": not blockers, "model_id": model_id, "training_model": model_id, "parameters_b": parameters,\n                "dataset": dataset, "cuda": cuda, "requirements": requirements, "detected": {"ram_gb": ram, "disk_gb": disk}, "blockers": blockers}\n''',
    '''        return {"ready": not blockers, "model_id": model_id, "training_model": model_id, "parameters_b": parameters,\n                "revision": dynamic.get("revision"), "dataset": dataset, "cuda": cuda, "requirements": requirements,\n                "detected": {"ram_gb": ram, "disk_gb": disk}, "blockers": blockers}\n''',
)

# Reproducible and safer QLoRA: revision pinning, deterministic seed, opt-in remote
# code, and checkpoint resume. This does not fake training on unsupported hardware.
patch(
    "training/train_lora.py",
    '''    parser.add_argument("--lora-rank", default=16, type=int)\n    return parser.parse_args()\n''',
    '''    parser.add_argument("--lora-rank", default=16, type=int)\n    parser.add_argument("--revision")\n    parser.add_argument("--seed", default=42, type=int)\n    parser.add_argument("--resume-from-checkpoint", type=Path)\n    parser.add_argument("--trust-remote-code", action="store_true")\n    return parser.parse_args()\n''',
)
patch(
    "training/train_lora.py",
    '''    available_vram = sum(\n        torch.cuda.get_device_properties(index).total_memory\n''',
    '''    torch.manual_seed(args.seed)\n    torch.cuda.manual_seed_all(args.seed)\n    available_vram = sum(\n        torch.cuda.get_device_properties(index).total_memory\n''',
)
patch(
    "training/train_lora.py",
    '''    tokenizer = dependencies["AutoTokenizer"].from_pretrained(args.model, trust_remote_code=True)\n''',
    '''    tokenizer = dependencies["AutoTokenizer"].from_pretrained(\n        args.model, revision=args.revision, trust_remote_code=args.trust_remote_code\n    )\n''',
)
patch(
    "training/train_lora.py",
    '''        args.model,\n        device_map="auto",\n        trust_remote_code=True,\n        quantization_config=quantization,\n''',
    '''        args.model,\n        revision=args.revision,\n        device_map="auto",\n        trust_remote_code=args.trust_remote_code,\n        quantization_config=quantization,\n''',
)
patch(
    "training/train_lora.py",
    '''        report_to="none",\n    )\n''',
    '''        report_to="none",\n        seed=args.seed,\n        data_seed=args.seed,\n    )\n''',
)
patch(
    "training/train_lora.py",
    '''    trainer.train()\n    trainer.save_model(str(args.output))\n''',
    '''    resume = str(args.resume_from_checkpoint.resolve()) if args.resume_from_checkpoint else None\n    trainer.train(resume_from_checkpoint=resume)\n    trainer.save_state()\n    trainer.save_model(str(args.output))\n''',
)
patch(
    "training/train_lora.py",
    '''        "lora_rank": args.lora_rank,\n        "vram_gb": round(available_vram, 1),\n''',
    '''        "lora_rank": args.lora_rank,\n        "revision": args.revision,\n        "seed": args.seed,\n        "trust_remote_code": args.trust_remote_code,\n        "resumed_from": str(args.resume_from_checkpoint.resolve()) if args.resume_from_checkpoint else None,\n        "vram_gb": round(available_vram, 1),\n''',
)

# Pass the pinned revision through the model manager/provider when it exists.
models = ROOT / "ai_hub" / "models.py"
text = models.read_text(encoding="utf-8")
old = '''            "max_seq_length": 2048,\n        }\n'''
new = '''            "max_seq_length": 2048,\n            "revision": preflight.get("revision"),\n        }\n'''
if new not in text:
    if old not in text:
        raise RuntimeError("models.py training payload anchor missing")
    text = text.replace(old, new, 1)
models.write_text(text, encoding="utf-8")

providers = ROOT / "ai_hub" / "providers.py"
text = providers.read_text(encoding="utf-8")
old = '''            "--max-seq-length", str(payload.get("max_seq_length", 2048)),\n        ]\n'''
new = '''            "--max-seq-length", str(payload.get("max_seq_length", 2048)),\n        ]\n        if payload.get("revision"):\n            arguments.extend(["--revision", str(payload["revision"])])\n'''
if new not in text:
    if old not in text:
        raise RuntimeError("training provider argument anchor missing")
    text = text.replace(old, new, 1)
providers.write_text(text, encoding="utf-8")

# Add a regression check that unverified completion alone cannot train calibration.
tests = ROOT / "tests" / "test_hardening.py"
text = tests.read_text(encoding="utf-8")
marker = "    def test_scheduler_cross_midnight(self):\n"
addition = '''    def test_calibration_requires_verified_examples(self):\n        from ai_hub.evaluator import FeasibilityEvaluator\n        class FakeDB:\n            @staticmethod\n            def feasibility_examples():\n                return [{"verified": False, "success": True, "factors": {}} for _ in range(100)]\n        self.assertIsNone(FeasibilityEvaluator(FakeDB())._calibration())\n\n'''
if addition not in text:
    if marker not in text:
        raise RuntimeError("hardening test anchor missing")
    text = text.replace(marker, addition + marker, 1)
tests.write_text(text, encoding="utf-8")
