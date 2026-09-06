from __future__ import annotations

import argparse
import html.parser
import sys
import urllib.parse
import urllib.request
from collections import deque
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ai_hub.application import AIHubApplication


class LinkExtractor(html.parser.HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.links: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag != "a":
            return
        for key, value in attrs:
            if key == "href" and value:
                self.links.append(value)


def links_from(url: str, max_bytes: int = 1_000_000) -> list[str]:
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "AIHubLocalResearch/1.0", "Accept": "text/html"},
    )
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            if response.headers.get_content_type() != "text/html":
                return []
            raw = response.read(max_bytes + 1)
            if len(raw) > max_bytes:
                return []
            charset = response.headers.get_content_charset() or "utf-8"
    except OSError:
        return []
    parser = LinkExtractor()
    parser.feed(raw.decode(charset, errors="replace"))
    base = urllib.parse.urlparse(url)
    result: list[str] = []
    seen: set[str] = set()
    for href in parser.links:
        absolute = urllib.parse.urljoin(url, href)
        parsed = urllib.parse.urlparse(absolute)
        if parsed.scheme not in {"http", "https"} or parsed.hostname != base.hostname:
            continue
        clean = urllib.parse.urlunparse(
            (parsed.scheme, parsed.netloc, parsed.path, parsed.params, parsed.query, "")
        )
        if clean not in seen:
            seen.add(clean)
            result.append(clean)
    return result


def crawl(
    app: AIHubApplication,
    seeds: list[str],
    max_pages: int,
    max_depth: int,
) -> tuple[int, int]:
    queue = deque((url, 0) for url in seeds)
    visited: set[str] = set()
    saved = 0
    failed = 0
    while queue and len(visited) < max_pages:
        url, depth = queue.popleft()
        if url in visited:
            continue
        visited.add(url)
        try:
            app.crawler.fetch(url)
            saved += 1
            print(f"[{saved}/{max_pages}] SAVED {url}", flush=True)
        except Exception as error:
            failed += 1
            print(f"SKIP {url}: {error}", flush=True)
            continue
        if depth >= max_depth:
            continue
        for link in links_from(url):
            if link not in visited:
                queue.append((link, depth + 1))
    return saved, failed


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Bounded recursive research crawler for AI Hub"
    )
    parser.add_argument("urls", nargs="+")
    parser.add_argument("--max-pages", type=int, default=25)
    parser.add_argument("--max-depth", type=int, default=2)
    args = parser.parse_args()
    app = AIHubApplication(ROOT)
    try:
        saved, failed = crawl(
            app,
            args.urls,
            max(1, min(args.max_pages, 250)),
            max(0, min(args.max_depth, 5)),
        )
        print(f"DONE saved={saved} failed={failed}")
    finally:
        app.stop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
