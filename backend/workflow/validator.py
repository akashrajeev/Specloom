from __future__ import annotations

from collections import defaultdict, deque

from .models import WorkflowIR
from backend.tools.policy import validate_tool_permissions


class WorkflowValidationError(ValueError):
    pass


def validate_workflow(ir: WorkflowIR) -> list[str]:
    errors: list[str] = []
    node_ids = {ir.trigger.id, *(node.id for node in ir.nodes)}
    outgoing: dict[str, list[str]] = defaultdict(list)
    incoming: dict[str, list[str]] = defaultdict(list)

    for edge in ir.edges:
        source = edge.get("from")
        target = edge.get("to")
        if source not in node_ids:
            errors.append(f"unknown edge source: {source}")
            continue
        if target not in node_ids:
            errors.append(f"unknown edge target: {target}")
            continue
        outgoing[source].append(target)
        incoming[target].append(source)

    semantic_refs: dict[str, list[str]] = defaultdict(list)
    for node in ir.nodes:
        if node.type == "loop":
            body = node.config.get("body")
            if not body:
                errors.append(f"loop {node.id} requires a body node")
            else:
                semantic_refs[node.id].append(str(body))
        elif node.type == "parallel":
            branches = node.config.get("branches", [])
            if not isinstance(branches, list) or len(branches) < 2:
                errors.append(f"parallel {node.id} requires at least two branches")
            else:
                semantic_refs[node.id].extend(str(value) for value in branches)
        elif node.type == "condition":
            branches = node.config.get("branches", [])
            if branches and (not isinstance(branches, list) or len(branches) < 2):
                errors.append(f"condition {node.id} requires at least two branches")

    for source, refs in semantic_refs.items():
        for target in refs:
            if target not in node_ids:
                errors.append(f"node {source} references unknown node: {target}")

    if ir.trigger.id in incoming:
        errors.append("trigger cannot have incoming edges")

    reachable: set[str] = set()
    queue = deque([ir.trigger.id])
    while queue:
        current = queue.popleft()
        if current in reachable:
            continue
        reachable.add(current)
        queue.extend(outgoing.get(current, []))
        queue.extend(semantic_refs.get(current, []))

    unreachable = node_ids - reachable
    if unreachable:
        errors.append(f"unreachable nodes: {sorted(unreachable)}")

    outputs = [node.id for node in ir.nodes if node.type == "output"]
    if not outputs:
        errors.append("workflow requires an output node")
    for output_id in outputs:
        if outgoing.get(output_id):
            errors.append(f"output {output_id} must be terminal")

    policy_ids = {str(policy.get("id")) for policy in ir.policies if policy.get("id")}
    for node in ir.nodes:
        if node.type == "loop":
            maximum = node.config.get("max_iterations")
            if not isinstance(maximum, int) or not 1 <= maximum <= 1000:
                errors.append(f"loop {node.id} requires bounded max_iterations")

        if node.type == "tool":
            mode = node.config.get("mode")
            if mode not in {"mock", "sandbox", "live"}:
                errors.append(f"tool {node.id} has invalid mode")

        if node.type == "condition" and not node.config.get("expression"):
            errors.append(f"condition {node.id} requires an expression")

        if node.policy_ref and node.policy_ref not in policy_ids:
            errors.append(f"node {node.id} references unknown policy: {node.policy_ref}")

    errors.extend(validate_tool_permissions(ir, outgoing))
    return errors


def assert_valid_workflow(ir: WorkflowIR) -> None:
    errors = validate_workflow(ir)
    if errors:
        raise WorkflowValidationError("; ".join(errors))
