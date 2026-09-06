# AI Hub model sync / account workflow notes

The runtime keeps secrets outside repository files. Model downloads, training, Google Play actions, and account-assisted workflows require explicit command flags and use environment/CLI authentication rather than storing credentials in `data/settings.json`.

- `tools/model_sync.py`: official Moonshot/DeepSeek Hugging Face metadata sync, ≤50B filtering, optional approved download/training.
- `tools/autonomous_research.py`: bounded same-host recursive research using the existing robots/allowlist crawler.
- `tools/play_publish.py`: Android Publisher API uploader; validate by default, explicit `--commit` required.
- `tools/google_sites_assist.py`: approved browser-assisted Modern Google Sites entry because the public Sites Data API only supports Classic Sites.
