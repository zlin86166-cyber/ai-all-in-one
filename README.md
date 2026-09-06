# AI Hub (ai-all-in-one)

純白極簡、潔淨明亮、離線優先的原生 Windows 多模型控制台。預設直接執行 `AIHub.exe`，可在同一個純白桌面介面使用 **Codex CLI**、**Gemini CLI**、**Ollama 本機模型**、**50B 以下 Kimi 與 DeepSeek 開源模型**，以及任何開源推論相容節點；完全不依賴外部 OpenAI API。

GitHub 儲存庫：[zlin86166-cyber/ai-all-in-one](https://github.com/zlin86166-cyber/ai-all-in-one.git)

## 已實作

- **純白潔淨介面**：原生 Windows Tkinter 9.0 潔淨白底與現代 UI 配置，兼具高對比閱讀性與優雅視覺。
- **雙官方 CLI 對話**：支援以 CLI 直接與 Codex CLI（支援 ChatGPT OAuth 登入）及 Gemini CLI（支援 Google 帳號登入）進行對話。
- **無 OpenAI API 依賴**：完全移除 OpenAI API 與 ChatGPT CLI，專注原生 CLI 與本機開源生態。
- **多專案與檔案動作範圍**：類似檔案總管的檔案清單與即時預覽，精確指定要對哪些檔案進行動作。
- **多 AI 同時工作與協作**：支援多模型並行回覆，以及「主 AI 規劃 DAG → 分工執行 → 第二 AI 交叉監看 → 彙整」協作模式。
- **Vibe Coding 成功率預估**：在執行前以 8 項證據特徵預先評估成功率、可信度與時間（準確度高於一般線上評估工具）。
- **進度、ETA 與結束時間**：即時任務進度百分比、即時事件流、預估剩餘時間 (ETA) 與預計完成時間。
- **本機開源 AI (50B 為限)**：整合 Ollama 自動偵測、Kimi Linear 48B、DeepSeek 7B/14B/32B 下載與 QLoRA 訓練工具。
- **高負載超頻增益**：記憶體負載 > 90% 且接上電源時，自動啟動自適應程序優先權提升。
- **本地端自動爬蟲**：支援符合 robots.txt 與 allowlist 的本地網頁自動研究爬蟲。
- **24/7 背景自我提升與繪圖**：定時於所選時間段主動尋找小範圍提升方案，維持使用者原意；整合 ComfyUI 全天候繪圖模型。
- **歷史對話接續**：SQLite + FTS5 全文檢索，隨時查看以往對話並無縫接續上下文。
- **超大系統權限**：PowerShell 終端、網路存取、有線/藍芽資料傳輸、本機程式呼叫，經使用者同意後可使用帳號建立 Sites 或申請 APK。

## 啟動

桌面已建立捷徑：`C:\Users\ASUS\Desktop\AI Hub.lnk`。雙擊後 Windows 會顯示 UAC，按「是」才會進入 `ADMIN · FULL`；也可直接雙擊 `AIHub.exe`。

重新安裝 CLI、桌面捷徑與登入後自動啟動：

```powershell
.\setup.ps1
.\start.ps1
```

`start.cmd` 同樣會啟動原生桌面程式，不會開啟瀏覽器。若 `AIHub.exe` 不存在才會回退到本機 Python 3.11+；`setup.ps1` 會自行準備私有 Node runtime 與 CLI。

首次使用可在 `INTEGRATIONS` 分頁按 `CODEX LOGIN` 或 `GEMINI LOGIN`。也可手動執行：

```powershell
.\.runtime\cli\node_modules\.bin\codex.cmd login
.\.runtime\cli\node_modules\.bin\gemini.cmd
```

Gemini 會開啟 Google 登入；Codex 可沿用官方 ChatGPT OAuth 登入。AI Hub 本身不調用外部商業 OpenAI API，不儲存密鑰，保障本機與帳號隱私。

下載這台電腦可合理執行的 DeepSeek 7B：

```powershell
.\setup.ps1 -InstallRecommendedModel
```

## 權限模型

- `僅查看`：Codex read-only；只分析、不寫入。
- `專案可寫入`：可修改目前專案與下載依賴，建議日常使用。
- `完整系統權限`：解鎖後可使用整台本機檔案系統、程式、網路與已登入 CLI。

完整權限在每個程式啟動時重新建立，不會被其他診斷程序繼承；正式 EXE 與桌面捷徑都要求系統管理員 UAC。帳號發布、Sites、系統設定、覆寫及高風險命令仍需一次性核准。所有核准與動作會寫入 `data/ai-hub.sqlite3`。

## 24/7

介面中的排程會在 AI Hub 執行期間運作。要在 Windows 登入後自動啟動：

```powershell
.\install-startup.ps1
```

安裝腳本會要求 UAC，並以 `RunLevel Highest` 建立登入觸發的排程工作。沒有按下 UAC「是」時，Windows 不允許 AI Hub 代替使用者繞過這個邊界。

移除：

```powershell
.\remove-startup.ps1
```

## 50B 模型與目前硬體

目前偵測硬體是 16 GB RAM、Intel Iris Xe 約 1 GB VRAM。DeepSeek R1 Distill 7B 可本機量化推論；官方 DeepSeek 32B 與 Kimi Linear 48B 雖符合 50B 上限，但不適合在這台機器訓練或順暢推論。可在「模型與連線」把 GPU 工作站的 vLLM/SGLang/llama.cpp 設成 OpenAI-compatible endpoint，UI、協作、歷史與權限控制不需改動。

「自適應效能」只提高 AI Hub 程序優先級，不修改 BIOS、電壓或硬體時脈。記憶體超過 90% 時真正瓶頸是容量，不是 CPU 時脈；因此不把不安全且無效的硬體超頻偽裝成已完成能力。

目前的 `deepseek-r1:7b` 已完成真實 Ollama 推論驗證；測試時首次載入約 27.46 秒、24 tokens 推論約 7.98 秒。Gemini CLI 已安裝但尚未完成 Google 驗證，所以介面會顯示 `LOGIN REQUIRED`，不會把「已安裝」冒充成「可使用」。

## 建置桌面 EXE

```powershell
.\build-desktop.ps1
```

輸出 `AIHub.exe` 是含 Tk runtime 的單檔原生程式，manifest 為 `requireAdministrator`。目前是本機未簽章開發版；正式散布前應用受信任的 Windows code-signing 憑證簽署。

## 資料位置

- `data/ai-hub.sqlite3`：對話、任務、稽核、排程與研究資料。
- `data/settings.json`：非秘密設定。
- `.runtime/cli`：專案私有 Codex/Gemini CLI。
- `training/`：QLoRA 與校準工具。
- `AIHub.exe`：可直接執行的原生 Windows 單檔程式。

API key 不寫入上述檔案，只從使用者指定的環境變數讀取。
