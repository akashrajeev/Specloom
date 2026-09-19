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
        outgoing[source].append(target)
        incoming[target].append(source)

    # Some graph relationships are encoded in node configuration instead of edges.
    # They still represent execution reachability and must be validated as such.
    semantic_refs: dict[str, list[str]] = defaultdict(list)
    for node in ir.nodes:
        if node.type == "loop":
            body = node.config.get("body")
            if body:
                semantic_refs[node.id].append(str(body))
        elif node.type == "parallel":
            semantic_refs[node.id].extend(str(value) for value in node.config.get("branches", []))

    if ir.trigger.id in incoming:
        errors.append("trigger cannot have incoming edges")

    loop_ids = {node.id for node in ir.nodes if node.type == "loop"}
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

    if not any(node.type == "output" for node in ir.nodes):
        errors.append("workflow requires an output node")

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

    errors.extend(validate_tool_permissions(ir, outgoing))
    return errors


def assert_valid_workflow(ir: WorkflowIR) -> None:
    errors = validate_workflow(ir)
    if errors:
        raise WorkflowValidationError("; ".join(errors))
