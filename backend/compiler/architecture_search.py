from __future__ import annotations

from dataclasses import dataclass, field

from backend.agents.architect import Architect, BuildRequest
from backend.agents.reviewer import ArchitectureReview
from backend.capabilities.bindings import validate_capability_bindings
from backend.context.models import ContextGraph
from backend.workflow.models import WorkflowIR
from backend.workflow.validator import (
    validate_architecture_coverage,
    validate_workflow,
)


@dataclass(frozen=True)
class ArchitectureCandidate:
    index: int
    workflow: WorkflowIR
    validation_errors: tuple[str, ...] = ()
    review: ArchitectureReview | None = None
    score: tuple[int, int, int] = (0, 0, 0)
    evidence: dict = field(default_factory=dict)


@dataclass(frozen=True)
class ArchitectureSearchResult:
    selected: ArchitectureCandidate
    candidates: tuple[ArchitectureCandidate, ...]


class ArchitectureHypothesisSearcher:
    """Generate bounded architecture hypotheses and select by hard proof signals."""

    def __init__(
        self,
        architect: Architect,
        *,
        candidate_count: int = 3,
    ) -> None:
        self.architect = architect
        self.candidate_count = max(1, min(candidate_count, 5))

    def search(
        self,
        *,
        request: BuildRequest,
        context: ContextGraph,
        reviewer=None,
    ) -> ArchitectureSearchResult:
        candidates: list[ArchitectureCandidate] = []

        for index in range(self.candidate_count):
            try:
                workflow = self.architect.build(request, context)
            except Exception as exc:
                candidates.append(
                    ArchitectureCandidate(
                        index=index,
                        workflow=None,  # type: ignore[arg-type]
                        validation_errors=(f"architecture synthesis failed: {exc}",),
                    )
                )
                continue

            errors = [
                *validate_workflow(workflow),
                *validate_architecture_coverage(workflow, context),
                *validate_capability_bindings(workflow, context),
            ]
            review = None
            review_errors: list[str] = []
            if not errors and reviewer is not None:
                review = reviewer.review(
                    goal=request.goal,
                    context=context,
                    workflow=workflow,
                )
                review_errors = [
                    item.message
                    for item in review.findings
                    if item.severity == "blocking"
                ]
                errors.extend(review_errors)

            coverage = self._coverage_score(workflow, context)
            warning_count = (
                sum(item.severity == "warning" for item in review.findings)
                if review is not None
                else 0
            )
            node_count = len(workflow.nodes) if workflow is not None else 10_000
            score = (
                0 if errors else 1,
                coverage - warning_count,
                -node_count,
            )

            candidates.append(
                ArchitectureCandidate(
                    index=index,
                    workflow=workflow,
                    validation_errors=tuple(errors),
                    review=review,
                    score=score,
                    evidence={
                        "coverage": coverage,
                        "warnings": warning_count,
                        "node_count": node_count,
                    },
                )
            )

        usable = [
            candidate
            for candidate in candidates
            if candidate.workflow is not None
        ]
        if not usable:
            raise ValueError("architecture search produced no usable hypothesis")

        selected = max(usable, key=lambda item: (item.score, -item.index))
        if selected.validation_errors:
            raise ValueError(
                "all architecture hypotheses were rejected: "
                + "; ".join(selected.validation_errors)
            )

        return ArchitectureSearchResult(
            selected=selected,
            candidates=tuple(candidates),
        )

    @staticmethod
    def _coverage_score(
        workflow: WorkflowIR,
        context: ContextGraph,
    ) -> int:
        requirement_refs = {
            str(ref)
            for node in workflow.nodes
            for ref in node.config.get("requirement_refs", [])
        }
        constraint_refs = {
            str(ref)
            for node in workflow.nodes
            for ref in node.config.get("constraint_refs", [])
        }
        covered_requirements = sum(
            item.id in requirement_refs
            for item in context.requirements
            if item.priority != "low"
        )
        covered_constraints = sum(
            item.id in constraint_refs
            for item in context.constraints
            if item.severity == "blocking"
        )
        bound_capabilities = sum(
            bool(node.config.get("tool_ref") or node.config.get("tools"))
            for node in workflow.nodes
            if node.type in {"tool", "agent"}
        )
        return covered_requirements + covered_constraints + bound_capabilities
