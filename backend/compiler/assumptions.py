from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from backend.context.models import ContextGraph, Source

if TYPE_CHECKING:
    from backend.context.gaps import Gap


@dataclass(frozen=True)
class AssumptionDecision:
    gap_id: str
    assumption: str
    rationale: str
    safe: bool = True


class AutonomousAssumptionResolver:
    """Resolve only low-risk semantic ambiguity; never infer authorization."""

    def resolve(
        self,
        goal: str,
        context: ContextGraph,
        gaps: list[Any],
    ) -> tuple[ContextGraph, list[AssumptionDecision]]:
        decisions: list[AssumptionDecision] = []

        for gap in gaps:
            if gap.category != "ambiguity":
                continue

            assumption = self._for_gap(goal, gap)
            if assumption is None:
                continue

            decisions.append(assumption)

        if not decisions:
            return context, decisions

        source_id = (
            "src_assumptions_"
            + hashlib.sha1(goal.strip().lower().encode("utf-8")).hexdigest()[:12]
        )
        sources = list(context.sources)
        if not any(item.id == source_id for item in sources):
            sources.append(
                Source(
                    id=source_id,
                    kind="text",
                    name="Autonomous Assumptions",
                    content_hash=hashlib.sha256(
                        "|".join(item.assumption for item in decisions).encode("utf-8")
                    ).hexdigest(),
                )
            )

        assumptions = list(context.assumptions)
        known_gap_ids = {
            str(item.get("gap_id"))
            for item in assumptions
            if isinstance(item, dict)
        }
        for decision in decisions:
            if decision.gap_id in known_gap_ids:
                continue
            assumptions.append(
                {
                    "gap_id": decision.gap_id,
                    "assumption": decision.assumption,
                    "rationale": decision.rationale,
                    "source_id": source_id,
                    "safe": decision.safe,
                }
            )

        return context.model_copy(
            update={
                "sources": sources,
                "assumptions": assumptions,
            }
        ), decisions

    @staticmethod
    def _for_gap(goal: str, gap: Any) -> AssumptionDecision | None:
        if gap.id == "ambiguous-goal":
            return AssumptionDecision(
                gap_id=gap.id,
                assumption=(
                    "Interpret relevance/quality/suitability using explicit project context, "
                    "stated requirements, and deterministic task semantics; when evidence is "
                    "insufficient, preserve the uncertainty instead of inventing a fact."
                ),
                rationale=(
                    "This is a semantic default with no authorization or external side effect."
                ),
            )

        if gap.id.startswith("ambiguous-"):
            return AssumptionDecision(
                gap_id=gap.id,
                assumption=(
                    "Interpret the requirement conservatively using available context and "
                    "explicit examples; do not invent provider behavior, credentials, or "
                    "side-effect permissions."
                ),
                rationale=(
                    "The default narrows behavior rather than granting new authority."
                ),
            )

        return None


def unresolved_safe_ambiguity_ids(context: ContextGraph) -> set[str]:
    return {
        str(item.get("gap_id"))
        for item in context.assumptions
        if isinstance(item, dict) and item.get("safe", False)
    }
