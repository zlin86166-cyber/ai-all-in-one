# AI Hub (ai-all-in-one)

白色潔淨、極客 Operator Console 風格的本機 Windows 多模型工作台。核心支援 **Codex CLI、Gemini CLI、Ollama 本機模型、≤50B 的 Kimi/DeepSeek 官方開源模型、OpenAI-compatible 推論節點、ComfyUI**，並整合多專案、檔案操作、PowerShell、任務進度、ETA、歷史對話、AI 協作、研究爬蟲、排程與高權限控制。

## 主要能力

- **雙介面**：Web 版使用 `web/geek.css`；原生 Tkinter 版透過 `desktop_geek.py` 套用同一套白色極客配色。
- **CLI AI**：直接使用 Codex CLI 與 Gemini CLI。
- **本機/開源 AI**：Ollama 自動發現；vLLM、SGLang、llama.cpp、LM Studio 等可透過 OpenAI-compatible endpoint 接入。
- **多專案 + 檔案範圍**：檔案瀏覽、預覽、選取指定檔案、編輯/儲存、匯入/匯出、下載與開啟本機程式。
- **多 AI 協作**：Planner DAG → 依賴/分工 → 安全並行 → Peer Review → 最終彙整；只使用使用者選取的 AI。
- **Vibe Coding 成功性前檢**：8 項證據特徵、歷史成功率、校準、ETA；`training/benchmark_feasibility.py` 可與舊估算器在同一測試集做 Brier/ECE/log-loss 比較。
- **任務控制**：進度、stage、ETA、預計結束、實際結束、事件流、取消與錯誤紀錄。
- **模型同步**：`tools/model_sync.py` 每次直接查 Moonshot/DeepSeek 官方 Hugging Face 組織，篩選 `≤50B + 文字模型`，輸出最新符合與最大符合候選；可經明確核准後下載與啟動真實 QLoRA。
- **研究**：robots.txt + allowlist 的單頁擷取，以及 `tools/autonomous_research.py` 有深度/頁數上限的同網域遞迴研究。
- **繪圖**：ComfyUI checkpoint 探測、工作流、進度、輸出保存及排程。
- **24/7 可用性**：`watchdog.ps1` + `install-watchdog.ps1` 在 Windows 使用者工作階段內監看退出並重新啟動 AI Hub；另每日同步官方模型 metadata。
- **安全效能模式**：RAM 超過設定門檻且接電時提高程序優先權；不自動修改 BIOS、電壓或硬體時脈。
- **Google Play**：`tools/play_publish.py` 使用官方 Android Publisher API，上傳 APK/AAB、更新 track、validate；只有明確加 `--commit` 才提交 edit。
- **Google Sites**：`tools/google_sites_assist.py` 提供經核准的 Modern Sites 瀏覽器輔助流程。Google 現行 Sites API 只支援 Classic Sites，因此不假裝存在 Modern Sites 寫入 API。
- **高權限**：UAC + full mode；帳號、發布、破壞性操作、下載、跨專案資料傳輸等仍保留一次性核准與 audit log。

## 啟動

```powershell
.\setup.ps1
.\start.ps1
```

`start.ps1` 預設使用 `desktop_geek.py`，因此不受 repository 中舊版 `AIHub.exe` 視覺影響。重新建置最新 EXE：

```powershell
.\build-desktop.ps1
```

Web 版：

```powershell
.\start.ps1 -Web
```

## CLI 登入

```powershell
.\.runtime\cli\node_modules\.bin\codex.cmd login
.\.runtime\cli\node_modules\.bin\gemini.cmd
```

AI Hub 不把帳號密碼寫入 SQLite 或 settings；CLI 認證由官方 CLI 自己保存。

## 最新 ≤50B Kimi / DeepSeek

同步 metadata：

```powershell
python .\tools\model_sync.py
```

下載「目前最新符合」的 Kimi：

```powershell
python .\tools\model_sync.py --download Kimi --approve-download
```

下載後使用 JSONL 啟動 QLoRA（硬體前檢不通過會停止）：

```powershell
python .\tools\model_sync.py --download DeepSeek --approve-download --dataset .\training\data.jsonl --approve-training
```

如果要最大但仍 ≤50B 的候選，加 `--prefer-largest`。

## 24/7 watchdog

```powershell
.\install-watchdog.ps1
```

移除：

```powershell
.\remove-watchdog.ps1
```

這個機制不繞過 Windows UAC，也不能在電腦關機或使用者工作階段不存在時執行 GUI 工作。

## Google Play APK/AAB

先取得已授權帳號的短期 OAuth access token，放在環境變數 `GOOGLE_PLAY_ACCESS_TOKEN`。預設只 validate：

```powershell
python .\tools\play_publish.py --package com.example.app --artifact .\app-release.aab --track internal --approve-account-action
```

要真的提交 edit，需再次明確加入 `--commit`。

## Google Sites

Modern Google Sites 沒有官方可用的通用寫入 API；AI Hub 只提供誠實的瀏覽器輔助入口：

```powershell
python .\tools\google_sites_assist.py --title "My Site" --approve-account-action
```

## Vibe Coding 準確度比較

準備 CSV：`outcome,ai_hub,baseline`，其中機率是 0~1、outcome 是 0/1：

```powershell
python .\training\benchmark_feasibility.py .\benchmark.csv
```

只有當同一批標註資料的 Brier/ECE 實測較好時，才宣稱 AI Hub 的估算器優於舊基準。

## 資料位置

- `data/ai-hub.sqlite3`：對話、任務、核准、audit、研究與排程。
- `data/settings.json`：非秘密設定。
- `data/latest-models.json`：每日官方模型同步結果。
- `data/downloads/`：受控下載位置。
- `.runtime/cli`：私有 Codex/Gemini CLI runtime。
- `training/`：QLoRA 與成功率校準/benchmark 工具。

完整規格見 `docs/MASTER_PROMPT.md`，需求覆蓋檢查見 `docs/PROMPT_COVERAGE.md`。

## Production hardening

目前主幹採 hardened runtime：Observe 為真正唯讀；選取檔案工作有回復式範圍守衛；Full AI CLI 預設仍限制在 workspace，系統/帳號動作改走 AI Hub 一次性核准層；核准 5 分鐘內只能消耗一次。Web 控制面使用 loopback session cookie + same-origin 驗證。Crash 後一般 Provider 會自動 retry，協作流程會從最近 checkpoint 恢復；Peer Review 是品質閘門，未通過不會標成完成。

官方 Kimi/DeepSeek metadata 會直接合併到模型目錄；Google Play、Google Sites 與模型同步都已接入 Task/Audit backend。Modern Google Sites 仍受平台限制，採受核准的瀏覽器工作階段，不宣稱不存在的寫入 API。CI 會在 Windows/Linux 與 Python 3.11/3.13 跑單元測試；Windows Build workflow 產生最新 AIHub.exe artifact。
