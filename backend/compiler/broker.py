from __future__ import annotations

from dataclasses import dataclass

from backend.capabilities.models import CapabilitySpec
from backend.context.models import ContextGraph

from .models import CapabilityRequirement


@dataclass(frozen=True)
class CapabilityCandidate:
    capability_id: str
    score: float
    reason: str
    requires_provisioning: bool
    compatible: bool


@dataclass(frozen=True)
class CapabilityBindingPlan:
    requirement_id: str
    selected: CapabilityCandidate | None
    candidates: tuple[CapabilityCandidate, ...]
    needs_synthesis: bool


class CapabilityBroker:
    """Resolve capability requirements against configured and synthesized contracts."""

    def plan(
        self,
        requirements: list[CapabilityRequirement],
        context: ContextGraph,
    ) -> list[CapabilityBindingPlan]:
        return [
            self._plan_one(requirement, context)
            for requirement in requirements
            if requirement.required
        ]

    def _plan_one(
        self,
        requirement: CapabilityRequirement,
        context: ContextGraph,
    ) -> CapabilityBindingPlan:
        candidates: list[CapabilityCandidate] = []

        for capability in context.capabilities:
            if not self._family_matches(requirement.family, capability):
                continue

            access_ok = (
                requirement.access == "read"
                or capability.access == "write"
            )
            if not access_ok:
                continue

            score = 0.55
            reasons: list[str] = []

            if requirement.family.lower() in capability.id.lower():
                score += 0.20
                reasons.append("family appears in capability id")
            if any(
                requirement.family.lower() == tag.lower()
                or requirement.family.lower() in tag.lower()
                for tag in capability.tags
            ):
                score += 0.20
                reasons.append("family matches capability tag")
            if capability.kind == "configured_api":
                score += 0.05
                reasons.append("configured provider")
            elif capability.kind == "openapi":
                score += 0.08
                reasons.append("OpenAPI contract")
            elif capability.kind == "synthesized":
                reasons.append("compiler-generated contract")

            candidates.append(
                CapabilityCandidate(
                    capability_id=capability.id,
                    score=min(score, 1.0),
                    reason="; ".join(reasons) or "family match",
                    requires_provisioning=(
                        capability.kind == "synthesized"
                        or not bool(capability.base_url)
                    ),
                    compatible=True,
                )
            )

        candidates.sort(
            key=lambda item: (-item.score, item.capability_id)
        )
        selected = candidates[0] if candidates else None

        return CapabilityBindingPlan(
            requirement_id=requirement.id,
            selected=selected,
            candidates=tuple(candidates[:5]),
            needs_synthesis=selected is None and requirement.external,
        )

    @staticmethod
    def _family_matches(
        family: str,
        capability: CapabilitySpec,
    ) -> bool:
        needle = family.strip().lower()
        haystack = " ".join(
            [
                capability.id,
                capability.name,
                capability.description,
                *capability.tags,
            ]
        ).lower()
        return needle in haystack
