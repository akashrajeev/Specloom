from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from backend.tools.registry import ToolRegistry, registry
from backend.tools.openapi import invoke_openapi_capability
from backend.tools.synthesized import invoke_synthesized_capability


@dataclass(frozen=True)
class ToolInvocation:
    tool_id: str
    mode: str
    input: dict[str, Any]
    capability: dict[str, Any] | None = None


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
        if invocation.capability:
            side_effecting = bool(invocation.capability.get("side_effecting"))
            if side_effecting and not approved:
                raise PermissionError(
                    f"tool {invocation.tool_id} requires explicit approval"
                )

            if invocation.mode in {"mock", "sandbox"}:
                return {
                    "status": "simulated",
                    "tool": invocation.tool_id,
                    "input": invocation.input,
                }

            kind = str(invocation.capability.get("kind"))
            if kind == "openapi":
                return invoke_openapi_capability(
                    invocation.capability,
                    invocation.input,
                    approved=approved,
                )
            if kind == "synthesized":
                return invoke_synthesized_capability(
                    invocation.capability,
                    invocation.input,
                    approved=approved,
                )
            raise ValueError(
                f"unsupported capability kind for {invocation.tool_id}: {kind}"
            )

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
