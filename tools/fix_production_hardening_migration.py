from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# The generated security guard must interpret Windows-style parent paths even when
# CI runs on Linux.
security = ROOT / "ai_hub" / "security.py"
text = security.read_text(encoding="utf-8")
text = text.replace(
    '        target = canonical_path(root / value) if value.startswith("..") else canonical_path(value)\n',
    '        normalized = value.replace("\\\\", "/")\n        target = canonical_path(root / normalized) if normalized.startswith("..") else canonical_path(value)\n',
)
security.write_text(text, encoding="utf-8")

# A textual migration in v1 could match the image-schedule timer twice and create
# one mis-indented return. Normalize that branch, then add the return to the final
# improve-schedule branch.
application = ROOT / "ai_hub" / "application.py"
text = application.read_text(encoding="utf-8")
text = text.replace(
    "            timer.start()\n        return task\n            return task\n",
    "            timer.start()\n            return task\n",
)
text = re.sub(
    r"(\n        timer\.daemon = True\n        timer\.start\(\)\n)\s*$",
    r"\1        return task\n",
    text,
)
application.write_text(text, encoding="utf-8")
