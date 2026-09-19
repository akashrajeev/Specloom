from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable

from backend.context.models import ContextGraph, Constraint, Requirement


@dataclass(frozen=True)
class Gap:
    id: str
    severity: str
    category: str
    question: str
    related_requirement: str | None = None


_ACTION_PATTERN = re.compile(
    r"\b(create|delete|send|publish|deploy|modify|update|write|post|execute|transfer)\b",
    re.I,
)


def detect_gaps(goal: str, context: ContextGraph) -> list[Gap]:
    gaps: list[Gap] = []

    if len(goal.strip()) < 20:
        gaps.append(
            Gap(
                id="goal-too-short",
                severity="blocking",
                category="goal",
                question="What concrete outcome should the system produce?",
            )
        )

    if _ACTION_PATTERN.search(goal) and not context.constraints:
        gaps.append(
            Gap(
                id="missing-write-policy",
                severity="blocking",
                category="safety",
                question="Which actions are allowed, and which require human approval?",
            )
        )

    for requirement in context.requirements:
        if _contains_ambiguous_term(requirement.statement):
            gaps.append(
                Gap(
                    id=f"ambiguous-{requirement.id}",
                    severity="blocking",
                    category="ambiguity",
                    question=f"How should Specloom interpret: “{requirement.statement}”?",
                    related_requirement=requirement.id,
                )
            )

    if not context.tools:
        gaps.append(
            Gap(
                id="no-tools",
                severity="warning",
                category="capability",
                question="Which external capabilities should the generated system be allowed to use?",
            )
        )

    if any(_requires_evidence(item) for item in context.requirements) and not context.examples:
        gaps.append(
            Gap(
                id="missing-examples",
                severity="warning",
                category="evaluation",
                question="Can you provide one or two examples of acceptable output?",
            )
        )

    return _deduplicate(gaps)


def _contains_ambiguous_term(text: str) -> bool:
    lower = text.lower()
    return any(term in lower for term in ("relevant", "appropriate", "important", "high quality"))


def _requires_evidence(requirement: Requirement) -> bool:
    return any(term in requirement.statement.lower() for term in ("verify", "accurate", "correct", "relevant"))


def _deduplicate(gaps: Iterable[Gap]) -> list[Gap]:
    seen: set[str] = set()
    result: list[Gap] = []
    for gap in gaps:
        if gap.id not in seen:
            seen.add(gap.id)
            result.append(gap)
    return result
