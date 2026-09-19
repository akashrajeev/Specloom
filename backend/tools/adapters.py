from __future__ import annotations

import html
import json
import os
import re
import ipaddress
import socket
from html.parser import HTMLParser
from typing import Any
from urllib.parse import quote_plus, quote, urlparse
from urllib.request import Request, urlopen


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


def _http(
    url: str,
    *,
    headers: dict[str, str] | None = None,
    method: str = "GET",
    body: bytes | None = None,
) -> bytes:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        raise ValueError("only http and https URLs are supported")
    hostname = parsed.hostname
    if not hostname:
        raise ValueError("URL must include a hostname")
    try:
        addresses = {info[4][0] for info in socket.getaddrinfo(hostname, None)}
    except socket.gaierror as exc:
        raise ValueError(f"cannot resolve hostname: {hostname}") from exc
    for address in addresses:
        ip = ipaddress.ip_address(address)
        if (
            ip.is_private
            or ip.is_loopback
            or ip.is_link_local
            or ip.is_multicast
            or ip.is_reserved
            or ip.is_unspecified
        ):
            raise ValueError("URL resolves to a non-public network address")
    request = Request(
        url,
        headers={"User-Agent": "Specloom/0.1", **(headers or {})},
        method=method,
        data=body,
    )
    with urlopen(request, timeout=15) as response:
        return response.read(512_000)


def _github_repository(value: Any) -> str:
    repository = str(value or os.getenv("SPECL00M_GITHUB_REPOSITORY", "")).strip()
    if not re.fullmatch(r"[^/\\s]+/[^/\\s]+", repository):
        raise ValueError("GitHub repository must look like owner/name")
    return repository


def _github_headers() -> dict[str, str]:
    headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    token = os.getenv("SPECL00M_GITHUB_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def _github_get(path: str, query: str = "") -> dict[str, Any]:
    url = f"https://api.github.com{path}"
    if query:
        url += f"?{query}"
    raw = _http(url, headers=_github_headers())
    value = json.loads(raw.decode("utf-8"))
    if not isinstance(value, dict):
        raise ValueError("GitHub API returned an unexpected response")
    return value


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


def live_github_get_repo(payload: dict[str, Any]) -> dict[str, Any]:
    repository = _github_repository(payload.get("repository"))
    data = _github_get(f"/repos/{repository}")
    return {
        "tool": "github.get_repo",
        "status": "ok",
        "repository": data.get("full_name", repository),
        "default_branch": data.get("default_branch"),
        "description": data.get("description"),
        "language": data.get("language"),
        "stars": data.get("stargazers_count"),
        "open_issues": data.get("open_issues_count"),
        "url": data.get("html_url"),
    }


def live_github_list_issues(payload: dict[str, Any]) -> dict[str, Any]:
    repository = _github_repository(payload.get("repository"))
    state = str(payload.get("state", "open")).strip().lower()
    if state not in {"open", "closed", "all"}:
        raise ValueError("issue state must be open, closed, or all")
    per_page = max(1, min(int(payload.get("per_page", 10)), 30))
    data = _github_get(
        f"/repos/{repository}/issues",
        f"state={quote(state)}&per_page={per_page}",
    )
    if not isinstance(data, list):
        raise ValueError("GitHub issue response was not a list")
    items = [
        {
            "number": item.get("number"),
            "title": item.get("title"),
            "state": item.get("state"),
            "url": item.get("html_url"),
            "labels": [label.get("name") for label in item.get("labels", [])],
        }
        for item in data
        if "pull_request" not in item
    ]
    return {"tool": "github.list_issues", "status": "ok", "repository": repository, "issues": items}


def live_github_search_code(payload: dict[str, Any]) -> dict[str, Any]:
    query = str(payload.get("query", "")).strip()
    if not query:
        raise ValueError("github.search_code requires a query")
    repository = str(payload.get("repository", "")).strip()
    qualified = f"{query} repo:{repository}" if repository else query
    data = _github_get("/search/code", f"q={quote(qualified)}&per_page=10")
    items = data.get("items", []) if isinstance(data, dict) else []
    return {
        "tool": "github.search_code",
        "status": "ok",
        "query": query,
        "repository": repository or None,
        "results": [
            {
                "name": item.get("name"),
                "path": item.get("path"),
                "url": item.get("html_url"),
                "repository": (item.get("repository") or {}).get("full_name"),
            }
            for item in items
        ],
    }


def live_github_create_issue(payload: dict[str, Any]) -> dict[str, Any]:
    token = os.getenv("SPECL00M_GITHUB_TOKEN")
    repository = _github_repository(payload.get("repository"))
    title = str(payload.get("title") or "Generated issue").strip()
    body = str(payload.get("body") or "").strip()

    if not token:
        raise RuntimeError("SPECL00M_GITHUB_TOKEN is required for live GitHub writes")

    endpoint = f"https://api.github.com/repos/{repository}/issues"
    raw = _http(
        endpoint,
        headers={
            **_github_headers(),
            "Authorization": f"Bearer {token}",
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
