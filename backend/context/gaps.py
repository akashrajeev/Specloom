from __future__ import annotations

from dataclasses import dataclass

from .models import ContextGraph


@dataclass(frozen=True)
class ContextGap:
    id: str
    severity: str
    title: str
    question: str


VAGUE_TERMS = {
    "relevant": "What makes an item relevant?",
    "important": "What makes an item important?",
    "appropriate": "What makes an action appropriate?",
    "high priority": "How is high priority determined?",
}


def detect_gaps(goal: str, context: ContextGraph) -> list[ContextGap]:
    text = f"{goal.lower()} {' '.join(item.statement.lower() for item in context.requirements)}"
    gaps: list[ContextGap] = []

    for index, (term, question) in enumerate(VAGUE_TERMS.items()):
        if term in text and not context.examples and not context.constraints:
            gaps.append(
                ContextGap(
                    id=f"gap_{index + 1}",
                    severity="blocking",
                    title=f"Undefined concept: {term}",
                    question=question,
                )
            )

    if not context.tools:
        gaps.append(
            ContextGap(
                id="gap_tools",
                severity="warning",
                title="No tools discovered",
                question="Which external capabilities should the generated system be allowed to use?",
            )
        )

    return gaps
