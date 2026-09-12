# AI Hub requirement coverage

Updated: 2026-09-12

Status meanings: `DONE` = executable implementation exists; `MEASURE` = implementation exists but the requested superiority/result depends on real benchmark data; `PLATFORM` = implementation is limited by an external platform capability and must not be misrepresented.

| Requirement | Status | Implementation |
|---|---|---|
| Native white clean geek interface | DONE | Native desktop uses the white `desktop.py` operator console; `desktop_geek.py` is an optional dark skin and is not the packaged default. |
| Downloadable local Windows package | DONE | Windows Build creates `AIHub.exe`, three bundled integration helpers, setup/watchdog files, training files and `AIHub-Windows.zip`; `v*` tags attach the ZIP to GitHub Release. |
| Local launch without Web server | DONE | `start.ps1` launches native desktop only; `-Web` is explicitly rejected. Release users can launch `AIHub.exe` directly. |
| Normal launch without forced admin | DONE | Native build no longer embeds `--uac-admin`; `start.ps1 -Elevate` is explicit. `-MaxControl` is also explicit. |
| Frozen integration execution | DONE | `IntegrationManager` uses `AIHubModelSync.exe`, `AIHubPlayPublish.exe` and `AIHubSitesAssist.exe` instead of treating frozen `AIHub.exe` as a Python interpreter. |
| Gemini CLI conversation | DONE | `GeminiProvider`. |
| Codex CLI conversation | DONE | `CodexProvider`. |
| ChatGPT CLI conversation | DONE | `ChatGPTCLIProvider` invokes the official `openai responses create` CLI; authentication uses the configured API-key environment variable. |
| Execution progress / ETA / predicted end | DONE | Task/event/progress/predicted time fields and UI. |
| Other open-source AI | DONE | Ollama discovery plus OpenAI-compatible endpoints. |
| Multiple projects / selected files | DONE | Project scope, file explorer, preview, selected files, write controls. |
| Downloads / local modification / terminal | DONE | Download, file transfer, file write, PowerShell providers and approval classification. |
| Google Play APK/AAB publishing | DONE | Bundled helper uses the official Android Publisher API, requires account approval, validates by default, and only commits with explicit commit. |
| Modern Google Sites account workflow | PLATFORM | Bundled helper opens an explicitly approved account session. Google does not provide a supported write API for rebuilt/modern Sites. |
| Latest eligible Kimi/DeepSeek ≤50B | DONE | Bundled model-sync helper queries official Hugging Face org metadata and filters eligible text models dynamically. |
| Download/train eligible Kimi/DeepSeek | DONE | Model manager supports approved HF download and real QLoRA workflow; real training correctly requires a compatible external CUDA/Python ML environment. |
| RAM >90% + AC performance mode | DONE | Safe adaptive process-priority behavior. Automatic BIOS/voltage/clock overclock is intentionally not performed. |
| Local research crawler | DONE | Existing robots/allowlist fetch plus bounded same-host recursive crawl. |
| Multiple AI concurrent work | DONE | Task threads and multi-provider execution. |
| Vibe Coding feasibility | DONE | Evidence evaluator + local calibration. |
| Prove more accurate than previous website | MEASURE | `training/benchmark_feasibility.py` compares identical cases using Brier, ECE and log loss; superiority is only claimed when data proves it. |
| AI collaboration order/delegation/selected-only | DONE | DAG planner, allowlist, dependencies, safe parallelism, peer review, synthesis. |
| 24/7 intermittent work / crash restart | DONE | Native-only watchdog restart loop plus optional scheduled task. This applies while the Windows user session and machine are available. |
| Time-window self-improvement | DONE | Scheduler window/interval/duration/weekdays and intent-preserving prompt. |
| Continuous image generation | DONE | ComfyUI + image schedules + optional watchdog keeping AI Hub available. ComfyUI itself must be installed/running. |
| AI monitors AI | DONE | Peer review plus task/event monitoring. |
| Old conversations and continuation | DONE | SQLite + FTS5 + history injection. |
| Network / wired / UNC import-export | DONE | File transfer in full mode. |
| Bluetooth | PLATFORM | Windows `fsquirt.exe` workflow is supported. Fully unattended transfer depends on paired-device/profile/protocol support. |
| Launch local apps | DONE | Explicitly approved external-app launcher. |
| Very large system permissions | DONE | Full mode plus scoped/one-run approvals and audit log; OS elevation is explicit instead of automatic. |

## Local distribution rules

- AI Hub is a Windows native desktop product, not a Web UI product.
- The release must be usable by launching `AIHub.exe` locally.
- Codex/Gemini/OpenAI CLI initialization is handled by `setup.ps1`; portable Node.js and the SHA256-verified official OpenAI Windows binary are installed into `.runtime`.
- QLoRA is intentionally different: a real NVIDIA CUDA/Python ML environment is required and may be specified with `AI_HUB_TRAINING_PYTHON`.
- Runtime data remains local beside the installed/extracted app unless the user explicitly transfers it elsewhere.

## External facts that remain intentionally constrained

- Rebuilt/modern Google Sites has no supported general-purpose write API; browser-assisted use is the honest integration path.
- Hardware auto-overclocking is not treated as a software permission feature. AI Hub uses safe OS-level adaptive performance rather than BIOS/voltage/clock modification.
- Feasibility accuracy superiority is a measured property, not a promise. Use the benchmark tool with the same labeled cases from the previous estimator.

## Production completion pass (2026-09-06)

- Product surface: Native Windows Desktop only; Web startup is not part of the supported distribution path.
- Distribution: complete Windows ZIP artifact plus tag-based GitHub Release asset.
- Permissions: normal launch is non-elevated; OS elevation and MaxControl are explicit requests.
- Reliability: crash recovery + collaboration checkpoint resume + native watchdog + scheduler overlap/cross-midnight handling.
- Quality: structured peer-review gate with remediation; unverified task completion does not train feasibility calibration.
- Progress: fake elapsed-time/output-line percentages removed; unknown progress is event-driven/unknown.
- Models: official dynamic Kimi/DeepSeek metadata is merged into the main catalog.
- Integrations: Google Play, Google Sites browser-assisted session and model sync have bundled frozen helpers.
- Training: revision pinning, deterministic seed, assistant-only loss, validation/eval loss, early stopping, resume, training curve, smoke test, optional merged export.
- Production engineering: runtime data git hygiene, retention/backups, cross-platform CI, Windows executable and packaged release build.
- Hardening follow-up: the versioned local API entry point is restored; compatibility API traffic is loopback-only with a session cookie and same-origin check; Full mode has a visible phrase + UAC path; cancelled/child tasks are not independently replayed after restart; QLoRA requires previously verified local Hugging Face weights and never silently downloads during training.

Platform limits remain explicit: Modern Google Sites has no supported generic modern Sites write API; external-account flows need real user credentials/OAuth; real QLoRA execution requires compatible NVIDIA CUDA hardware; selected-file enforcement is rollback/snapshot based rather than a Windows kernel sandbox.
