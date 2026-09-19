from __future__ import annotations

from backend.context.models import ContextGraph
from backend.tools.registry import registry
from backend.workflow.models import WorkflowIR


def augment_with_generated_tests(workflow: WorkflowIR, context: ContextGraph) -> WorkflowIR:
    """Generate deterministic proof obligations in addition to model-authored tests."""
    current = list(workflow.tests)
    existing = {str(test.get("id")) for test in current}

    def add(test: dict) -> None:
        test_id = str(test["id"])
        if test_id not in existing:
            current.append(test)
            existing.add(test_id)

    for requirement in context.requirements:
        if requirement.priority == "low":
            continue
        add(
            {
                "id": f"coverage-{requirement.id}",
                "name": f"Coverage · {requirement.statement[:70]}",
                "input": {},
                "expected": {"requirement_covered": requirement.id},
                "tags": ["compiler", "coverage", "requirement"],
            }
        )

    for constraint in context.constraints:
        if constraint.severity != "blocking":
            continue
        add(
            {
                "id": f"coverage-{constraint.id}",
                "name": f"Coverage · {constraint.statement[:70]}",
                "input": {"approved": False},
                "expected": {"constraint_covered": constraint.id},
                "tags": ["compiler", "coverage", "constraint"],
            }
        )

    for node in workflow.nodes:
        if node.type == "condition":
            branches = [
                edge for edge in workflow.edges
                if edge.get("from") == node.id
                and (edge.get("condition") is not None or edge.get("label") is not None)
            ]
            add(
                {
                    "id": f"control-condition-{node.id}",
                    "name": f"Condition coverage · {node.name}",
                    "input": {},
                    "expected": {
                        "condition_covered": node.id,
                        "branch_count": len(branches),
                    },
                    "tags": ["compiler", "control-flow", "condition"],
                }
            )

        elif node.type == "parallel":
            branches = node.config.get("branches", [])
            add(
                {
                    "id": f"control-parallel-{node.id}",
                    "name": f"Parallel coverage · {node.name}",
                    "input": {},
                    "expected": {
                        "parallel_covered": node.id,
                        "branch_count": len(branches) if isinstance(branches, list) else 0,
                    },
                    "tags": ["compiler", "control-flow", "parallel"],
                }
            )

        elif node.type == "loop":
            add(
                {
                    "id": f"control-loop-{node.id}",
                    "name": f"Loop bound · {node.name}",
                    "input": {"items": [1, 2, 3]},
                    "expected": {
                        "loop_bounded": node.id,
                        "max_iterations": node.config.get("max_iterations"),
                    },
                    "tags": ["compiler", "control-flow", "loop"],
                }
            )

        if node.type == "human_approval":
            add(
                {
                    "id": f"approval-node-{node.id}",
                    "name": f"Approval suspension · {node.name}",
                    "input": {"approved": False},
                    "expected": {"approval_waits_for": node.id},
                    "tags": ["compiler", "policy", "approval"],
                }
            )

        if node.type == "output":
            outgoing = [
                edge for edge in workflow.edges
                if edge.get("from") == node.id
            ]
            if not outgoing:
                add(
                    {
                        "id": f"terminal-output-{node.id}",
                        "name": f"Terminal output · {node.name}",
                        "input": {},
                        "expected": {"terminal_output": node.id},
                        "tags": ["compiler", "control-flow", "output"],
                    }
                )

        if node.type == "tool":
            tool_ref = str(node.config.get("tool_ref", ""))
            try:
                spec = registry.get(tool_ref)
            except KeyError:
                continue
            if spec.side_effecting:
                add(
                    {
                        "id": f"approval-{node.id}",
                        "name": f"Approval boundary · {node.name}",
                        "input": {"approved": False},
                        "expected": {"approval_required_for": node.id},
                        "tags": ["compiler", "policy", "approval"],
                    }
                )

    return workflow.model_copy(update={"tests": current})
