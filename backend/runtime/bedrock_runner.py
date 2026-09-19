from __future__ import annotations

import os
from typing import Any

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

        allowed_tools = [
            str(tool_id)
            for tool_id in node.config.get("tools", [])
            if str(tool_id) in {"web_search", "url_fetch"}
        ]
        agent = self._Agent(
            model=self._model,
            system_prompt=str(
                node.config.get("instructions")
                or node.config.get("role")
                or "Complete the task."
            ),
            tools=build_agent_tools(allowed_tools),
        )
        response = agent(
            "Execute your assigned role using only the supplied workflow context. "
            "Return a structured result when practical.\n\n"
            + str(payload)
        )
        message = getattr(response, "message", None)
        if isinstance(message, dict):
            return {
                "agent": node.id,
                "output": message.get("content", []),
            }
        return {"agent": node.id, "output": str(response)}
