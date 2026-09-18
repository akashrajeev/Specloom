from __future__ import annotations
from collections import defaultdict
from .models import WorkflowIR

class WorkflowValidationError(ValueError):
    pass

def validate_workflow(ir: WorkflowIR) -> list[str]:
    errors: list[str] = []
    node_ids = {ir.trigger.id, *(node.id for node in ir.nodes)}
    outgoing: dict[str, list[str]] = defaultdict(list)
    incoming: dict[str, list[str]] = defaultdict(list)
    for edge in ir.edges:
        outgoing[edge["from"]].append(edge["to"])
        incoming[edge["to"]].append(edge["from"])

    if ir.trigger.id in incoming:
        errors.append("trigger cannot have incoming edges")

    loop_ids = {node.id for node in ir.nodes if node.type == "loop"}
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(node_id: str) -> None:
        if node_id in visiting:
            if node_id not in loop_ids:
                errors.append(f"cycle detected outside loop: {node_id}")
            return
        if node_id in visited:
            return
        visiting.add(node_id)
        for child in outgoing.get(node_id, []):
            visit(child)
        visiting.remove(node_id)
        visited.add(node_id)

    visit(ir.trigger.id)
    unreachable = node_ids - visited
    if unreachable:
        errors.append(f"unreachable nodes: {sorted(unreachable)}")

    if not any(node.type == "output" for node in ir.nodes):
        errors.append("workflow requires an output node")

    for node in ir.nodes:
        if node.type == "loop":
            maximum = node.config.get("max_iterations")
            if not isinstance(maximum, int) or not 1 <= maximum <= 1000:
                errors.append(f"loop {node.id} requires bounded max_iterations")
        if node.type == "tool" and node.config.get("mode") not in {"mock","sandbox","live"}:
            errors.append(f"tool {node.id} has invalid mode")

    return errors

def assert_valid_workflow(ir: WorkflowIR) -> None:
    errors = validate_workflow(ir)
    if errors:
        raise WorkflowValidationError("; ".join(errors))
