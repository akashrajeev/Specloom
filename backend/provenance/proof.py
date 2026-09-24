"""Proof view: link each line of an agent's answer to the exact quote on the page it came from.

Deterministic (no extra model call): every number in a line must appear near the matched spot on
a fetched page, plus some of its key words. Lines with no match are flagged, so a made-up value
shows up as "no quote found" instead of passing silently.
"""
from __future__ import annotations

import re
from typing import Any
from urllib.parse import quote as urlquote

_NUM = re.compile(r"[£$€₹]?\d[\d,]*(?:\.\d+)?")
_WORD = re.compile(r"[a-zA-Z][a-zA-Z'-]{3,}")
_URL = re.compile(r"https?://[^\s)\]】|>]+")
_STOP = {
    "this", "that", "with", "from", "have", "were", "they", "their", "there", "which", "about", "would",
    "price", "prices", "title", "availability", "source", "sources", "http", "https", "www", "html", "index",
}
# Lines that only describe the answer itself ("Candidate list", "These ten entries ...") carry no
# checkable claim. Without a number or a link they are skipped instead of flagged.
_META = re.compile(r"\b(candidates?|entries|listed|the following|shown below|see below|as above|evidence|summary of results)\b", re.I)
_SOURCES_HEADING = re.compile(r"(sources?|evidence|references|citations)\s*:?", re.I)
_WINDOW = 220
_MAX_LINES = 40


def _clean(line: str) -> str:
    line = _URL.sub(" ", line)
    line = re.sub(r"【[^】]*】|\[\d+\]|\*\*|__|`|#+ ", " ", line)
    line = line.replace("|", " ").strip(" -*•\t")
    return re.sub(r"\s+", " ", line).strip()


def answer_lines(text: str) -> list[tuple[str, str | None]]:
    """(clean line, cited url) for lines worth proving; skips headings, table headers and separators."""
    lines: list[tuple[str, str | None]] = []
    rows = [row for row in text.splitlines() if row.strip()]
    table_header_done = False
    in_sources = False
    for row in rows:
        stripped = row.strip()
        if re.fullmatch(r"\|?[\s:|-]+\|?", stripped):
            table_header_done = True
            continue
        if stripped.startswith("|") and not table_header_done:
            continue  # header row
        if not stripped.startswith("|"):
            table_header_done = False
        urls = _URL.findall(row)
        cleaned = _clean(row)
        if _SOURCES_HEADING.fullmatch(cleaned.strip("*_ ")):
            in_sources = True  # "Sources" / "Evidence" lists describe citations, not claims
            continue
        if not _NUM.search(cleaned) and re.match(r"(sources?|evidence|references|citations)\s*:", cleaned.strip("*_ "), re.I):
            continue  # inline "Sources: ..." citation line
        if in_sources and not stripped.startswith("|") and not _NUM.search(cleaned):
            continue
        if cleaned.endswith(":") and not urls:
            continue  # section label
        if not urls and not _NUM.search(cleaned) and _META.search(cleaned):
            continue  # describes the answer, claims nothing checkable
        if cleaned and (_NUM.search(cleaned) or len(_keywords(cleaned)) >= 3):
            lines.append((cleaned, urls[0].rstrip(".,;:") if urls else None))
    return lines[:_MAX_LINES]


def _keywords(line: str) -> list[str]:
    return [w.lower() for w in _WORD.findall(line) if w.lower() not in _STOP]


def _numbers(line: str) -> list[str]:
    return [n.replace(",", "").rstrip(".") for n in _NUM.findall(line)]


def _snippet(text: str, center: int) -> tuple[str, str]:
    start = max(0, center - 70)
    end = min(len(text), center + 150)
    while start > 0 and text[start - 1] not in " \n":
        start -= 1
    while end < len(text) and text[end] not in " \n":
        end += 1
    quote = text[start:end].strip()
    words = text[center:].split()
    fragment = " ".join(words[:5])
    return quote, fragment


def prove_line(line: str, cited: str | None, pages: dict[str, str]) -> dict[str, Any]:
    numbers = _numbers(line)
    words = list(dict.fromkeys(_keywords(line)))
    candidates = {cited: pages[cited]} if cited in pages else pages
    best: dict[str, Any] = {"text": line, "status": "not_found", "source": cited, "quote": None, "link": cited, "score": 0.0, "missing": numbers}
    for url, page in candidates.items():
        if not page or page.startswith("FETCH FAILED"):
            continue
        flat = page.replace(",", "")
        lower = flat.lower()
        anchors = [m.start() for n in numbers for m in re.finditer(re.escape(n.lower()), lower)]
        if not anchors:
            anchors = [m.start() for w in words[:4] for m in re.finditer(re.escape(w), lower)]
        for pos in anchors[:50]:
            window = lower[max(0, pos - _WINDOW): pos + _WINDOW]
            num_hit = sum(1 for n in numbers if n.lower() in window)
            word_hit = sum(1 for w in words if w in window)
            num_score = num_hit / len(numbers) if numbers else 1.0
            word_score = word_hit / len(words) if words else 1.0
            score = 0.7 * num_score + 0.3 * word_score if numbers else word_score
            if score > best["score"]:
                if numbers:
                    status = "supported" if num_score == 1 and (word_score >= 0.3 or not words) else "partial"
                else:
                    status = "supported" if word_score >= 0.6 else "partial" if word_score >= 0.3 else "not_found"
                quote, fragment = _snippet(flat, pos)
                best = {
                    "text": line,
                    "status": status,
                    "source": url,
                    "quote": quote,
                    "link": f"{url}#:~:text={urlquote(fragment)}" if fragment else url,
                    "score": round(score, 2),
                    "missing": [n for n in numbers if n.lower() not in window],
                }
    if best["status"] == "not_found":
        best.update({"quote": None, "link": best["source"]})
    return best


def build_proof(text: str, pages: dict[str, str]) -> dict[str, Any] | None:
    if not pages or not text:
        return None
    lines = [prove_line(line, cited, pages) for line, cited in answer_lines(text)]
    if not lines:
        return None
    return {
        "lines": lines,
        "supported": sum(1 for item in lines if item["status"] == "supported"),
        "total": len(lines),
        "pages": list(pages),
    }


def output_text(output: Any) -> str:
    if isinstance(output, str):
        return output
    if isinstance(output, list):
        return "\n".join(str(item.get("text", "")) if isinstance(item, dict) else str(item) for item in output)
    return str(output or "")
