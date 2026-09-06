from __future__ import annotations

import argparse
import json
import mimetypes
import os
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

API = "https://androidpublisher.googleapis.com/androidpublisher/v3/applications"
UPLOAD = "https://androidpublisher.googleapis.com/upload/androidpublisher/v3/applications"


def request_json(url: str, token: str, method: str = "GET", payload: Any | None = None, content_type: str = "application/json") -> dict[str, Any]:
    body = None
    if payload is not None:
        body = json.dumps(payload).encode("utf-8") if content_type == "application/json" else payload
    request = urllib.request.Request(
        url,
        data=body,
        method=method,
        headers={"Authorization": f"Bearer {token}", "Content-Type": content_type, "Accept": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=180) as response:
            raw = response.read()
    except urllib.error.HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Google Play API HTTP {error.code}: {detail[-4000:]}") from error
    return json.loads(raw.decode("utf-8")) if raw else {}


def publish(package: str, artifact: Path, track: str, status: str, token: str, commit: bool) -> dict[str, Any]:
    edit = request_json(f"{API}/{urllib.parse.quote(package)}/edits", token, "POST", {})
    edit_id = str(edit.get("id") or "")
    if not edit_id:
        raise RuntimeError("Google Play API 未回傳 edit id。")

    suffix = artifact.suffix.lower()
    endpoint = "bundles" if suffix == ".aab" else "apks"
    upload_url = f"{UPLOAD}/{urllib.parse.quote(package)}/edits/{urllib.parse.quote(edit_id)}/{endpoint}?uploadType=media"
    uploaded = request_json(
        upload_url,
        token,
        "POST",
        artifact.read_bytes(),
        mimetypes.guess_type(artifact.name)[0] or "application/octet-stream",
    )
    version_code = uploaded.get("versionCode")
    if version_code is None:
        raise RuntimeError(f"上傳完成但沒有 versionCode：{uploaded}")

    release = {
        "releases": [{
            "name": f"AI Hub upload {artifact.name}",
            "versionCodes": [str(version_code)],
            "status": status,
        }]
    }
    track_url = f"{API}/{urllib.parse.quote(package)}/edits/{urllib.parse.quote(edit_id)}/tracks/{urllib.parse.quote(track)}"
    track_result = request_json(track_url, token, "PUT", release)
    validate_url = f"{API}/{urllib.parse.quote(package)}/edits/{urllib.parse.quote(edit_id)}:validate"
    validation = request_json(validate_url, token, "POST", {})

    committed = None
    if commit:
        commit_url = f"{API}/{urllib.parse.quote(package)}/edits/{urllib.parse.quote(edit_id)}:commit"
        committed = request_json(commit_url, token, "POST", {})
    return {
        "package": package,
        "artifact": str(artifact),
        "edit_id": edit_id,
        "version_code": version_code,
        "track": track,
        "status": status,
        "track_result": track_result,
        "validation": validation,
        "committed": committed,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Google Play Developer Publishing API uploader for AI Hub")
    parser.add_argument("--package", required=True)
    parser.add_argument("--artifact", required=True, help=".aab or .apk")
    parser.add_argument("--track", default="internal")
    parser.add_argument("--status", choices=["draft", "inProgress", "halted", "completed"], default="draft")
    parser.add_argument("--commit", action="store_true", help="Commit the edit. Without this flag the tool only validates the edit.")
    parser.add_argument("--approve-account-action", action="store_true", help="Required explicit one-run approval flag")
    args = parser.parse_args()

    if not args.approve_account_action:
        raise SystemExit("拒絕執行：帳號/上架操作必須明確加上 --approve-account-action。")
    artifact = Path(args.artifact).expanduser().resolve()
    if not artifact.is_file() or artifact.suffix.lower() not in {".apk", ".aab"}:
        raise SystemExit("artifact 必須是存在的 .apk 或 .aab。")
    token = os.environ.get("GOOGLE_PLAY_ACCESS_TOKEN", "").strip()
    if not token:
        raise SystemExit("缺少 GOOGLE_PLAY_ACCESS_TOKEN。請先以已授權 Google 帳號取得短期 OAuth access token。")

    result = publish(args.package, artifact, args.track, args.status, token, args.commit)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if not args.commit:
        print("VALIDATED ONLY: 未提交 edit；要正式送出請再次確認後加入 --commit。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
