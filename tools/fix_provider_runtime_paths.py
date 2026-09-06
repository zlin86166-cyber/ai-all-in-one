from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
path = ROOT / "ai_hub" / "providers.py"
text = path.read_text(encoding="utf-8")
old = '''    openai_bin = paths.runtime / "openai-cli"\n    if openai_bin.exists():\n        path_entries.append(str(openai_bin))\n    portable_node = paths.runtime / "node"\n    if portable_node.exists():\n        for executable in portable_node.rglob("node.exe"):\n            path_entries.append(str(executable.parent))\n            break\n    bundled = Path(\n        os.environ.get(\n            "AI_HUB_BUNDLED_NODE",\n            r"C:\\Users\\ASUS\\.cache\\codex-runtimes\\codex-primary-runtime\\dependencies\\node\\bin",\n        )\n    )\n    if bundled.exists():\n        path_entries.append(str(bundled))\n'''
new = '''    portable_node = paths.runtime / "node"\n    if portable_node.exists():\n        for executable in portable_node.rglob("node.exe"):\n            path_entries.append(str(executable.parent))\n            break\n    bundled_override = os.environ.get("AI_HUB_BUNDLED_NODE")\n    if bundled_override:\n        bundled = Path(bundled_override)\n        if bundled.exists():\n            path_entries.append(str(bundled))\n'''
if old not in text:
    if new in text:
        raise SystemExit(0)
    raise RuntimeError("provider runtime block did not match expected source")
path.write_text(text.replace(old, new, 1), encoding="utf-8")
