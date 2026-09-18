from __future__ import annotations

from backend.tools.registry import registry
from backend.workflow.models import WorkflowIR


class ToolPolicyError(PermissionError):
    pass


def validate_tool_permissions(ir: WorkflowIR) -> list[str]:
    errors: list[str] = []

    for node in ir.nodes:
        if node.type != "tool":
            continue

        tool_ref = str(node.config.get("tool_ref", ""))
        try:
            spec = registry.get(tool_ref)
        except KeyError:
            errors.append(f"tool {node.id} references unknown tool: {tool_ref}")
            continue

        if spec.side_effecting and not node.policy_ref:
            errors.append(f"side-effecting tool {node.id} requires policy_ref")

        if spec.side_effecting:
            approval_upstream = any(
                candidate.type == "human_approval"
                for candidate in ir.nodes
                if candidate.id != node.id
            )
            if not approval_upstream:
                errors.append(f"side-effecting tool {node.id} requires a human approval node")

    return errors
