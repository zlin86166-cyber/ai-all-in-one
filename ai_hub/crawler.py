from __future__ import annotations

import html
import re
import urllib.error
import urllib.parse
import urllib.request
import urllib.robotparser
from html.parser import HTMLParser
from typing import Any

from .config import Settings
from .db import Database


USER_AGENT = "AIHubLocalResearch/0.1 (+local-user-agent)"


class TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.title_parts: list[str] = []
        self._ignored = 0
        self._in_title = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"script", "style", "svg", "noscript"}:
            self._ignored += 1
        if tag == "title":
            self._in_title = True
        if tag in {"p", "div", "article", "section", "li", "h1", "h2", "h3", "br"}:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style", "svg", "noscript"} and self._ignored:
            self._ignored -= 1
        if tag == "title":
            self._in_title = False

    def handle_data(self, data: str) -> None:
        if self._ignored:
            return
        if self._in_title:
            self.title_parts.append(data)
        self.parts.append(data)

    def result(self) -> tuple[str, str]:
        title = " ".join(" ".join(self.title_parts).split())
        text = html.unescape("\n".join(self.parts))
        text = re.sub(r"[ \t]+", " ", text)
        text = re.sub(r"\n{3,}", "\n\n", text).strip()
        return title, text


class ResearchCrawler:
    def __init__(self, database: Database, settings: Settings):
        self.database = database
        self.settings = settings

    def _allowed(self, url: str) -> bool:
        allowlist = self.settings.get("crawler_allowlist", [])
        if not allowlist:
            return True
        host = (urllib.parse.urlparse(url).hostname or "").lower()
        return any(host == item.lower() or host.endswith("." + item.lower()) for item in allowlist)

    def fetch(self, url: str) -> dict[str, Any]:
        parsed = urllib.parse.urlparse(url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise ValueError("只支援有效的 HTTP/HTTPS 網址。")
        if not self._allowed(url):
            raise PermissionError("此網域不在自動研究允許清單。")
        robots_url = f"{parsed.scheme}://{parsed.netloc}/robots.txt"
        robot = urllib.robotparser.RobotFileParser()
        robot.set_url(robots_url)
        try:
            robot.read()
            if not robot.can_fetch(USER_AGENT, url):
                raise PermissionError("網站 robots.txt 不允許擷取此頁面。")
        except urllib.error.URLError:
            pass
        request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "text/html,text/plain,application/json"})
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                content_type = response.headers.get_content_type()
                raw = response.read(2_000_001)
                if len(raw) > 2_000_000:
                    raise ValueError("頁面超過 2 MB 擷取上限。")
                charset = response.headers.get_content_charset() or "utf-8"
        except urllib.error.URLError as error:
            raise ConnectionError(f"無法擷取網址：{error}") from error
        decoded = raw.decode(charset, errors="replace")
        if content_type == "text/html":
            parser = TextExtractor()
            parser.feed(decoded)
            title, text = parser.result()
        else:
            title, text = parsed.path.rsplit("/", 1)[-1] or parsed.hostname, decoded
        if not text.strip():
            raise ValueError("頁面沒有可用文字內容。")
        return self.database.save_research_document(
            url=url,
            title=title or parsed.hostname,
            text=text[:500_000],
            metadata={"content_type": content_type, "characters": len(text)},
        )
