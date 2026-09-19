from __future__ import annotations

import json
import os
from typing import Any

from backend.context.models import ContextGraph
from backend.agents.prompt import ArchitectPrompt
from backend.workflow.models import WorkflowIR
from backend.workflow.validator import validate_workflow

ARCHITECT_PROMPT = (
    "You are Specloom's Architect. Return only a valid Workflow IR v0.1 JSON object. "
    "Use only supported node types. Never invent credentials or unavailable tools. "
    "Put high-impact writes behind human approval and keep loops bounded. "
    "Preserve supplied requirements and constraints. Prefer the smallest safe workflow."
)


class BedrockArchitect:
    def __init__(self, model_id: str = "") -> None:
        try:
            from strands import Agent
            from strands.models import BedrockModel
        except ImportError as exc:
            raise RuntimeError(
                "AWS architect dependencies are missing. Install backend/requirements-aws.txt"
            ) from exc

        resolved_model = model_id or os.getenv(
            "SPECL00M_BEDROCK_MODEL_ID", "amazon.nova-lite-v1:0"
        )
        self._agent = Agent(
            model=BedrockModel(model_id=resolved_model),
            system_prompt=ARCHITECT_PROMPT,
        )

    def build(self, goal: str, context: ContextGraph) -> WorkflowIR:
        response = self._agent(
            "GOAL:\n" + goal + "\n\nCONTEXT:\n" + context.model_dump_json(indent=2)
        )
        workflow = WorkflowIR.model_validate(self._extract_json(response))
        errors = validate_workflow(workflow)
        if errors:
            raise ValueError("Bedrock architect produced invalid workflow: " + str(errors))
        return workflow

    @staticmethod
    def _extract_json(response: Any) -> dict[str, Any]:
        text = ""
        message = getattr(response, "message", None)
        if isinstance(message, dict):
            content = message.get("content", [])
            if content and isinstance(content[0], dict):
                text = str(content[0].get("text", ""))
        if not text:
            text = str(response)

        start = text.find("{")
        end = text.rfind("}")
        if start < 0 or end <= start:
            raise ValueError("architect response did not contain a JSON object")
        value = json.loads(text[start : end + 1])
        if not isinstance(value, dict):
            raise ValueError("architect response root must be an object")
        return value
