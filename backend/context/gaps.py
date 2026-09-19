from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable

from backend.context.models import ContextGraph, Requirement


@dataclass(frozen=True)
class Gap:
    id: str
    severity: str
    category: str
    question: str
    related_requirement: str | None = None


_AMBIGUOUS_GOAL = re.compile(
    r"\b(relevant|appropriate|important|high[- ]quality|best|suitable)\b",
    re.I,
)
_ACTION_PATTERN = re.compile(
    r"\b(delete|send|publish|deploy|transfer|create|modify|update|commit|upload|post|purchase|book|notify|message)\b",
    re.I,
)

# Capability families are deliberately small and conservative. They do not
# invent integrations; they only recognize when the goal explicitly asks for
# an external capability that the current registry/MCP catalog may not provide.
_CAPABILITY_PATTERNS = {
    "email": re.compile(r"\b(email|e-mail|smtp|mailbox|inbox)\b", re.I),
    "slack": re.compile(r"\bslack\b", re.I),
    "calendar": re.compile(r"\b(calendar|meeting|schedule a meeting|calendar event)\b", re.I),
    "database": re.compile(r"\b(database|postgres(?:ql)?|mysql|sqlite|sql query|query the db)\b", re.I),
    "jira": re.compile(r"\bjira\b", re.I),
    "linear": re.compile(r"\blinear\b", re.I),
    "sms": re.compile(r"\b(sms|text message|twilio)\b", re.I),
    "storage": re.compile(r"\b(s3|bucket|object storage|upload file)\b", re.I),
    "payments": re.compile(r"\b(payment|stripe|checkout|charge|refund)\b", re.I),
}


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
                id="missing-action-policy",
                severity="blocking",
                category="safety",
                question="Which external actions are allowed, and which require human approval? What must never happen automatically?",
            )
        )

    if _AMBIGUOUS_GOAL.search(goal) and not context.requirements:
        gaps.append(
            Gap(
                id="ambiguous-goal",
                severity="blocking",
                category="ambiguity",
                question="What concrete rules should define relevance, quality, suitability, or acceptance for the requested result?",
            )
        )

    gaps.extend(_detect_missing_capabilities(goal, context))

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


def _detect_missing_capabilities(goal: str, context: ContextGraph) -> list[Gap]:
    text = goal.strip()
    available = {
        capability.lower()
        for tool in context.tools
        for capability in tool.capabilities
    }

    gaps: list[Gap] = []
    for capability, pattern in _CAPABILITY_PATTERNS.items():
        if not pattern.search(text):
            continue

        candidates = {capability, capability.rstrip("s")}
        if candidates & available:
            continue

        gaps.append(
            Gap(
                id=f"missing-capability-{capability}",
                severity="blocking",
                category="capability",
                question=(
                    f"This goal explicitly requires {capability} capability, but no configured "
                    f"tool currently provides it. Configure a trusted tool/MCP server for {capability} "
                    "or change the goal."
                ),
            )
        )
    return gaps


def _contains_ambiguous_term(text: str) -> bool:
    lower = text.lower()
    return any(
        term in lower
        for term in ("relevant", "appropriate", "important", "high quality", "best", "suitable")
    )


def _requires_evidence(requirement: Requirement) -> bool:
    return any(
        term in requirement.statement.lower()
        for term in ("verify", "accurate", "correct", "relevant", "best", "suitable")
    )


def _deduplicate(gaps: Iterable[Gap]) -> list[Gap]:
    seen: set[str] = set()
    result: list[Gap] = []
    for gap in gaps:
        if gap.id not in seen:
            seen.add(gap.id)
            result.append(gap)
    return result
