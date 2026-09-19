from __future__ import annotations

import html
import os
import re
from html.parser import HTMLParser
from typing import Any
from urllib.parse import quote_plus, urlparse
from urllib.request import Request, urlopen
import json


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []

    def handle_data(self, data: str) -> None:
        value = " ".join(data.split())
        if value:
            self.parts.append(value)

    def text(self) -> str:
        return " ".join(self.parts)


def _http(url: str, *, headers: dict[str, str] | None = None, method: str = "GET", body: bytes | None = None) -> bytes:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        raise ValueError("only http and https URLs are supported")
    request = Request(
        url,
        headers={"User-Agent": "Specloom/0.1", **(headers or {})},
        method=method,
        data=body,
    )
    with urlopen(request, timeout=15) as response:
        return response.read(512_000)


def live_url_fetch(payload: dict[str, Any]) -> dict[str, Any]:
    url = str(payload.get("url", "")).strip()
    if not url:
        raise ValueError("url_fetch requires a url")

    raw = _http(url)
    content_type = str(payload.get("content_type", "text"))
    if "html" in content_type or b"<html" in raw[:512].lower():
        parser = _TextExtractor()
        parser.feed(raw.decode("utf-8", errors="replace"))
        text = parser.text()
    else:
        text = raw.decode("utf-8", errors="replace")

    return {
        "tool": "url_fetch",
        "status": "ok",
        "url": url,
        "content": text[:50_000],
    }


def live_web_search(payload: dict[str, Any]) -> dict[str, Any]:
    query = str(payload.get("query", "")).strip()
    if not query:
        raise ValueError("web_search requires a query")

    url = f"https://html.duckduckgo.com/html/?q={quote_plus(query)}"
    raw = _http(url)
    page = raw.decode("utf-8", errors="replace")
    results: list[dict[str, str]] = []

    pattern = re.compile(
        r'<a[^>]*class="result__a"[^>]*href="([^"]+)"[^>]*>(.*?)</a>',
        re.I | re.S,
    )
    for href, title in pattern.findall(page):
        clean_title = html.unescape(re.sub(r"<[^>]+>", "", title)).strip()
        if not clean_title:
            continue
        results.append({"title": clean_title, "url": html.unescape(href)})
        if len(results) >= 5:
            break

    return {"tool": "web_search", "status": "ok", "query": query, "results": results}


def live_github_create_issue(payload: dict[str, Any]) -> dict[str, Any]:
    token = os.getenv("SPECL00M_GITHUB_TOKEN")
    repository = str(payload.get("repository") or os.getenv("SPECL00M_GITHUB_REPOSITORY", "")).strip()
    title = str(payload.get("title") or "Generated issue").strip()
    body = str(payload.get("body") or "").strip()

    if not token:
        raise RuntimeError("SPECL00M_GITHUB_TOKEN is required for live GitHub writes")
    if not re.fullmatch(r"[^/\\s]+/[^/\\s]+", repository):
        raise ValueError("GitHub repository must look like owner/name")

    endpoint = f"https://api.github.com/repos/{repository}/issues"
    raw = _http(
        endpoint,
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "X-GitHub-Api-Version": "2022-11-28",
            "Content-Type": "application/json",
        },
        method="POST",
        body=json.dumps({"title": title, "body": body}).encode("utf-8"),
    )
    response = json.loads(raw.decode("utf-8"))
    return {
        "tool": "github.create_issue",
        "status": "created",
        "issue_number": response.get("number"),
        "url": response.get("html_url"),
        "title": response.get("title", title),
    }
