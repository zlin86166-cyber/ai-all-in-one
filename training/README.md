# 模型訓練與校準

AI Hub 把兩件事分開：

1. `train_calibrator.py` 用真實任務的成功/失敗標註訓練小型成功率校準器，可在 CPU 執行。
2. `train_lora.py` 才會修改模型行為（QLoRA adapter），需要 WSL2/Linux、NVIDIA CUDA 與足夠 VRAM。

資料集採 JSONL，每行至少包含：

```json
{"messages":[{"role":"user","content":"需求"},{"role":"assistant","content":"理想回覆"}]}
```

本工具採保守前檢：8B 至少 16 GB CUDA VRAM，32B 建議至少 48 GB，Kimi Linear 48B 建議至少 80 GB，且還要保留足夠 RAM 與模型/optimizer 磁碟空間。目前這台 Intel Iris Xe / 16 GB RAM 電腦不符合條件。腳本會在無 CUDA 或容量不足時明確停止，不會把提示詞校準宣稱成模型微調。

範例：

```bash
python training/train_lora.py --model deepseek-ai/DeepSeek-R1-Distill-Qwen-32B --dataset training/data.jsonl --output training/output/deepseek
```
