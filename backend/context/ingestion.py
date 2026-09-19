from __future__ import annotations

import base64
import hashlib
import ipaddress
import re
import socket
from urllib.parse import urljoin, urlparse
from dataclasses import dataclass
from pathlib import Path

import httpx

from .models import Source, SourceKind


@dataclass(frozen=True)
class IngestedSource:
    source: Source
    text: str


class IngestionError(ValueError):
    pass


def _hash_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def ingest_text(name: str, content: str) -> IngestedSource:
    if not content.strip():
        raise IngestionError("text content cannot be empty")
    source_id = f"src_{_hash_text(name + content)[:12]}"
    source = Source(
        id=source_id,
        kind="text",
        name=name,
        content_hash=_hash_text(content),
    )
    return IngestedSource(source=source, text=content)


def ingest_pdf(path: str | Path, name: str | None = None) -> IngestedSource:
    try:
        import fitz
    except ImportError as exc:
        raise IngestionError("PyMuPDF is required for PDF ingestion") from exc

    pdf_path = Path(path)
    if not pdf_path.exists():
        raise IngestionError(f"PDF does not exist: {pdf_path}")

    document = fitz.open(pdf_path)
    pages: list[str] = []
    for index, page in enumerate(document):
        text = page.get_text("text").strip()
        if text:
            pages.append(f"[page {index + 1}]\n{text}")

    content = "\n\n".join(pages)
    if not content:
        raise IngestionError("PDF contains no extractable text")

    display_name = name or pdf_path.name
    source_id = f"src_{_hash_text(str(pdf_path.resolve()))[:12]}"
    source = Source(
        id=source_id,
        kind="pdf",
        name=display_name,
        uri=str(pdf_path),
        content_hash=_hash_text(content),
    )
    return IngestedSource(source=source, text=content)


async def ingest_url(url: str, name: str | None = None, timeout: float = 15.0) -> IngestedSource:
    current_url = _validate_public_url(url)

    async with httpx.AsyncClient(follow_redirects=False, timeout=timeout) as client:
        response = None
        for _ in range(5):
            response = await client.get(current_url)
            if response.is_redirect:
                location = response.headers.get("location")
                if not location:
                    raise IngestionError("URL redirect did not include a location")
                current_url = _validate_public_url(urljoin(current_url, location))
                continue
            response.raise_for_status()
            break
        else:
            raise IngestionError("too many redirects while ingesting URL")

    assert response is not None
    content_type = response.headers.get("content-type", "")
    text = response.text
    if "text" not in content_type and not text.strip():
        raise IngestionError("URL did not return readable text")

    source_id = f"src_{_hash_text(url)[:12]}"
    source = Source(
        id=source_id,
        kind="url",
        name=name or url,
        uri=url,
        content_hash=_hash_text(text),
    )
    return IngestedSource(source=source, text=text)


async def ingest_github(
    repository_url: str,
    name: str | None = None,
    *,
    max_files: int = 20,
    max_total_chars: int = 250_000,
    timeout: float = 15.0,
) -> IngestedSource:
    parsed = urlparse(repository_url)
    if parsed.scheme != "https" or parsed.hostname != "github.com":
        raise IngestionError("GitHub context must use an https://github.com/owner/repository URL")

    parts = [part for part in parsed.path.split("/") if part]
    if len(parts) < 2:
        raise IngestionError("GitHub URL must include owner and repository")

    owner, repo = parts[0], parts[1].removesuffix(".git")
    if not re.fullmatch(r"[A-Za-z0-9_.-]+", owner) or not re.fullmatch(r"[A-Za-z0-9_.-]+", repo):
        raise IngestionError("invalid GitHub repository name")

    headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "Specloom/0.1",
    }
    token = __import__("os").getenv("SPECL00M_GITHUB_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"

    async with httpx.AsyncClient(timeout=timeout) as client:
        repo_response = await client.get(f"https://api.github.com/repos/{owner}/{repo}", headers=headers)
        repo_response.raise_for_status()
        repo_data = repo_response.json()
        default_branch = str(repo_data.get("default_branch") or "main")

        tree_response = await client.get(
            f"https://api.github.com/repos/{owner}/{repo}/git/trees/{default_branch}",
            params={"recursive": "1"},
            headers=headers,
        )
        tree_response.raise_for_status()
        tree = tree_response.json()
        entries = tree.get("tree", [])

        candidates = [
            item for item in entries
            if item.get("type") == "blob"
            and isinstance(item.get("path"), str)
            and not any(part in str(item["path"]).split("/") for part in (".git", "node_modules", "dist", "build", ".next"))
            and Path(str(item["path"])).suffix.lower() in {
                ".md", ".txt", ".py", ".js", ".jsx", ".ts", ".tsx",
                ".json", ".yaml", ".yml", ".toml", ".sql", ".java",
                ".go", ".rs", ".env.example",
            }
        ]

        priority_names = {"readme.md", "pyproject.toml", "package.json", "requirements.txt", "dockerfile"}
        candidates.sort(
            key=lambda item: (
                0 if str(item["path"]).lower() in priority_names else 1,
                len(str(item["path"])),
                str(item["path"]).lower(),
            )
        )

        sections: list[str] = []
        total = 0
        for item in candidates[: max(1, min(max_files, 50))]:
            if total >= max_total_chars:
                break
            sha = str(item.get("sha", ""))
            if not sha:
                continue
            blob_response = await client.get(
                f"https://api.github.com/repos/{owner}/{repo}/git/blobs/{sha}",
                headers=headers,
            )
            if blob_response.status_code != 200:
                continue
            blob = blob_response.json()
            if blob.get("encoding") != "base64":
                continue
            try:
                text = base64.b64decode(str(blob.get("content", ""))).decode("utf-8", errors="replace")
            except (ValueError, UnicodeError):
                continue
            remaining = max_total_chars - total
            text = text[:remaining]
            if not text.strip():
                continue
            sections.append(f"===== {item['path']} =====\n{text}")
            total += len(text)

    content = (
        f"Repository: {owner}/{repo}\n"
        f"Default branch: {default_branch}\n"
        + "\n\n".join(sections)
    )
    if not sections:
        raise IngestionError("GitHub repository contained no readable source files")

    source_id = f"src_{_hash_text(f'github:{owner}/{repo}')[:12]}"
    source = Source(
        id=source_id,
        kind="github",
        name=name or f"{owner}/{repo}",
        uri=f"https://github.com/{owner}/{repo}",
        content_hash=_hash_text(content),
    )
    return IngestedSource(source=source, text=content)


def _validate_public_url(url: str) -> str:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise IngestionError("only public http(s) URLs are supported")

    try:
        addresses = {info[4][0] for info in socket.getaddrinfo(parsed.hostname, None)}
    except socket.gaierror as exc:
        raise IngestionError(f"cannot resolve hostname: {parsed.hostname}") from exc

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
            raise IngestionError("URL resolves to a non-public network address")

    return url
