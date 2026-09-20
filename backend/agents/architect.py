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


class ShowcaseArchitect:
    """Deterministic local architect retained as a test/demo fallback."""

    mode = "showcase"

    def build(self, request: BuildRequest, context: ContextGraph) -> WorkflowIR:
        from backend.workflow.templates import deterministic_goal_template

        workflow = deterministic_goal_template(
            goal=request.goal,
            context=context,
        )
        requirement_refs = [
            item.id for item in context.requirements
            if item.priority != "low"
        ]
        constraint_refs = [
            item.id for item in context.constraints
            if item.severity == "blocking"
        ]
        decomposition_steps = [
            str(item.get("id"))
            for item in context.problem_decomposition.get("steps", [])
            if isinstance(item, dict) and item.get("id")
        ]
        for node in workflow.nodes:
            if node.type == "agent":
                node.config["requirement_refs"] = requirement_refs
                if decomposition_steps:
                    node.config["decomposition_step_refs"] = decomposition_steps
            if node.type in {"human_approval", "tool"}:
                node.config["constraint_refs"] = constraint_refs

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
