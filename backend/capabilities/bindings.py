from __future__ import annotations

from backend.context.models import ContextGraph
from backend.workflow.models import WorkflowIR


def capability_map(context: ContextGraph) -> dict[str, object]:
    return {item.id: item for item in context.capabilities}


def bind_capabilities(workflow: WorkflowIR, context: ContextGraph) -> WorkflowIR:
    """Resolve capability IDs into credential-free executable bindings."""
    catalog = capability_map(context)
    changed = []

    for node in workflow.nodes:
        config = dict(node.config)
        refs = [str(value) for value in config.get("tools", [])]
        if node.type == "tool" and config.get("tool_ref"):
            refs.append(str(config["tool_ref"]))

        bindings = []
        for ref in refs:
            capability = catalog.get(ref)
            if capability is None:
                continue
            bindings.append(capability.model_dump(mode="json"))

        if bindings:
            config["capability_bindings"] = bindings

        tool_ref = str(config.get("tool_ref", ""))
        if node.type == "tool" and tool_ref in catalog:
            config["capability"] = catalog[tool_ref].model_dump(mode="json")

        changed.append(node.model_copy(update={"config": config}))

    return workflow.model_copy(update={"nodes": changed})


def validate_capability_bindings(
    workflow: WorkflowIR,
    context: ContextGraph,
) -> list[str]:
    catalog = capability_map(context)
    errors: list[str] = []

    for node in workflow.nodes:
        refs = [str(value) for value in node.config.get("tools", [])]
        if node.type == "tool" and node.config.get("tool_ref"):
            refs.append(str(node.config["tool_ref"]))

        for ref in refs:
            if ref not in catalog:
                if ref.startswith(("apiop:", "synth:")):
                    errors.append(f"node {node.id} references unknown capability: {ref}")
                continue

            capability = catalog[ref]
            if node.type == "agent" and capability.side_effecting:
                errors.append(
                    f"agent {node.id} cannot use side-effecting capability: {ref}"
                )
            if node.type == "tool" and capability.side_effecting and not node.policy_ref:
                errors.append(
                    f"side-effecting capability {ref} requires policy_ref on {node.id}"
                )

    return errors
