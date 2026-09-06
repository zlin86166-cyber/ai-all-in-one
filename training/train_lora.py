from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="QLoRA trainer for an eligible <=50B model")
    parser.add_argument("--model", required=True)
    parser.add_argument("--dataset", required=True, type=Path)
    parser.add_argument("--eval-dataset", type=Path)
    parser.add_argument("--output", default=Path("training/output"), type=Path)
    parser.add_argument("--max-seq-length", default=2048, type=int)
    parser.add_argument("--epochs", default=1.0, type=float)
    parser.add_argument("--learning-rate", default=2e-4, type=float)
    parser.add_argument("--lora-rank", default=16, type=int)
    parser.add_argument("--revision")
    parser.add_argument("--seed", default=42, type=int)
    parser.add_argument("--resume-from-checkpoint", type=Path)
    parser.add_argument("--trust-remote-code", action="store_true")
    parser.add_argument("--full-sequence-loss", action="store_true", help="Train on all tokens instead of masking prompt tokens")
    parser.add_argument("--early-stopping-patience", default=2, type=int)
    parser.add_argument("--smoke-prompt", default="請用一句話說明你能做什麼。")
    parser.add_argument("--merge-output", type=Path)
    return parser.parse_args()


def load_dependencies():
    try:
        import inspect
        import torch
        from datasets import load_dataset
        from peft import LoraConfig, prepare_model_for_kbit_training
        from transformers import (
            AutoModelForCausalLM,
            AutoTokenizer,
            BitsAndBytesConfig,
            DataCollatorForSeq2Seq,
            EarlyStoppingCallback,
            Trainer,
            TrainingArguments,
        )
    except ImportError as error:
        raise SystemExit("缺少訓練套件。請在 WSL2/Linux CUDA 環境安裝 torch transformers datasets peft accelerate bitsandbytes。") from error
    return locals()


def json_safe(value):
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, dict):
        return {str(k): json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_safe(v) for v in value]
    try:
        return float(value)
    except (TypeError, ValueError):
        return str(value)


def main() -> int:
    args = arguments()
    if not args.dataset.is_file():
        raise SystemExit(f"找不到資料集：{args.dataset}")
    if args.eval_dataset and not args.eval_dataset.is_file():
        raise SystemExit(f"找不到驗證資料集：{args.eval_dataset}")
    d = load_dependencies(); torch=d["torch"]; load_dataset=d["load_dataset"]
    if not torch.cuda.is_available():
        raise SystemExit("真正 QLoRA 訓練需要 NVIDIA CUDA；目前沒有可用 CUDA GPU，因此拒絕假裝完成訓練。")
    torch.manual_seed(args.seed); torch.cuda.manual_seed_all(args.seed)
    available_vram=sum(torch.cuda.get_device_properties(i).total_memory for i in range(torch.cuda.device_count()))/1024**3
    name=args.model.lower(); required_vram=80 if "48b" in name or "49b" in name else 48 if "32b" in name or "33b" in name else 24 if "14b" in name else 16
    if available_vram < required_vram:
        raise SystemExit(f"偵測到 {available_vram:.1f} GB CUDA VRAM；{args.model} 的保守 QLoRA 前檢需要至少 {required_vram} GB。")

    quantization=d["BitsAndBytesConfig"](load_in_4bit=True,bnb_4bit_quant_type="nf4",bnb_4bit_compute_dtype=torch.bfloat16,bnb_4bit_use_double_quant=True)
    tokenizer=d["AutoTokenizer"].from_pretrained(args.model, revision=args.revision, trust_remote_code=args.trust_remote_code)
    if tokenizer.pad_token is None: tokenizer.pad_token=tokenizer.eos_token
    model=d["AutoModelForCausalLM"].from_pretrained(args.model,revision=args.revision,device_map="auto",trust_remote_code=args.trust_remote_code,quantization_config=quantization)
    model=d["prepare_model_for_kbit_training"](model)
    model.add_adapter(d["LoraConfig"](r=args.lora_rank,lora_alpha=args.lora_rank*2,lora_dropout=.05,bias="none",task_type="CAUSAL_LM",target_modules="all-linear"))

    raw=load_dataset("json",data_files=str(args.dataset),split="train")
    eval_raw=load_dataset("json",data_files=str(args.eval_dataset),split="train") if args.eval_dataset else None
    if eval_raw is None and len(raw)>=20:
        split=raw.train_test_split(test_size=max(1,round(len(raw)*.1)),seed=args.seed)
        raw,eval_raw=split["train"],split["test"]

    def tokenize(example):
        messages=example.get("messages")
        if not isinstance(messages,list) or not messages: raise ValueError("每筆 JSONL 必須有 messages 陣列。")
        full_text=tokenizer.apply_chat_template(messages,tokenize=False,add_generation_prompt=False)
        result=tokenizer(full_text,truncation=True,max_length=args.max_seq_length,add_special_tokens=False)
        if args.full_sequence_loss:
            result["labels"]=list(result["input_ids"]); return result
        assistant_indexes=[i for i,m in enumerate(messages) if isinstance(m,dict) and m.get("role")=="assistant"]
        if not assistant_indexes: raise ValueError("Assistant-only loss 需要每筆至少一個 assistant 訊息。")
        last=assistant_indexes[-1]
        prefix=messages[:last]
        prefix_text=tokenizer.apply_chat_template(prefix,tokenize=False,add_generation_prompt=True)
        prefix_ids=tokenizer(prefix_text,truncation=True,max_length=args.max_seq_length,add_special_tokens=False)["input_ids"]
        mask=min(len(prefix_ids),len(result["input_ids"]))
        result["labels"]=[-100]*mask + list(result["input_ids"])[mask:]
        return result

    train_tokens=raw.map(tokenize,remove_columns=raw.column_names)
    eval_tokens=eval_raw.map(tokenize,remove_columns=eval_raw.column_names) if eval_raw is not None else None
    args.output.mkdir(parents=True,exist_ok=True)
    kwargs=dict(output_dir=str(args.output),num_train_epochs=args.epochs,learning_rate=args.learning_rate,per_device_train_batch_size=1,gradient_accumulation_steps=16,gradient_checkpointing=True,bf16=True,logging_steps=5,save_strategy="epoch",report_to="none",seed=args.seed,data_seed=args.seed)
    callbacks=[]
    if eval_tokens is not None:
        parameter="eval_strategy" if "eval_strategy" in d["inspect"].signature(d["TrainingArguments"].__init__).parameters else "evaluation_strategy"
        kwargs[parameter]="epoch"; kwargs.update(load_best_model_at_end=True,metric_for_best_model="eval_loss",greater_is_better=False)
        callbacks=[d["EarlyStoppingCallback"](early_stopping_patience=max(1,args.early_stopping_patience))]
    training_args=d["TrainingArguments"](**kwargs)
    trainer=d["Trainer"](model=model,args=training_args,train_dataset=train_tokens,eval_dataset=eval_tokens,data_collator=d["DataCollatorForSeq2Seq"](tokenizer,model=model,label_pad_token_id=-100,pad_to_multiple_of=8),callbacks=callbacks)
    resume=str(args.resume_from_checkpoint.resolve()) if args.resume_from_checkpoint else None
    train_result=trainer.train(resume_from_checkpoint=resume); trainer.save_state(); trainer.save_model(str(args.output)); tokenizer.save_pretrained(str(args.output))
    eval_metrics=trainer.evaluate() if eval_tokens is not None else None
    curve=json_safe(trainer.state.log_history); (args.output/"training-curve.json").write_text(json.dumps(curve,ensure_ascii=False,indent=2),encoding="utf-8")

    smoke={"prompt":args.smoke_prompt,"ok":False}
    try:
        model.eval(); encoded=tokenizer(args.smoke_prompt,return_tensors="pt")
        device=next(model.parameters()).device; encoded={k:v.to(device) for k,v in encoded.items()}
        with torch.no_grad(): output=model.generate(**encoded,max_new_tokens=48,do_sample=False)
        smoke.update(ok=True,response=tokenizer.decode(output[0][encoded["input_ids"].shape[1]:],skip_special_tokens=True).strip())
    except Exception as error:
        smoke["error"]=str(error)

    merged=None
    if args.merge_output:
        try:
            args.merge_output.mkdir(parents=True,exist_ok=True)
            merged_model=model.merge_and_unload(); merged_model.save_pretrained(str(args.merge_output),safe_serialization=True); tokenizer.save_pretrained(str(args.merge_output)); merged=str(args.merge_output.resolve())
        except Exception as error:
            raise SystemExit(f"Adapter 已訓練，但要求的 merge/export 失敗：{error}") from error

    metadata={"base_model":args.model,"revision":args.revision,"dataset":str(args.dataset.resolve()),"train_examples":len(raw),"eval_examples":len(eval_raw) if eval_raw is not None else 0,"epochs":args.epochs,"lora_rank":args.lora_rank,"seed":args.seed,"assistant_only_loss":not args.full_sequence_loss,"trust_remote_code":args.trust_remote_code,"resumed_from":resume,"vram_gb":round(available_vram,1),"train_metrics":json_safe(train_result.metrics),"eval_metrics":json_safe(eval_metrics),"smoke_test":smoke,"merged_output":merged}
    (args.output/"ai-hub-training.json").write_text(json.dumps(metadata,ensure_ascii=False,indent=2),encoding="utf-8")
    print(json.dumps(metadata,ensure_ascii=False)); return 0


if __name__ == "__main__": sys.exit(main())
