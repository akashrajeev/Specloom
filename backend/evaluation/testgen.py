from __future__ import annotations

from backend.context.models import ContextGraph
from backend.tools.registry import registry
from backend.workflow.models import WorkflowIR


def augment_with_generated_tests(workflow: WorkflowIR, context: ContextGraph) -> WorkflowIR:
    """Add deterministic proof obligations that the model cannot omit."""
    current = list(workflow.tests)
    existing = {str(test.get("id")) for test in current}

    for requirement in context.requirements:
        if requirement.priority == "low":
            continue
        test_id = f"coverage-{requirement.id}"
        if test_id in existing:
            continue
        current.append(
            {
                "id": test_id,
                "name": f"Coverage · {requirement.statement[:70]}",
                "input": {},
                "expected": {"requirement_covered": requirement.id},
                "tags": ["compiler", "coverage", "requirement"],
            }
        )
        existing.add(test_id)

    for constraint in context.constraints:
        if constraint.severity != "blocking":
            continue
        test_id = f"coverage-{constraint.id}"
        if test_id in existing:
            continue
        current.append(
            {
                "id": test_id,
                "name": f"Coverage · {constraint.statement[:70]}",
                "input": {"approved": False},
                "expected": {"constraint_covered": constraint.id},
                "tags": ["compiler", "coverage", "constraint"],
            }
        )
        existing.add(test_id)

    for node in workflow.nodes:
        if node.type != "tool":
            continue
        tool_ref = str(node.config.get("tool_ref", ""))
        try:
            spec = registry.get(tool_ref)
        except KeyError:
            continue
        if not spec.side_effecting:
            continue

        test_id = f"approval-{node.id}"
        if test_id in existing:
            continue
        current.append(
            {
                "id": test_id,
                "name": f"Approval boundary · {node.name}",
                "input": {"approved": False},
                "expected": {"approval_required_for": node.id},
                "tags": ["compiler", "policy", "approval"],
            }
        )
        existing.add(test_id)

    return workflow.model_copy(update={"tests": current})
