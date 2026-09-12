# AI Hub (ai-all-in-one)

[公開下載站](https://ai-hub-windows-download.ai-pro-myhome.chatgpt.site) · [直接下載 Windows ZIP](https://github.com/zlin86166-cyber/ai-all-in-one/releases/download/v0.2.0/AIHub-Windows.zip) · [v0.2.0 Release](https://github.com/zlin86166-cyber/ai-all-in-one/releases/tag/v0.2.0)

AI Hub 是一套 **Windows 本機多模型 AI Operator Console**。正式產品只以原生 Windows 桌面版發佈：下載 `AIHub-Windows.zip`、解壓後直接執行 `AIHub.exe`，專案、對話、任務、模型 metadata、研究索引與設定都保存在本機。

核心支援 **Codex CLI、Gemini CLI、官方 OpenAI CLI（ChatGPT API）、Ollama 本機模型、≤50B 的 Kimi/DeepSeek 官方開源模型、OpenAI-compatible 推論節點、ComfyUI**，並整合多專案、檔案操作、PowerShell、任務進度、ETA、歷史對話、AI 協作、研究爬蟲、排程與權限控制。

## 正式發佈形式

Windows Build 會產生完整的本機套件：

- `AIHub.exe`：原生 Tkinter 桌面主程式。
- `AIHubModelSync.exe`：Kimi / DeepSeek 官方模型 metadata 同步工具。
- `AIHubPlayPublish.exe`：Google Play Android Publisher API helper。
- `AIHubSitesAssist.exe`：Modern Google Sites 瀏覽器輔助 helper。
- `setup.ps1`：初始化 Codex/Gemini CLI runtime 與桌面捷徑。
- watchdog / model-sync 腳本。
- `training/`：QLoRA 訓練腳本；實際訓練仍需要相容 NVIDIA CUDA / Python ML 環境。

GitHub Actions 的 **Windows Build** 會上傳 `AIHub-Windows.zip` artifact；建立 `v*` tag 時，同一個 ZIP 會附加到 GitHub Release，作為可直接下載的 Windows 發行包。

下載網站的可維護原始碼位於 `download-site/`；公開部署由 OpenAI Sites 執行，下載檔則固定來自 GitHub Release，訪客不需要 GitHub 登入即可下載。

## 第一次使用

1. 下載並解壓 `AIHub-Windows.zip` 到可寫入的本機資料夾。
2. 直接執行 `AIHub.exe` 使用本機桌面介面；一般啟動會自動進入 Full / MaxControl，Windows 可能顯示 UAC。
3. 要使用 Codex CLI / Gemini CLI 時，在 PowerShell 執行：

```powershell
.\setup.ps1
```

`setup.ps1` 會建立 `.runtime`，必要時下載 portable Node.js，並安裝測試過的 Codex/Gemini CLI 版本；預設只建立桌面捷徑，不會自動安裝 watchdog。

## 本機啟動

正式發行包：

```powershell
.\AIHub.exe
```

或：

```powershell
.\start.ps1
```

`start.ps1` 只啟動原生 Windows 桌面版。若需要以 source tree 開發：

```powershell
.\start.ps1 -Source
```

一般啟動預設會進入 Full / MaxControl；Windows 會依需要顯示 UAC。若要以較低權限啟動：

```powershell
.\start.ps1 -SafeMode
# 或
.\AIHub.exe --safe-mode
```

`-MaxControl` 仍可明確指定完整模式；`-Elevate` 可用於先手動提升 PowerShell。下載、覆寫與帳號操作仍會各自要求核准。

## 主要能力

- **Native Windows UI**：`desktop.py` 白色潔淨 + Operator Console 風格；`desktop_geek.py` 保留為可選深色外觀，不是預設入口。
- **CLI AI**：Codex CLI、Gemini CLI、官方 OpenAI CLI（ChatGPT API）。
- **本機/開源 AI**：Ollama 自動發現；vLLM、SGLang、llama.cpp、LM Studio 等可透過 OpenAI-compatible endpoint 接入。
- **多專案與檔案**：瀏覽、預覽、選取、修改、儲存、匯入/匯出與受控下載。
- **多 AI 協作**：Planner DAG → 依賴/分工 → 安全並行 → Peer Review → 最終彙整。
- **任務與進度**：stage、ETA、預計結束、事件流、取消、錯誤與恢復資訊。
- **Vibe Coding 成功性前檢**：8 項證據特徵、歷史校準與 benchmark。
- **模型同步**：動態查 Moonshot/DeepSeek 官方 Hugging Face metadata，篩選 ≤50B 文字模型。
- **研究**：robots.txt + allowlist + 有頁數/深度上限的本機研究爬蟲。
- **繪圖**：ComfyUI checkpoint、生成進度、輸出保存與排程。
- **Google Play**：上傳 APK/AAB、更新 track、validate；只有明確 `--commit` 才提交 edit。
- **Google Sites**：只提供 Modern Sites 瀏覽器輔助，不宣稱不存在的寫入 API。
- **watchdog**：可選安裝，Windows 使用者工作階段存在時監看程式退出並重啟。

## CLI 登入

完成 `setup.ps1` 後：

```powershell
.\.runtime\cli\node_modules\.bin\codex.cmd login
.\.runtime\cli\node_modules\.bin\gemini.cmd
.\.runtime\openai-cli\openai.exe --version
```

Codex/Gemini 的互動認證由官方 CLI 自己保存；OpenAI CLI 讀取 `OPENAI_API_KEY`（或整合頁指定的環境變數）。AI Hub 不把密碼或 API 金鑰寫入 SQLite/settings。

## 重新建置 Windows 發行版

```powershell
python -m pip install --upgrade pyinstaller
.\build-desktop.ps1
```

建置會產生主程式與三個 bundled helper。CI 會再把它們打成 `AIHub-Windows.zip`。

## 24/7 watchdog（選用）

```powershell
.\install-watchdog.ps1
```

移除：

```powershell
.\remove-watchdog.ps1
```

這個機制不能在電腦關機或 Windows 使用者工作階段不存在時執行 GUI 工作。

## QLoRA

QLoRA 是進階本機訓練功能。`AIHub.exe` 本身可直接執行，但真正的 QLoRA 仍需要 NVIDIA CUDA、足夠 VRAM/RAM/磁碟，以及安裝 Transformers/PEFT/BitsAndBytes 等套件的 Python ML 環境。可用 `AI_HUB_TRAINING_PYTHON` 指向該環境。

## 本機資料

AI Hub 會在執行檔旁建立或使用：

- `data/ai-hub.sqlite3`：對話、任務、核准、audit、研究與排程。
- `data/settings.json`：非秘密設定。
- `data/latest-models.json`：官方模型同步結果。
- `data/downloads/`：受控下載位置。
- `.runtime/cli`：Codex/Gemini CLI runtime。
- `training/`：QLoRA 工具。

完整規格見 `docs/MASTER_PROMPT.md`，需求覆蓋檢查見 `docs/PROMPT_COVERAGE.md`。

## 使用提示

啟動時會顯示三步使用導覽；任何時候按 F1 可重新開啟。預設已啟用 Full / MaxControl，先選專案、連接一個 AI，再輸入工作即可。若需要較低權限可用 `--safe-mode`。F5 重新檢查連線，Ctrl+K 搜尋，Ctrl+Enter 送出。訓練需要先獨立下載本地權重。

main 的最新建置請到 Actions → Windows Build → Artifacts 下載；v0.2.0 Release 不會因 main 更新而自動替換。
