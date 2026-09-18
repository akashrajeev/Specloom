from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from backend.context.models import ContextGraph
from backend.workflow.models import WorkflowIR
from backend.workflow.validator import validate_workflow


@dataclass(frozen=True)
class BuildRequest:
    goal: str
    project_id: str


class Architect(Protocol):
    def build(self, request: BuildRequest, context: ContextGraph) -> WorkflowIR:
        ...


class ShowcaseArchitect:
    """Deterministic local architect used until a Bedrock architect is configured.

    It intentionally builds a safe showcase workflow rather than inventing
    arbitrary integrations from incomplete context.
    """

    def build(self, request: BuildRequest, context: ContextGraph) -> WorkflowIR:
        from backend.workflow.templates import research_hunter_template

        workflow = research_hunter_template(
            goal=request.goal,
            has_github_tool=any("github" in tool.name.lower() for tool in context.tools),
        )
        errors = validate_workflow(workflow)
        if errors:
            raise ValueError(f"architect produced invalid workflow: {errors}")
        return workflow
