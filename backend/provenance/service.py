from __future__ import annotations

import re
from typing import Any

from backend.context.models import ContextGraph, Constraint, Requirement, Source
from backend.workflow.models import Node, WorkflowIR


_STOP = {
    "the", "and", "for", "with", "from", "that", "this", "only", "into",
    "must", "should", "system", "node", "agent", "tool", "data", "using",
}


def build_node_provenance(
    graph: ContextGraph,
    workflow: WorkflowIR,
    node_id: str,
) -> dict[str, Any]:
    node = next((item for item in [workflow.trigger, *workflow.nodes] if item.id == node_id), None)
    if node is None:
        raise KeyError(f"unknown workflow node: {node_id}")

    node_text = _node_text(node)
    requirements = _select_requirements(graph.requirements, node, node_text)
    constraints = _select_constraints(graph.constraints, node, node_text)

    source_ids = _explicit_ids(node, "source_refs")
    for item in [*requirements, *constraints]:
        source_ids.update(provenance.source_id for provenance in item.provenance)

    sources = [source for source in graph.sources if source.id in source_ids]

    policy_ref = node.policy_ref
    policies = [
        policy
        for policy in workflow.policies
        if policy_ref and policy.get("id") == policy_ref
    ]

    tests = _related_tests(workflow.tests, node)
    upstream = [edge["from"] for edge in workflow.edges if edge.get("to") == node.id]
    downstream = [edge["to"] for edge in workflow.edges if edge.get("from") == node.id]

    return {
        "node": node.model_dump(mode="json"),
        "requirements": [item.model_dump(mode="json") for item in requirements],
        "constraints": [item.model_dump(mode="json") for item in constraints],
        "sources": [item.model_dump(mode="json") for item in sources],
        "policies": policies,
        "tests": tests,
        "dependencies": {
            "upstream": upstream,
            "downstream": downstream,
        },
    }


def build_workflow_provenance(
    graph: ContextGraph,
    workflow: WorkflowIR,
) -> dict[str, Any]:
    return {
        "workflow_id": workflow.id,
        "nodes": [
            build_node_provenance(graph, workflow, node.id)
            for node in [workflow.trigger, *workflow.nodes]
        ],
    }


def _node_text(node: Node) -> str:
    config = getattr(node, "config", {})
    parts = [
        node.name,
        node.description or "",
        str(config.get("role", "")),
        str(config.get("instructions", "")),
        str(config.get("prompt", "")),
        str(config.get("tool_ref", "")),
    ]
    return " ".join(parts)


def _tokens(text: str) -> set[str]:
    return {
        token
        for token in re.findall(r"[a-z0-9]+", text.lower())
        if len(token) >= 4 and token not in _STOP
    }


def _explicit_ids(node: Node, key: str) -> set[str]:
    config = getattr(node, "config", {})
    values = config.get(key, [])
    return {str(value) for value in values} if isinstance(values, list) else set()


def _select_requirements(
    requirements: list[Requirement],
    node: Node,
    node_text: str,
) -> list[Requirement]:
    explicit = _explicit_ids(node, "requirement_refs")
    if explicit:
        selected = [item for item in requirements if item.id in explicit]
        if selected:
            return selected

    return _ranked_matches(requirements, node_text)


def _select_constraints(
    constraints: list[Constraint],
    node: Node,
    node_text: str,
) -> list[Constraint]:
    explicit = _explicit_ids(node, "constraint_refs")
    if explicit:
        selected = [item for item in constraints if item.id in explicit]
        if selected:
            return selected

    return _ranked_matches(constraints, node_text)


def _ranked_matches(items: list[Any], node_text: str) -> list[Any]:
    node_tokens = _tokens(node_text)
    scored: list[tuple[float, Any]] = []
    for item in items:
        item_tokens = _tokens(item.statement)
        if not item_tokens:
            continue
        overlap = len(node_tokens & item_tokens)
        score = overlap / max(1, len(item_tokens))
        if score >= 0.2:
            scored.append((score, item))

    scored.sort(key=lambda pair: (-pair[0], pair[1].id))
    return [item for _, item in scored[:4]]


def _related_tests(tests: list[dict[str, Any]], node: Node) -> list[dict[str, Any]]:
    node_id = node.id
    name_tokens = _tokens(node.name)
    related: list[dict[str, Any]] = []

    for test in tests:
        haystack = " ".join(
            [
                str(test.get("id", "")),
                str(test.get("name", "")),
                str(test.get("tags", "")),
                str(test.get("input", "")),
                str(test.get("expected", "")),
            ]
        ).lower()

        if node_id.lower() in haystack:
            related.append(test)
            continue

        if name_tokens & _tokens(haystack):
            related.append(test)

    return related[:6]
