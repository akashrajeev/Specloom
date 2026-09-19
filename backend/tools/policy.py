from __future__ import annotations

from collections import deque
from typing import DefaultDict

from backend.tools.registry import registry
from backend.workflow.models import WorkflowIR


class ToolPolicyError(PermissionError):
    pass


def validate_tool_permissions(
    ir: WorkflowIR,
    outgoing: DefaultDict[str, list[str]],
) -> list[str]:
    errors: list[str] = []

    for node in ir.nodes:
        if node.type == "agent":
            for tool_ref in node.config.get("tools", []):
                try:
                    spec = registry.get(str(tool_ref))
                except KeyError:
                    errors.append(f"agent {node.id} references unknown tool: {tool_ref}")
                    continue
                if spec.side_effecting:
                    errors.append(
                        f"agent {node.id} cannot directly use write-capable tool: {tool_ref}; "
                        "use a dedicated tool node behind human approval"
                    )
            continue

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

        if spec.side_effecting and not _has_upstream_approval(
            ir, node.id, outgoing
        ):
            errors.append(
                f"side-effecting tool {node.id} requires upstream human approval"
            )

    return errors


def _has_upstream_approval(
    ir: WorkflowIR,
    target_id: str,
    outgoing: DefaultDict[str, list[str]],
) -> bool:
    reverse: dict[str, list[str]] = {}

    for source, children in outgoing.items():
        for child in children:
            reverse.setdefault(child, []).append(source)

    approvals = {node.id for node in ir.nodes if node.type == "human_approval"}
    queue = deque([target_id])
    seen = {target_id}

    while queue:
        current = queue.popleft()
        for parent in reverse.get(current, []):
            if parent in approvals:
                return True
            if parent not in seen:
                seen.add(parent)
                queue.append(parent)

    return False
