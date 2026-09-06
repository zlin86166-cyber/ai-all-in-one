# AI Hub 原始需求覆蓋檢查

更新日期：2026-09-06

狀態定義：`DONE` 已有可執行程式碼；`PARTIAL` 有基礎能力但尚未完全達成原始語意；`MISSING` 尚未實作；`CONSTRAINED` 受平台/硬體/官方工具限制，不能誠實宣稱完成。

| 原始需求 | 狀態 | 現況 |
|---|---|---|
| 白色、潔淨、極客風介面 | DONE | Web 版保留原完整樣式並疊加 `web/geek.css`；白底、網格、mono、operator console 視覺。 |
| Gemini CLI 對話 | DONE | `GeminiProvider` 直接呼叫 Gemini CLI。 |
| Codex CLI 對話 | DONE | `CodexProvider` 直接呼叫官方 Codex CLI，支援 ChatGPT OAuth 登入。 |
| ChatGPT CLI 對話 | CONSTRAINED | 截至本次檢查，OpenAI 有官方 Codex CLI，但沒有可確認的獨立官方 ChatGPT CLI。不能把 Codex 假標成 ChatGPT CLI。 |
| 查看執行進度 | DONE | Task / task_events / progress。 |
| 預估執行時間、結束時間 | DONE | `predicted_seconds`、`predicted_end_at`、歷史校準。 |
| 相容其他開源 AI，下載到本機即可用 | DONE | Ollama 自動發現已安裝模型；另支援 OpenAI-compatible endpoint。 |
| 多專案 | DONE | project 資料表、專案切換、目錄範圍。 |
| 下載檔案/模型 | DONE | URL downloader、Ollama pull、Hugging Face downloader。 |
| 修改本機內容 | DONE | workspace/full 權限、檔案寫入與 Codex/Gemini 工作區修改。 |
| 經同意後使用帳號建立 Sites | PARTIAL | 有帳號/部署一次性核准與終端/CLI 執行能力，但沒有 Google Sites 專用可靠自動化流程。 |
| 經同意後用帳號申請 APK | PARTIAL | 有帳號/發布核准、外部程式與終端能力；沒有 Play Console 專用提交器。 |
| Kimi 最新模型（≤50B）下載/訓練 | PARTIAL | 已有 Kimi 48B 與 HF/QLoRA 管線，但模型目錄需持續跟官方更新；K3/K2 主線已超過 50B。 |
| DeepSeek 最新模型（≤50B）下載/訓練 | PARTIAL | R1 Distill 7B/32B 管線可用；V4 主線超過 50B。真正訓練受 CUDA/VRAM/RAM 限制。 |
| RAM >90% 且插電時超頻 | PARTIAL | 現在做的是 Windows process priority boost，不改 BIOS/電壓/時脈；這不是硬體超頻。 |
| 本地模型自動爬蟲 | PARTIAL | 有 robots.txt/allowlist crawler 與研究庫；目前主要由 prompt URL 或研究動作觸發，不是無限制自主全網爬取。 |
| 選擇要操作的檔案 | DONE | 檔案瀏覽器、預覽、selected_files、scope enforcement。 |
| 多模型同時工作 | DONE | 可多 provider 並行；TaskManager 背景 thread。 |
| Vibe Coding 成功率判斷 | DONE | 8 因素 evidence evaluator + 本機歷史校準。 |
| 比原網站更準 | PARTIAL | 有 Brier score/校準品質衡量，但尚未取得「原網站」相同測試集做 head-to-head benchmark，因此不能保證。 |
| AI 合作：先判斷順序、分工、只用所選 AI | DONE | DAG planner、provider allowlist、depends_on、parallel_safe、peer review、final synthesis。 |
| 全天候間斷工作 | PARTIAL | App 執行時 scheduler 可工作，Windows 登入可自啟；尚不是具 watchdog/崩潰自復原的 Windows Service。 |
| 指定時段/時長自己找提升方案 | DONE | schedule 具 start/end/duration/interval/weekdays，並保留原意的小範圍改善提示。 |
| 不大量改變使用者原意 | DONE | collaboration prompt 與改善排程均有禁止擴張原意的控制語句。 |
| 全天候繪圖模型 | PARTIAL | ComfyUI 已整合且可排程；是否 24/7 取決於 AI Hub/ComfyUI 是否持續運作。 |
| AI 監控其他 AI | DONE | 第二 provider peer review + task/event 監控。 |
| 查看以前對話並繼續 | DONE | SQLite conversations/messages + FTS5 + history injection。 |
| 終端機 | DONE | PowerShell provider/API/UI。 |
| 網路連線 | DONE | providers、crawler、download manager。 |
| 有線/網路資料匯入匯出 | DONE | file-transfer 可處理專案、外接磁碟、UNC/網路路徑（full 權限）。 |
| Bluetooth 匯入匯出 | PARTIAL | 可啟動 Windows `fsquirt.exe` 藍牙檔案傳輸精靈；不是背景無人值守 Bluetooth protocol stack。 |
| 使用電腦內 App/程式 | DONE | `launch_external_app` + full 權限 + 一次性系統核准。 |
| 很大的系統權限 | DONE | UAC `requireAdministrator`、full mode、全檔案系統/程式/網路能力；高風險/帳號/不可逆操作仍維持一次性核准。 |

## 仍需優先補齊

1. **ChatGPT CLI**：不能虛構官方 CLI。若未來 OpenAI 發布獨立 ChatGPT CLI，可新增 provider；目前 ChatGPT 帳號的官方 CLI 路徑是 Codex CLI OAuth。
2. **Google Sites / Play Console**：需要專用 connector/瀏覽器自動化與明確一次性核准，不能只靠「有 full access」就宣稱完成。
3. **真正 24/7**：應增加 Windows Service/watchdog、崩潰自啟、工作 checkpoint/resume。
4. **Vibe Coding 準確度**：需把原網站與 AI Hub 放到同一測試集，用 Brier score、ECE、成功率分桶比較。
5. **模型目錄自動更新**：官方模型快速變動，應定期同步 Hugging Face 官方 org metadata，再套用 `<=50B` 與用途篩選，而不是把「最新」寫死在 source code。
6. **硬體加速**：目前是程序優先權，不是硬體超頻。建議保持現狀或改為安全的 power-plan / worker concurrency / model offload 自適應；不應自動改 BIOS 電壓或時脈。
