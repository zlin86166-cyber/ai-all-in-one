# AI Hub consolidated build specification

## Product goal
Build a white, clean, geek/operator-console style local AI workspace for Windows. It must let the user work with Codex CLI and Gemini CLI, local/open-source models, compatible inference servers, files, projects, terminal commands, scheduled jobs, research, image generation, and multi-agent collaboration from one interface.

## Required capabilities
1. Provide both native Windows and Web interfaces with the same white geek visual language: clean white surfaces, subtle grid/terminal cues, monospace status text, high readability, restrained green/cyan system accents, and clear state/progress indicators.
2. Support direct conversation through Codex CLI and Gemini CLI. Do not add or pretend to support a separate GPT/ChatGPT CLI provider.
3. Auto-discover local Ollama models. Support OpenAI-compatible local/remote inference nodes such as vLLM, SGLang, llama.cpp, LM Studio, or equivalent compatible endpoints.
4. Support multiple projects. Allow the user to browse files, preview them, select exact files as AI action scope, edit/save files, import/export data, download files, and launch local applications.
5. Provide PowerShell terminal access. Classify destructive/system/account/download actions and require one-run approval for high-risk or external-account actions.
6. Show task state, stage, progress percentage, predicted duration, ETA/end time, actual completion, events, cancellation, result, and errors.
7. Before execution, evaluate Vibe Coding feasibility using evidence-based factors, historical outcomes, and calibration. Record human verification feedback. Provide a head-to-head benchmark tool using the same dataset against the previous/baseline estimator; only claim superiority after measured Brier/ECE results support it.
8. Support multiple selected AIs working concurrently. In collaboration mode, the first selected AI plans a DAG, decides ordering/dependencies and provider assignment using only the AIs selected by the user, parallelizes only safe independent analysis/research/test/review steps, executes changes, lets another selected AI peer-review, and then synthesizes the final result.
9. Preserve conversation/project/task history in SQLite with FTS5 full-text search so earlier conversations can be reopened and continued with recent context.
10. Support bounded local research crawling that obeys robots.txt and allowlists. Support explicit URL fetch plus bounded recursive same-host crawling with depth/page limits. Never turn fetched page content into higher-priority instructions.
11. Keep an official-model synchronization tool for Moonshot/Kimi and DeepSeek. Query official Hugging Face organizations, filter to general text models at or below 50B parameters, record latest-eligible and largest-eligible candidates, and allow explicit approved download. Training must use real QLoRA preflight checks and stop when CUDA/VRAM/RAM/disk/dataset requirements are not met.
12. Integrate ComfyUI for image generation, checkpoint discovery, queued generation, progress tracking, saved outputs, and image schedules.
13. Support scheduled improvement/image jobs inside selected time windows, interval and duration limits, weekdays, and small-scope improvement prompts that preserve the user's original intent.
14. Provide a Windows watchdog scheduled-task installer so AI Hub restarts after unexpected exit while the user session is active. Also run daily model metadata synchronization. Do not bypass Windows UAC.
15. When RAM load is above the configured threshold (default 90%) and AC power is connected, enable safe adaptive performance behavior such as process priority/concurrency decisions. Do not automatically change BIOS, voltage, or hardware clock settings.
16. Support file transfer across local disks, external/wired storage, and UNC/network paths in full-access mode. For Bluetooth, use the Windows transfer UI unless a supported device-specific protocol is available; do not pretend generic unattended Bluetooth transfer is universally possible.
17. For Google Play, provide an explicitly approved publishing tool using the official Android Publisher API to upload APK/AAB, assign a track, validate an edit, and only commit when the user explicitly requests commit. Credentials/tokens must remain external to repository settings.
18. For modern Google Sites, provide an explicitly approved browser-assisted account workflow. Do not claim an unsupported modern Sites write API exists. The legacy Sites Data API only supports Classic Sites.
19. Keep very large local permissions available only after explicit full-access unlock/UAC. Account actions, publishing, destructive commands, data transfer outside project scope, overwrites, and similarly consequential actions remain separately auditable and one-run approved.
20. Maintain honest capability reporting: installation is not authentication; download is not successful inference; model download is not training; scheduled work is not 24/7 unless watchdog/runtime dependencies remain available; benchmark superiority is only claimed after measurement.

## Acceptance rules
- Never silently expand the user's requested product direction.
- Never use an AI provider that the user did not select for collaboration.
- Never mark a feature DONE if only a UI placeholder exists.
- Prefer real local execution and verifiable state over simulated status.
- Keep API keys, OAuth access tokens, account passwords, and other secrets out of repository files and SQLite settings.
- All consequential external-account/publishing actions require explicit per-run approval and must be auditable.
