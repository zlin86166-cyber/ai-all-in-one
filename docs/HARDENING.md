# AI Hub Production Hardening

本輪將權限、任務復原、品質閘門、真實進度、模型生命週期、整合工作、SSRF 防護、Watchdog、資料生命週期與 CI 由「功能存在」提升成可驗證的產品機制。

- Observe：唯讀；Workspace 終端機阻擋常見專案外路徑；選取檔案由 ScopedWorkspaceGuard 建立回復快照。
- Full：Codex/Gemini 預設不再 bypass sandbox；只有明確設定 `unsafe_full_cli` 才會恢復 CLI 原生危險模式。
- Approval：核准 5 分鐘內、同 fingerprint 僅可消耗一次。
- Web：只接受 loopback，使用 HttpOnly SameSite session cookie 與 Origin 檢查。
- Recovery：一般 Task crash 後 retry；協作 DAG 保存 checkpoint 並續跑未完成步驟。
- QA：Peer Review `pass` 才能完成；失敗會進 remediation，最多三輪。
- Progress：移除 elapsed-time 假百分比；沒有來源就只顯示 stage/ETA。
- Models：`latest-models.json` 合併進主 Catalog，可下載與 QLoRA 前檢。
- Integrations：Play/Sites/model sync 進入 Task + Audit。
- Research：DNS/private/reserved IP 與 redirect 再驗證，預設阻擋 SSRF 到 LAN/localhost。
- Reliability：Watchdog 辨識正常關閉、5 分鐘 5 次 crash loop 熔斷、log rotation。
- Maintenance：每日 SQLite backup、保留 7 份、事件/audit/research 清理與生成圖片 2GB quota。
- CI：Windows/Linux test matrix；Windows executable artifact build。
