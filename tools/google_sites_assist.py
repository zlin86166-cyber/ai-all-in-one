from __future__ import annotations

import argparse
import json
import os
import subprocess
import webbrowser
from datetime import datetime, timezone
from pathlib import Path


def open_modern_sites(title: str, template_url: str | None, profile: str | None) -> dict[str, str]:
    url = template_url or "https://sites.new"
    opened_with = "default-browser"
    if profile:
        candidates = [
            os.path.expandvars(r"%ProgramFiles%\Google\Chrome\Application\chrome.exe"),
            os.path.expandvars(r"%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe"),
            os.path.expandvars(r"%ProgramFiles(x86)%\Microsoft\Edge\Application\msedge.exe"),
            os.path.expandvars(r"%ProgramFiles%\Microsoft\Edge\Application\msedge.exe"),
        ]
        executable = next((item for item in candidates if Path(item).is_file()), None)
        if executable:
            subprocess.Popen([executable, f"--profile-directory={profile}", url])
            opened_with = executable
        else:
            webbrowser.open(url)
    else:
        webbrowser.open(url)
    return {
        "title": title,
        "url": url,
        "opened_with": opened_with,
        "opened_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "mode": "modern-sites-browser-assisted",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Open an explicitly approved modern Google Sites creation session")
    parser.add_argument("--title", required=True)
    parser.add_argument("--template-url")
    parser.add_argument("--profile", help="Optional Chrome/Edge profile directory name, e.g. 'Default'")
    parser.add_argument("--approve-account-action", action="store_true")
    parser.add_argument("--manifest", default="data/sites-last-session.json")
    args = parser.parse_args()

    if not args.approve_account_action:
        raise SystemExit("拒絕執行：Google 帳號操作必須明確加上 --approve-account-action。")
    result = open_modern_sites(args.title, args.template_url, args.profile)
    root = Path(__file__).resolve().parents[1]
    manifest = Path(args.manifest)
    if not manifest.is_absolute():
        manifest = root / manifest
    manifest.parent.mkdir(parents=True, exist_ok=True)
    manifest.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    print("Modern Google Sites does not expose a supported write API. AI Hub opened the account session; final site editing/publishing remains in Google's browser UI.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
