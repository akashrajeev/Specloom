from __future__ import annotations

import re

from .models import ContextGraph, Constraint, Provenance, Requirement

STOP_WORDS = {"the","and","with","that","this","from","into","your","have","will","should"}

def analyze_sources(graph: ContextGraph, documents: dict[str, str]) -> ContextGraph:
    requirements: list[Requirement] = []
    constraints: list[Constraint] = []

    for source in graph.sources:
        text = documents.get(source.id, "")
        lines = [line.strip(" -•\t") for line in text.splitlines() if line.strip()]
        for index, line in enumerate(lines):
            lower = line.lower()
            provenance = [Provenance(source_id=source.id, locator=f"line:{index + 1}", quote=line[:280], confidence=0.55)]

            if re.search(r"\b(must|required|shall|need to|needs to)\b", lower):
                requirements.append(
                    Requirement(
                        id=f"req_{source.id}_{index + 1}",
                        statement=line,
                        priority="high" if "must" in lower or "required" in lower else "medium",
                        provenance=provenance,
                    )
                )

            if re.search(r"\b(must not|cannot|do not|never|only)\b", lower):
                constraints.append(
                    Constraint(
                        id=f"con_{source.id}_{index + 1}",
                        statement=line,
                        severity="blocking",
                        provenance=provenance,
                    )
                )

    return graph.model_copy(update={"requirements": requirements, "constraints": constraints})
