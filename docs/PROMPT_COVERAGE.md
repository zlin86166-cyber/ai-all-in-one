# AI Hub requirement coverage

Updated: 2026-09-06

Status meanings: `DONE` = executable implementation exists; `MEASURE` = implementation exists but the requested superiority/result depends on real benchmark data; `PLATFORM` = implementation is limited by an external platform capability and must not be misrepresented.

| Requirement | Status | Implementation |
|---|---|---|
| White clean geek interface | DONE | Web uses base CSS + `web/geek.css`; native desktop uses `desktop_geek.py` palette wrapper and build entry. |
| Gemini CLI conversation | DONE | `GeminiProvider`. |
| Codex CLI conversation | DONE | `CodexProvider`. |
| Execution progress / ETA / predicted end | DONE | Task/event/progress/predicted time fields and UI. |
| Other open-source AI | DONE | Ollama discovery plus OpenAI-compatible endpoints. |
| Multiple projects / selected files | DONE | Project scope, file explorer, preview, selected files, write controls. |
| Downloads / local modification / terminal | DONE | Download, file transfer, file write, PowerShell providers and approval classification. |
| Google Play APK/AAB publishing | DONE | `tools/play_publish.py` uses the official Android Publisher API, requires `--approve-account-action`, validates by default, and only commits with `--commit`. |
| Modern Google Sites account workflow | PLATFORM | `tools/google_sites_assist.py` opens an explicitly approved account session. Google does not provide a supported write API for rebuilt/modern Sites; legacy Sites API only accesses Classic Sites. |
| Latest eligible Kimi/DeepSeek ≤50B | DONE | `tools/model_sync.py` queries official Hugging Face org metadata and filters eligible text models dynamically. Daily sync is installed by watchdog setup. |
| Download/train eligible Kimi/DeepSeek | DONE | Model sync supports explicit approved HF download and invokes real QLoRA training; hardware/data preflight may correctly block training when requirements are not met. |
| RAM >90% + AC performance mode | DONE | Safe adaptive process-priority behavior. Automatic BIOS/voltage/clock overclock is intentionally not performed. |
| Local research crawler | DONE | Existing robots/allowlist fetch plus `tools/autonomous_research.py` bounded same-host recursive crawl. |
| Multiple AI concurrent work | DONE | Task threads and multi-provider execution. |
| Vibe Coding feasibility | DONE | Evidence evaluator + local calibration. |
| Prove more accurate than previous website | MEASURE | `training/benchmark_feasibility.py` compares identical cases using Brier, ECE and log loss; superiority is only claimed when data proves it. |
| AI collaboration order/delegation/selected-only | DONE | DAG planner, allowlist, dependencies, safe parallelism, peer review, synthesis. |
| 24/7 intermittent work / crash restart | DONE | `watchdog.ps1` restart loop plus `install-watchdog.ps1` highest-run-level logon task. This applies while the Windows user session and machine are available; it does not bypass UAC or power-off. |
| Time-window self-improvement | DONE | Scheduler window/interval/duration/weekdays and intent-preserving prompt. |
| Continuous image generation | DONE | ComfyUI + image schedules + watchdog keeping AI Hub available. ComfyUI itself must be installed/running or separately configured to start. |
| AI monitors AI | DONE | Peer review plus task/event monitoring. |
| Old conversations and continuation | DONE | SQLite + FTS5 + history injection. |
| Network / wired / UNC import-export | DONE | File transfer in full mode. |
| Bluetooth | PLATFORM | Windows `fsquirt.exe` workflow is supported. Fully unattended transfer depends on paired-device/profile/protocol support and cannot be universalized safely. |
| Launch local apps | DONE | Explicitly approved external-app launcher. |
| Very large system permissions | DONE | UAC/full mode plus scoped/one-run approvals and audit log. |

## External facts that remain intentionally constrained

- Rebuilt/modern Google Sites has no supported general-purpose write API; browser-assisted use is the honest integration path.
- Hardware auto-overclocking is not treated as a software permission feature. AI Hub uses safe OS-level adaptive performance rather than BIOS/voltage/clock modification.
- Feasibility accuracy superiority is a measured property, not a promise. Use the benchmark tool with the same labeled cases from the previous estimator.
