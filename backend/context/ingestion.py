from __future__ import annotations

import hashlib
import re
import ipaddress
import socket
from urllib.parse import urlparse, urljoin
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
    source = Source(id=source_id, kind="text", name=name, content_hash=_hash_text(content))
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
