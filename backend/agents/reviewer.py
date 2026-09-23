from __future__ import annotations

from backend.llm import resilient_agent

import json
import os
from typing import Any, Literal

from pydantic import BaseModel, Field

from backend.bedrock_config import resolve_bedrock_model
from backend.context.models import ContextGraph
from backend.workflow.models import WorkflowIR


class ReviewFinding(BaseModel):
    severity: Literal["info", "warning", "blocking"]
    category: str
    message: str
    rationale: str
    node_id: str | None = None
    requirement_refs: list[str] = Field(default_factory=list)
    constraint_refs: list[str] = Field(default_factory=list)


class ArchitectureReview(BaseModel):
    status: Literal["passed", "needs_revision"]
    summary: str
    findings: list[ReviewFinding] = Field(default_factory=list)


class BedrockArchitectureReviewer:
    """Adversarial semantic review of a generated workflow before promotion."""

    def __init__(self, model_id: str = "") -> None:
        try:
            from strands import Agent
            from strands.models import BedrockModel
        except ImportError as exc:
            raise RuntimeError(
                "AWS reviewer dependencies are missing. Install backend/requirements-aws.txt"
            ) from exc

        resolved = resolve_bedrock_model(model_id)
        self._agent = resilient_agent(
            resolved,
            system_prompt=(
                "You are Specloom's adversarial architecture reviewer. "
                "Review a generated Workflow IR against the supplied context. "
                "Look for semantic omissions, unsafe behavior, unnecessary complexity, "
                "unhandled failure modes, missing evidence, weak contracts, and "
                "production-operability problems. Do not invent facts. "
                "Return only the requested structured review."
            ),
        )

    def review(
        self,
        *,
        goal: str,
        context: ContextGraph,
        workflow: WorkflowIR,
    ) -> ArchitectureReview:
        prompt = self._prompt(goal, context, workflow)
        try:
            result = self._agent(prompt, structured_output_model=ArchitectureReview)
            structured = getattr(result, "structured_output", result)
            if isinstance(structured, ArchitectureReview):
                return structured
            if isinstance(structured, dict):
                return ArchitectureReview.model_validate(structured)
        except Exception:
            pass

        response = self._agent(prompt)
        return ArchitectureReview.model_validate(self._extract_json(response))

    @staticmethod
    def _prompt(
        goal: str,
        context: ContextGraph,
        workflow: WorkflowIR,
    ) -> str:
        return (
            "USER GOAL:\n"
            + goal
            + "\n\nCONTEXT:\n"
            + json.dumps(context.model_dump(mode="json"), indent=2)
            + "\n\nGENERATED WORKFLOW:\n"
            + json.dumps(workflow.model_dump(mode="json"), indent=2)
            + "\n\nREVIEW METHOD:\n"
            "1. Determine whether the workflow can actually achieve the requested outcome.\n"
            "2. Check every high/critical requirement and blocking constraint for a concrete implementation path.\n"
            "3. Check that tools are real, permissions are appropriate, and external writes are protected.\n"
            "4. Check conditions, parallel joins, loops, approvals, terminal outputs, retries and timeouts.\n"
            "5. Check whether the selected control flow is unnecessarily complex or hides important decisions.\n"
            "6. Check whether tests cover representative behavior and safety boundaries.\n"
            "7. Mark a finding blocking only when the generated system should not be promoted without correction.\n"
            "8. Reference exact node IDs and requirement/constraint IDs when applicable.\n\n"
            "Return status=needs_revision when one or more blocking findings exist; otherwise status=passed."
        )

    @staticmethod
    def _extract_json(response: Any) -> dict[str, Any]:
        message = getattr(response, "message", None)
        text = ""
        if isinstance(message, dict):
            for item in message.get("content", []):
                if isinstance(item, dict) and item.get("text"):
                    text += str(item["text"])
        if not text:
            text = str(response)

        start = text.find("{")
        end = text.rfind("}")
        if start < 0 or end <= start:
            raise ValueError("architecture reviewer response did not contain JSON")
        value = json.loads(text[start : end + 1])
        if not isinstance(value, dict):
            raise ValueError("architecture reviewer response must be an object")
        return value
