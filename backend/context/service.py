from __future__ import annotations

import hashlib
import re
from collections import defaultdict

from .models import ContextGraph, Constraint, Provenance, Requirement

_REQUIREMENT = re.compile(r"\b(must|required|shall|need to|needs to|should)\b", re.I)
_CONSTRAINT = re.compile(r"\b(must not|cannot|do not|never|only|prohibited|forbidden)\b", re.I)
_PRIORITY = re.compile(r"\b(critical|urgent|high[- ]priority)\b", re.I)


def analyze_sources(graph: ContextGraph, documents: dict[str, str]) -> ContextGraph:
    requirements: list[Requirement] = [
        item
        for item in graph.requirements
        if not _has_provenance_source(item.provenance, documents)
    ]
    constraints: list[Constraint] = [
        item
        for item in graph.constraints
        if not _has_provenance_source(item.provenance, documents)
    ]
    seen_requirements = {_normalize(item.statement) for item in requirements}
    seen_constraints = {_normalize(item.statement) for item in constraints}

    for source in graph.sources:
        text = documents.get(source.id, "")
        if not text.strip():
            continue
        lines = [line.strip(" -•\t") for line in text.splitlines() if line.strip()]

        for index, line in enumerate(lines):
            provenance = [
                Provenance(
                    source_id=source.id,
                    locator=f"line:{index + 1}",
                    quote=line[:280],
                    confidence=0.72,
                )
            ]

            if _REQUIREMENT.search(line):
                key = _normalize(line)
                if key not in seen_requirements:
                    seen_requirements.add(key)
                    priority = "high" if _PRIORITY.search(line) else "medium"
                    requirements.append(
                        Requirement(
                            id=_stable_id("req", source.id, line),
                            statement=line,
                            priority=priority,
                            provenance=provenance,
                        )
                    )

            if _CONSTRAINT.search(line):
                key = _normalize(line)
                if key not in seen_constraints:
                    seen_constraints.add(key)
                    constraints.append(
                        Constraint(
                            id=_stable_id("con", source.id, line),
                            statement=line,
                            severity="blocking",
                            provenance=provenance,
                        )
                    )

    return graph.model_copy(
        update={
            "requirements": requirements,
            "constraints": constraints,
        }
    )


def _has_provenance_source(provenance: list[Provenance], documents: dict[str, str]) -> bool:
    return any(item.source_id in documents for item in provenance)

def _normalize(text: str) -> str:
    return " ".join(text.lower().split())


def _stable_id(prefix: str, source_id: str, text: str) -> str:
    digest = hashlib.sha1(
        f"{source_id}:{_normalize(text)}".encode("utf-8")
    ).hexdigest()[:10]
    return f"{prefix}_{digest}"
