from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol
import os

from backend.context.models import ContextGraph
from backend.workflow.models import WorkflowIR
from backend.workflow.validator import validate_workflow
from backend.agents.prompt import ArchitectPrompt


@dataclass(frozen=True)
class BuildRequest:
    goal: str
    project_id: str


class Architect(Protocol):
    def build(self, request: BuildRequest, context: ContextGraph) -> WorkflowIR:
        ...

    def revise(
        self,
        request: BuildRequest,
        context: ContextGraph,
        workflow: WorkflowIR,
        findings: list[dict],
    ) -> WorkflowIR:
        ...


_SEEDED_SOURCES = {"src_researchhunter_brief"}

_STOPWORDS = {
    "the", "and", "for", "with", "that", "this", "from", "into", "must", "should",
    "system", "systems", "shall", "will", "only", "before", "after", "each", "any",
    "all", "are", "not", "without", "when", "then", "than", "requested", "outcome",
    "satisfy", "build", "create", "using", "use", "node", "generated", "relevant",
}


def _terms(text: str) -> set[str]:
    import re

    words = re.findall(r"[a-z][a-z0-9]+", text.lower().replace("_", " "))
    terms = set()
    for word in words:
        if len(word) < 4 or word in _STOPWORDS:
            continue
        terms.add(word.rstrip("s") if len(word) > 4 else word)
    return terms


def _planner_source_id(goal: str) -> str:
    import hashlib

    return "src_planner_" + hashlib.sha256(goal.strip().encode("utf-8")).hexdigest()[:12]


def _relevant(item, node_terms: set[str], planner_source: str) -> bool:
    """Link a requirement/constraint to a node only when there is evidence it applies.

    Statements planned from the current goal and user-supplied context apply to the
    whole design. Statements planned for an older goal never apply. The seeded demo
    brief only applies where it shares vocabulary with the node, so unrelated
    requirements stay uncovered instead of passing by default.
    """
    sources = {str(ref.source_id) for ref in item.provenance}
    if planner_source in sources:
        return True
    if sources and all(source.startswith("src_planner_") for source in sources):
        return False
    if sources and sources <= _SEEDED_SOURCES:
        return bool(_terms(item.statement) & node_terms)
    return True


class ShowcaseArchitect:
    """Deterministic local architect retained as a test/demo fallback."""

    mode = "showcase"

    def build(self, request: BuildRequest, context: ContextGraph) -> WorkflowIR:
        from backend.workflow.templates import deterministic_goal_template

        workflow = deterministic_goal_template(
            goal=request.goal,
            context=context,
        )
        planner_source = _planner_source_id(request.goal)
        decomposition_steps = [
            str(item.get("id"))
            for item in context.problem_decomposition.get("steps", [])
            if isinstance(item, dict) and item.get("id")
        ]
        requirements = [item for item in context.requirements if item.priority != "low"]
        constraints = [item for item in context.constraints if item.severity == "blocking"]
        for node in workflow.nodes:
            node_terms = _terms(" ".join([
                node.id,
                node.name,
                str(node.description or ""),
                str(node.config.get("role", "")),
                " ".join(str(tool) for tool in node.config.get("tools", [])),
                str(node.config.get("tool", "")),
            ]))
            if node.type == "agent":
                node.config["requirement_refs"] = [
                    item.id for item in requirements
                    if _relevant(item, node_terms, planner_source)
                ]
                if decomposition_steps:
                    node.config["decomposition_step_refs"] = decomposition_steps
            if node.type in {"human_approval", "tool"}:
                node.config["constraint_refs"] = [
                    item.id for item in constraints
                    if _relevant(item, node_terms, planner_source)
                ]

        errors = validate_workflow(workflow)
        if errors:
            raise ValueError("architect produced invalid workflow: " + str(errors))
        return workflow


class ConfiguredArchitect:
    """Select the model-backed production architect or deterministic fallback."""

    def __init__(self) -> None:
        self.mode = os.getenv("SPECL00M_ARCHITECT_MODE", "bedrock").lower()
        if self.mode not in {"bedrock", "showcase"}:
            self.mode = "bedrock"
        self._impl: Architect | None = None

    def _architect(self) -> Architect:
        if self._impl is not None:
            return self._impl

        if self.mode == "bedrock":
            from backend.agents.bedrock_architect import BedrockArchitect
            self._impl = BedrockArchitect()
        else:
            self._impl = ShowcaseArchitect()
        return self._impl

    def build(self, request: BuildRequest, context: ContextGraph) -> WorkflowIR:
        impl = self._architect()
        if self.mode == "bedrock":
            return impl.build(request.goal, context)  # type: ignore[arg-type]
        return impl.build(request, context)

    def revise(
        self,
        request: BuildRequest,
        context: ContextGraph,
        workflow: WorkflowIR,
        findings: list[dict],
    ) -> WorkflowIR:
        impl = self._architect()
        reviser = getattr(impl, "revise", None)
        if not callable(reviser):
            raise ValueError("configured architect does not support semantic revision")
        if self.mode == "bedrock":
            return reviser(request.goal, context, workflow, findings)
        return workflow

    @staticmethod
    def prompt_preview(request: BuildRequest, context: ContextGraph) -> str:
        return ArchitectPrompt.render(request.goal, context)
