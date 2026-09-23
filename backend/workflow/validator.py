from __future__ import annotations

from collections import defaultdict, deque
import os

from .models import WorkflowIR
from backend.tools.policy import validate_tool_permissions
from backend.context.models import ContextGraph
from backend.tools.registry import registry
from backend.tools.mcp import configured_mcp_servers, readonly_mcp_server_names


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

    branching_nodes = {"condition", "parallel"}
    node_map = {
        ir.trigger.id: ir.trigger,
        **{node.id: node for node in ir.nodes},
    }
    for node_id, children in outgoing.items():
        node = node_map.get(node_id)
        if node and node.type not in branching_nodes and len(children) > 1:
            errors.append(
                f"node {node_id} has multiple successors; use condition or parallel"
            )

    if len(outgoing.get(ir.trigger.id, [])) != 1:
        errors.append("trigger must have exactly one successor")

    policy_ids = {
        str(policy.get("id"))
        for policy in ir.policies
        if policy.get("id")
    }

    for node in ir.nodes:
        if node.type == "loop":
            maximum = node.config.get("max_iterations")
            if not isinstance(maximum, int) or not 1 <= maximum <= 1000:
                errors.append(
                    f"loop {node.id} requires bounded max_iterations"
                )

        if node.type == "tool":
            mode = node.config.get("mode")
            if mode not in {"mock", "sandbox", "live"}:
                errors.append(f"tool {node.id} has invalid mode")

        if node.type == "condition" and not node.config.get("expression"):
            errors.append(f"condition {node.id} requires an expression")

        if node.type == "agent" and node.config.get("model"):
            requested_model = str(node.config["model"])
            allowed_models = {
                item.strip()
                for item in os.getenv(
                    "SPECL00M_ALLOWED_BEDROCK_MODELS",
                    os.getenv(
                        "SPECL00M_BEDROCK_MODEL_ID",
                        "amazon.nova-lite-v1:0",
                    ),
                ).split(",")
                if item.strip()
            }
            if requested_model not in allowed_models:
                errors.append(
                    f"agent {node.id} references model not in allowlist: {requested_model}"
                )

        if node.type == "agent":
            requested_mcp = node.config.get("mcp_servers", [])
            if requested_mcp:
                if not isinstance(requested_mcp, list):
                    errors.append(
                        f"agent {node.id} mcp_servers must be a list"
                    )
                else:
                    configured = configured_mcp_servers()
                    readonly = readonly_mcp_server_names()
                    for server in requested_mcp:
                        name = str(server)
                        if name not in configured:
                            errors.append(
                                f"agent {node.id} references unknown MCP server: {name}"
                            )
                        elif name not in readonly:
                            errors.append(
                                f"agent {node.id} references MCP server not allowlisted as read-only: {name}"
                            )

        if node.policy_ref and node.policy_ref not in policy_ids:
            errors.append(
                f"node {node.id} references unknown policy: {node.policy_ref}"
            )

    errors.extend(validate_tool_permissions(ir, outgoing))
    return errors


def validate_architecture_coverage(
    ir: WorkflowIR,
    context: ContextGraph,
) -> list[str]:
    """Validate requirements, constraints, and capability bindings against context."""
    errors: list[str] = []
    referenced_requirements: set[str] = set()
    referenced_constraints: set[str] = set()
    valid_requirement_ids = {item.id for item in context.requirements}
    valid_constraint_ids = {item.id for item in context.constraints}
    capabilities = {item.id: item for item in context.capabilities}

    for node in ir.nodes:
        config = node.config

        for ref in config.get("requirement_refs", []):
            ref_id = str(ref)
            referenced_requirements.add(ref_id)
            if ref_id not in valid_requirement_ids:
                errors.append(
                    f"node {node.id} references unknown requirement: {ref_id}"
                )

        for ref in config.get("constraint_refs", []):
            ref_id = str(ref)
            referenced_constraints.add(ref_id)
            if ref_id not in valid_constraint_ids:
                errors.append(
                    f"node {node.id} references unknown constraint: {ref_id}"
                )

        if node.type == "agent":
            bindings = {
                str(item.get("id")): item
                for item in config.get("capability_bindings", [])
                if isinstance(item, dict) and item.get("id")
            }
            for tool_ref in config.get("tools", []):
                ref = str(tool_ref)
                if ref in capabilities or ref in bindings:
                    capability = capabilities.get(ref) or bindings.get(ref)
                    if capability is None:
                        errors.append(
                            f"agent {node.id} references unavailable capability: {ref}"
                        )
                    elif _is_side_effecting(capability):
                        errors.append(
                            f"agent {node.id} references side-effecting capability: {ref}"
                        )
                    continue

                try:
                    registry.get(ref)
                except KeyError:
                    errors.append(
                        f"agent {node.id} references unavailable tool: {ref}"
                    )

        if node.type == "tool":
            ref = str(config.get("tool_ref", ""))
            if ref in capabilities:
                capability = capabilities[ref]
            elif isinstance(config.get("capability"), dict):
                capability = config["capability"]
            elif ref.startswith(("apiop:", "synth:")):
                capability = None
            else:
                capability = None

            if ref.startswith(("apiop:", "synth:")) and capability is None:
                errors.append(
                    f"tool {node.id} references unavailable capability: {ref}"
                )
            elif capability is not None and capability.get("side_effecting") and not node.policy_ref:
                errors.append(
                    f"side-effecting capability {ref} requires policy_ref on {node.id}"
                )

    important_requirements = {
        item.id for item in context.requirements if item.priority != "low"
    }
    important_constraints = {
        item.id for item in context.constraints if item.severity == "blocking"
    }

    for requirement_id in sorted(important_requirements - referenced_requirements):
        errors.append(
            f"important requirement is not covered: {requirement_id}"
        )
    for constraint_id in sorted(important_constraints - referenced_constraints):
        errors.append(
            f"blocking constraint is not covered: {constraint_id}"
        )

    errors.extend(validate_decomposition_coverage(ir, context))
    return errors


def validate_decomposition_coverage(
    ir: WorkflowIR,
    context: ContextGraph,
) -> list[str]:
    """Require every compiled decomposition step to map to executable workflow nodes."""
    decomposition = context.problem_decomposition or {}
    steps = [
        str(item.get("id"))
        for item in decomposition.get("steps", [])
        if isinstance(item, dict) and item.get("id")
    ]
    if not steps:
        return []

    known = set(steps)
    referenced: set[str] = set()
    errors: list[str] = []
    for node in ir.nodes:
        refs = node.config.get("decomposition_step_refs", [])
        if refs is None:
            continue
        if not isinstance(refs, list):
            errors.append(
                f"node {node.id} decomposition_step_refs must be a list"
            )
            continue
        for ref in refs:
            ref_id = str(ref)
            if ref_id not in known:
                errors.append(
                    f"node {node.id} references unknown decomposition step: {ref_id}"
                )
            else:
                referenced.add(ref_id)

    for step_id in sorted(known - referenced):
        errors.append(
            f"decomposition step is not covered by workflow: {step_id}"
        )
    return errors


def assert_valid_workflow(ir: WorkflowIR) -> None:
    errors = validate_workflow(ir)
    if errors:
        raise WorkflowValidationError("; ".join(errors))


def _is_side_effecting(capability: object) -> bool:
    """Capabilities arrive as dict bindings or as CapabilitySpec models."""
    if isinstance(capability, dict):
        return bool(capability.get("side_effecting"))
    return bool(getattr(capability, "side_effecting", False))
