from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from backend.tools.registry import ToolRegistry, ToolSpec, registry


@dataclass(frozen=True)
class ToolInvocation:
    tool_id: str
    mode: str
    input: dict[str, Any]


class ToolGateway:
    """Single policy-aware boundary between Workflow IR and external tools."""

    def __init__(self, tool_registry: ToolRegistry | None = None) -> None:
        self.registry = tool_registry or registry

    def invoke(
        self,
        invocation: ToolInvocation,
        *,
        approved: bool = False,
    ) -> dict[str, Any]:
        spec = self.registry.get(invocation.tool_id)

        if spec.side_effecting and not approved:
            raise PermissionError(
                f"tool {invocation.tool_id} requires explicit approval"
            )

        if invocation.mode in {"mock", "sandbox"}:
            return {
                "status": "simulated",
                "tool": invocation.tool_id,
                "input": invocation.input,
            }

        return self.registry.invoke(
            invocation.tool_id,
            invocation.input,
            allow_side_effects=approved,
        )
