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
        agent = self._Agent(
            model=self._model,
            system_prompt=str(node.config.get("instructions") or node.config.get("role") or "Complete the task."),
        )
        response = agent(str(payload))
        message = getattr(response, "message", None)
        if isinstance(message, dict):
            return {
                "agent": node.id,
                "output": message.get("content", []),
            }
        return {"agent": node.id, "output": str(response)}
