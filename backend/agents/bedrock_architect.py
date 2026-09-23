from __future__ import annotations

from backend.llm import resilient_agent

import json
import os
from typing import Any

from backend.bedrock_config import resolve_bedrock_model
from backend.context.models import ContextGraph
from backend.agents.prompt import ArchitectPrompt
from backend.capabilities.bindings import bind_capabilities, validate_capability_bindings
from backend.workflow.models import WorkflowIR
from backend.workflow.validator import validate_workflow, validate_architecture_coverage


class BedrockArchitect:
    """Model-backed generic system architect with schema-first generation and repair."""

    def __init__(self, model_id: str = "", max_repairs: int = 2) -> None:
        try:
            from strands import Agent
            from strands.models import BedrockModel
        except ImportError as exc:
            raise RuntimeError(
                "AWS architect dependencies are missing. Install backend/requirements-aws.txt"
            ) from exc

        resolved_model = resolve_bedrock_model(model_id)
        self.max_repairs = max(0, min(max_repairs, 3))
        self._agent = resilient_agent(
            resolved_model,
            system_prompt=(
                "You are Specloom's autonomous compiler. "
                "Produce only Workflow IR v0.1. "
                "Reason internally, preserve supplied facts, and never invent tools."
            ),
        )

    def build(self, goal: str, context: ContextGraph) -> WorkflowIR:
        prompt = ArchitectPrompt.render(goal, context)
        last_payload: dict[str, Any] | None = None
        last_errors: list[str] = []

        for attempt in range(self.max_repairs + 1):
            current_prompt = prompt
            if attempt:
                current_prompt = self._repair_prompt(prompt, last_payload or {}, last_errors)

            workflow = self._generate(current_prompt)
            workflow = bind_capabilities(workflow, context)
            last_payload = workflow.model_dump(mode="json")
            errors = validate_workflow(workflow)
            if not errors:
                errors = validate_architecture_coverage(workflow, context)
            if not errors:
                errors = validate_capability_bindings(workflow, context)
            if not errors:
                return workflow
            last_errors = errors

        raise ValueError(
            "Bedrock architect could not produce a valid workflow after "
            f"{self.max_repairs} repair attempt(s): {last_errors}"
        )

    def revise(
        self,
        goal: str,
        context: ContextGraph,
        workflow: WorkflowIR,
        findings: list[dict[str, Any]],
    ) -> WorkflowIR:
        feedback = "\n".join(
            f"- [{item.get('severity', 'blocking')}] {item.get('message', '')} "
            f"(node={item.get('node_id') or 'n/a'})"
            for item in findings
        )
        prompt = (
            ArchitectPrompt.render(goal, context)
            + "\n\nADVERSARIAL REVIEW / TEST FINDINGS:\n"
            + feedback
            + "\n\nCURRENT WORKFLOW JSON:\n"
            + json.dumps(workflow.model_dump(mode="json"), indent=2)
            + "\n\nRevise the workflow to address every blocking finding. Preserve valid design decisions, "
              "keep exact context references, use only compiled capabilities, and return only Workflow IR JSON."
        )
        revised = bind_capabilities(self._generate(prompt), context)
        errors = validate_workflow(revised)
        if not errors:
            errors = validate_architecture_coverage(revised, context)
        if not errors:
            errors = validate_capability_bindings(revised, context)
        if errors:
            raise ValueError(
                "architect revision failed deterministic validation: " + "; ".join(errors)
            )
        return revised

    def _generate(self, prompt: str) -> WorkflowIR:
        try:
            result = self._agent(prompt, structured_output_model=WorkflowIR)
            structured = getattr(result, "structured_output", result)
            if isinstance(structured, WorkflowIR):
                return structured
            if isinstance(structured, dict):
                return WorkflowIR.model_validate(structured)
        except Exception:
            pass

        response = self._agent(prompt)
        return WorkflowIR.model_validate(self._extract_json(response))

    @staticmethod
    def _repair_prompt(original_prompt: str, payload: dict[str, Any], errors: list[str]) -> str:
        hints = []
        if any("is not covered" in error for error in errors):
            hints.append(
                "For each uncovered id, add it to config.requirement_refs (or config.constraint_refs) "
                "of the node that implements it. Keep every ref you already have."
            )
        return (
            original_prompt
            + "\n\nREPAIR THE PREVIOUS WORKFLOW.\n"
            + "VALIDATION ERRORS:\n- "
            + "\n- ".join(errors)
            + ("\n" + "\n".join(hints) if hints else "")
            + "\n\nPREVIOUS WORKFLOW JSON:\n"
            + json.dumps(payload, separators=(",", ":"))
            + "\n\nReturn the corrected Workflow IR JSON only."
        )

    @staticmethod
    def _extract_json(response: Any) -> dict[str, Any]:
        text = ""
        message = getattr(response, "message", None)
        if isinstance(message, dict):
            chunks = message.get("content", [])
            text = "".join(
                str(chunk.get("text", ""))
                for chunk in chunks
                if isinstance(chunk, dict) and chunk.get("text")
            )
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
