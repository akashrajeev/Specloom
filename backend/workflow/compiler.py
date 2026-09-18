from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass

from .models import WorkflowIR
from .validator import assert_valid_workflow


@dataclass(frozen=True)
class CompiledNode:
    id: str
    type: str
    config: dict


@dataclass(frozen=True)
class ExecutionPlan:
    workflow_id: str
    ordered_nodes: tuple[CompiledNode, ...]


def compile_workflow(ir: WorkflowIR) -> ExecutionPlan:
    """Compile validated IR into a deterministic execution ordering.

    This compiler deliberately handles the common DAG path first. Parallel,
    condition and loop semantics remain encoded in the node config and will be
    interpreted by the runtime executor.
    """
    assert_valid_workflow(ir)

    ids = {ir.trigger.id, *(node.id for node in ir.nodes)}
    node_map = {ir.trigger.id: ir.trigger, **{node.id: node for node in ir.nodes}}
    outgoing: dict[str, list[str]] = defaultdict(list)
    indegree = {node_id: 0 for node_id in ids}

    for edge in ir.edges:
        outgoing[edge["from"]].append(edge["to"])
        indegree[edge["to"]] += 1

    queue = deque(sorted(node_id for node_id, degree in indegree.items() if degree == 0))
    ordered: list[CompiledNode] = []

    while queue:
        node_id = queue.popleft()
        node = node_map[node_id]
        ordered.append(
            CompiledNode(
                id=node.id,
                type=node.type,
                config=getattr(node, "config", {}),
            )
        )
        for child in sorted(outgoing[node_id]):
            indegree[child] -= 1
            if indegree[child] == 0:
                queue.append(child)

    if len(ordered) != len(ids):
        raise ValueError("workflow contains a cycle that the DAG compiler cannot linearize")

    return ExecutionPlan(workflow_id=ir.id, ordered_nodes=tuple(ordered))
