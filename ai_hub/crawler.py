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
from .security import validate_network_url

USER_AGENT = "AIHubLocalResearch/1.0 (+local-user-agent)"


class TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True); self.parts=[]; self.title_parts=[]; self._ignored=0; self._in_title=False
    def handle_starttag(self, tag, attrs):
        if tag in {"script","style","svg","noscript"}: self._ignored += 1
        if tag == "title": self._in_title=True
        if tag in {"p","div","article","section","li","h1","h2","h3","br"}: self.parts.append("\n")
    def handle_endtag(self, tag):
        if tag in {"script","style","svg","noscript"} and self._ignored: self._ignored -= 1
        if tag == "title": self._in_title=False
    def handle_data(self, data):
        if self._ignored: return
        if self._in_title: self.title_parts.append(data)
        self.parts.append(data)
    def result(self):
        title=" ".join(" ".join(self.title_parts).split()); text=html.unescape("\n".join(self.parts))
        text=re.sub(r"[ \t]+"," ",text); text=re.sub(r"\n{3,}","\n\n",text).strip(); return title,text


class SafeRedirectHandler(urllib.request.HTTPRedirectHandler):
    def __init__(self, allow_private: bool): super().__init__(); self.allow_private=allow_private
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        validate_network_url(newurl, allow_private=self.allow_private)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


class ResearchCrawler:
    def __init__(self, database: Database, settings: Settings): self.database=database; self.settings=settings
    def _allowed(self, url: str) -> bool:
        allowlist=self.settings.get("crawler_allowlist", [])
        if not allowlist: return True
        host=(urllib.parse.urlparse(url).hostname or "").lower()
        return any(host == item.lower() or host.endswith("."+item.lower()) for item in allowlist)
    def fetch(self, url: str) -> dict[str, Any]:
        allow_private=bool(self.settings.get("allow_private_research", False))
        parsed=validate_network_url(url, allow_private=allow_private)
        if not self._allowed(url): raise PermissionError("此網域不在自動研究允許清單。")
        robots_url=f"{parsed.scheme}://{parsed.netloc}/robots.txt"; robot=urllib.robotparser.RobotFileParser(); robot.set_url(robots_url)
        try:
            robot.read()
            if not robot.can_fetch(USER_AGENT, url): raise PermissionError("網站 robots.txt 不允許擷取此頁面。")
        except urllib.error.URLError: pass
        request=urllib.request.Request(url, headers={"User-Agent":USER_AGENT,"Accept":"text/html,text/plain,application/json"})
        opener=urllib.request.build_opener(SafeRedirectHandler(allow_private))
        try:
            with opener.open(request, timeout=30) as response:
                validate_network_url(response.geturl(), allow_private=allow_private)
                content_type=response.headers.get_content_type(); raw=response.read(2_000_001)
                if len(raw)>2_000_000: raise ValueError("頁面超過 2 MB 擷取上限。")
                charset=response.headers.get_content_charset() or "utf-8"
        except urllib.error.URLError as error: raise ConnectionError(f"無法擷取網址：{error}") from error
        decoded=raw.decode(charset, errors="replace")
        if content_type == "text/html": parser=TextExtractor(); parser.feed(decoded); title,text=parser.result()
        else: title,text=parsed.path.rsplit("/",1)[-1] or parsed.hostname,decoded
        if not text.strip(): raise ValueError("頁面沒有可用文字內容。")
        return self.database.save_research_document(url=response.geturl(), title=title or parsed.hostname,
            text=text[:500_000], metadata={"content_type":content_type,"characters":len(text)})
