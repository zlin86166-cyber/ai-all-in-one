from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="QLoRA trainer for an eligible <=50B model")
    parser.add_argument("--model", required=True)
    parser.add_argument("--dataset", required=True, type=Path)
    parser.add_argument("--output", default=Path("training/output"), type=Path)
    parser.add_argument("--max-seq-length", default=2048, type=int)
    parser.add_argument("--epochs", default=1.0, type=float)
    parser.add_argument("--learning-rate", default=2e-4, type=float)
    parser.add_argument("--lora-rank", default=16, type=int)
    return parser.parse_args()


def load_dependencies():
    try:
        import torch
        from datasets import load_dataset
        from peft import LoraConfig, prepare_model_for_kbit_training
        from transformers import (
            AutoModelForCausalLM,
            AutoTokenizer,
            BitsAndBytesConfig,
            DataCollatorForLanguageModeling,
            Trainer,
            TrainingArguments,
        )
    except ImportError as error:
        raise SystemExit(
            "缺少訓練套件。請在 WSL2/Linux CUDA 環境安裝 torch transformers datasets peft accelerate bitsandbytes。"
        ) from error
    return {
        "torch": torch,
        "load_dataset": load_dataset,
        "LoraConfig": LoraConfig,
        "prepare_model_for_kbit_training": prepare_model_for_kbit_training,
        "AutoModelForCausalLM": AutoModelForCausalLM,
        "AutoTokenizer": AutoTokenizer,
        "BitsAndBytesConfig": BitsAndBytesConfig,
        "DataCollatorForLanguageModeling": DataCollatorForLanguageModeling,
        "Trainer": Trainer,
        "TrainingArguments": TrainingArguments,
    }


def main() -> int:
    args = arguments()
    if not args.dataset.is_file():
        raise SystemExit(f"找不到資料集：{args.dataset}")
    dependencies = load_dependencies()
    torch = dependencies["torch"]
    if not torch.cuda.is_available():
        raise SystemExit("真正 QLoRA 訓練需要 NVIDIA CUDA；目前沒有可用 CUDA GPU，因此拒絕假裝完成訓練。")
    available_vram = sum(
        torch.cuda.get_device_properties(index).total_memory
        for index in range(torch.cuda.device_count())
    ) / 1024**3
    model_name = args.model.lower()
    if "48b" in model_name or "49b" in model_name:
        required_vram = 80
    elif "32b" in model_name or "33b" in model_name:
        required_vram = 48
    elif "14b" in model_name:
        required_vram = 24
    else:
        required_vram = 16
    if available_vram < required_vram:
        raise SystemExit(
            f"偵測到 {available_vram:.1f} GB CUDA VRAM；{args.model} 的保守 QLoRA 前檢需要至少 "
            f"{required_vram} GB。拒絕在明知會 OOM 的硬體上假裝啟動訓練。"
        )

    quantization = dependencies["BitsAndBytesConfig"](
        load_in_4bit=True,
        bnb_4bit_quant_type="nf4",
        bnb_4bit_compute_dtype=torch.bfloat16,
        bnb_4bit_use_double_quant=True,
    )
    tokenizer = dependencies["AutoTokenizer"].from_pretrained(args.model, trust_remote_code=True)
    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token
    model = dependencies["AutoModelForCausalLM"].from_pretrained(
        args.model,
        device_map="auto",
        trust_remote_code=True,
        quantization_config=quantization,
    )
    model = dependencies["prepare_model_for_kbit_training"](model)
    lora = dependencies["LoraConfig"](
        r=args.lora_rank,
        lora_alpha=args.lora_rank * 2,
        lora_dropout=0.05,
        bias="none",
        task_type="CAUSAL_LM",
        target_modules="all-linear",
    )
    model.add_adapter(lora)
    dataset = dependencies["load_dataset"]("json", data_files=str(args.dataset), split="train")

    def tokenize(example):
        messages = example.get("messages")
        if not isinstance(messages, list):
            raise ValueError("每筆 JSONL 必須有 messages 陣列。")
        text = tokenizer.apply_chat_template(messages, tokenize=False, add_generation_prompt=False)
        return tokenizer(text, truncation=True, max_length=args.max_seq_length)

    tokenized = dataset.map(tokenize, remove_columns=dataset.column_names)
    args.output.mkdir(parents=True, exist_ok=True)
    training_args = dependencies["TrainingArguments"](
        output_dir=str(args.output),
        num_train_epochs=args.epochs,
        learning_rate=args.learning_rate,
        per_device_train_batch_size=1,
        gradient_accumulation_steps=16,
        gradient_checkpointing=True,
        bf16=True,
        logging_steps=5,
        save_strategy="epoch",
        report_to="none",
    )
    trainer = dependencies["Trainer"](
        model=model,
        args=training_args,
        train_dataset=tokenized,
        data_collator=dependencies["DataCollatorForLanguageModeling"](tokenizer, mlm=False),
    )
    trainer.train()
    trainer.save_model(str(args.output))
    tokenizer.save_pretrained(str(args.output))
    metadata = {
        "base_model": args.model,
        "dataset": str(args.dataset.resolve()),
        "examples": len(dataset),
        "epochs": args.epochs,
        "lora_rank": args.lora_rank,
        "vram_gb": round(available_vram, 1),
    }
    (args.output / "ai-hub-training.json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(metadata, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
