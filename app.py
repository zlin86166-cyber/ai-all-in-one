from __future__ import annotations

import argparse
import signal
import sys
from pathlib import Path

from ai_hub.application import AIHubApplication


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Local multi-model AI workspace")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", default=8765, type=int)
    parser.add_argument("--no-browser", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    root = Path(__file__).resolve().parent
    app = AIHubApplication(root)

    def stop(_signum: int, _frame: object) -> None:
        app.stop()

    signal.signal(signal.SIGINT, stop)
    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, stop)
    app.serve(args.host, args.port, open_browser=not args.no_browser)
    return 0


if __name__ == "__main__":
    sys.exit(main())
