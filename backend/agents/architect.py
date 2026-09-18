from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol
import os

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
    """Deterministic local architect used until Bedrock is enabled."""

    mode = "showcase"

    def build(self, request: BuildRequest, context: ContextGraph) -> WorkflowIR:
        from backend.workflow.templates import research_hunter_template

        workflow = research_hunter_template(
            goal=request.goal,
            has_github_tool=any("github" in tool.name.lower() for tool in context.tools),
        )
        errors = validate_workflow(workflow)
        if errors:
            raise ValueError("architect produced invalid workflow: " + str(errors))
        return workflow

class ConfiguredArchitect:
    """Select the deterministic or Bedrock-backed architect from environment config."""

    def __init__(self) -> None:
        mode = os.getenv("SPECL00M_ARCHITECT_MODE", "showcase").lower()
        if mode == "bedrock":
            from backend.agents.bedrock_architect import BedrockArchitect
            self.mode = "bedrock"
            self._impl = BedrockArchitect()
        else:
            self.mode = "showcase"
            self._impl = ShowcaseArchitect()

    def build(self, request: BuildRequest, context: ContextGraph) -> WorkflowIR:
        if self.mode == "bedrock":
            return self._impl.build(request.goal, context)
        return self._impl.build(request, context)
