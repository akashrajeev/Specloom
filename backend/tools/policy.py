from __future__ import annotations

from collections import deque
from typing import Any, DefaultDict

from backend.tools.registry import registry
from backend.workflow.models import WorkflowIR


class ToolPolicyError(PermissionError):
    pass


def _side_effecting(node: Any) -> bool | None:
    capability = node.config.get("capability")
    if isinstance(capability, dict) and "side_effecting" in capability:
        return bool(capability["side_effecting"])

    tool_ref = str(node.config.get("tool_ref", ""))
    try:
        return bool(registry.get(tool_ref).side_effecting)
    except KeyError:
        if tool_ref.startswith("apiop:"):
            return None
        raise


def validate_tool_permissions(ir: WorkflowIR, outgoing: DefaultDict[str, list[str]]) -> list[str]:
    errors: list[str] = []

    for node in ir.nodes:
        if node.type == "agent":
            bindings = {
                str(item.get("id")): item
                for item in node.config.get("capability_bindings", [])
                if isinstance(item, dict) and item.get("id")
            }
            for tool_ref in node.config.get("tools", []):
                try:
                    spec = registry.get(str(tool_ref))
                except KeyError:
                    match = bindings.get(str(tool_ref))
                    if match is None:
                        errors.append(f"agent {node.id} references unknown tool: {tool_ref}")
                        continue
                    if bool(match.get("side_effecting")):
                        errors.append(
                            f"agent {node.id} cannot directly use write-capable capability: {tool_ref}; "
                            "use a dedicated tool node behind human approval"
                        )
                    continue
                if spec.side_effecting:
                    errors.append(
                        f"agent {node.id} cannot directly use write-capable tool: {tool_ref}; "
                        "use a dedicated tool node behind human approval"
                    )
            continue

        if node.type != "tool":
            continue

        try:
            side_effecting = _side_effecting(node)
        except KeyError:
            errors.append(f"tool {node.id} references unknown tool: {node.config.get('tool_ref')}")
            continue

        if side_effecting is None:
            errors.append(f"tool {node.id} has no resolved capability binding")
            continue

        if side_effecting and not node.policy_ref:
            errors.append(f"side-effecting tool {node.id} requires policy_ref")
        if side_effecting and not _has_upstream_approval(ir, node.id, outgoing):
            errors.append(f"side-effecting tool {node.id} requires upstream human approval")

    return errors


def _has_upstream_approval(ir: WorkflowIR, target_id: str, outgoing: DefaultDict[str, list[str]]) -> bool:
    reverse: dict[str, list[str]] = {}
    for source, children in outgoing.items():
        for child in children:
            reverse.setdefault(child, []).append(source)
    # Loop bodies are semantic edges in Workflow IR rather than ordinary graph edges.
    for parent in ir.nodes:
        if parent.type == "loop":
            body_id = str(parent.config.get("body") or "")
            if body_id:
                reverse.setdefault(body_id, []).append(parent.id)

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
