from __future__ import annotations

import os
from typing import Any

from backend.tools.registry import registry
from backend.workflow.models import Node


class BedrockAgentRunner:
    """Adapter for executing agent nodes with Strands + Amazon Bedrock."""

    def __init__(self, model_id: str | None = None) -> None:
        try:
            from strands import Agent
            from strands.models import BedrockModel
        except ImportError as exc:
            raise RuntimeError("Install backend/requirements-aws.txt for Bedrock runtime.") from exc

        resolved = model_id or os.getenv("SPECL00M_BEDROCK_MODEL_ID", "amazon.nova-lite-v1:0")
        self._Agent = Agent
        self._model = BedrockModel(model_id=resolved)

    def __call__(self, node: Node, payload: Any) -> Any:
        from backend.runtime.agent_tools import build_agent_tools

        requested = [str(tool_id) for tool_id in node.config.get("tools", [])]
        allowed_tools = []
        for tool_id in requested:
            try:
                spec = registry.get(tool_id)
            except KeyError as exc:
                raise ValueError(f"agent {node.id} requested unknown tool: {tool_id}") from exc
            if spec.side_effecting:
                raise PermissionError(
                    f"agent {node.id} cannot directly use side-effecting tool: {tool_id}"
                )
            allowed_tools.append(tool_id)

        instructions = str(
            node.config.get("instructions")
            or node.config.get("role")
            or "Complete the task."
        )
        system_prompt = (
            instructions
            + "\\n\\nRuntime rules: use only the provided tools; do not invent facts or "
            "credentials; cite retrieved evidence when the task requires evidence."
        )
        agent = self._Agent(
            model=self._model,
            system_prompt=system_prompt,
            tools=build_agent_tools(allowed_tools),
        )
        response = agent(
            "Execute your assigned role using only the supplied workflow context. "
            "Return the result needed by downstream workflow nodes.\\n\\n"
            + str(payload)
        )
        message = getattr(response, "message", None)
        if isinstance(message, dict):
            return {
                "agent": node.id,
                "output": message.get("content", []),
            }
        return {"agent": node.id, "output": str(response)}
