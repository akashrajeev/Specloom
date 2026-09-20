from backend.context.models import ContextGraph
from backend.workflow.templates import deterministic_goal_template
from backend.workflow.validator import validate_workflow


def test_showcase_fallback_builds_goal_aware_workflow():
    context = ContextGraph()
    workflow = deterministic_goal_template(
        goal="Build a support triage system that reviews urgent customer requests.",
        context=context,
    )

    assert workflow.description.startswith("Build a support triage system")
    assert workflow.trigger.config["mode"] == "manual"
    assert any(node.type == "human_approval" for node in workflow.nodes)
    assert any(node.type == "output" for node in workflow.nodes)
    assert validate_workflow(workflow) == []


def test_support_showcase_proof_accepts_combined_demo_expectations():
    from backend.evaluation.evaluator import Evaluator
    from backend.workflow.templates import deterministic_goal_template

    workflow = deterministic_goal_template(
        goal="Build a support triage system that receives customer requests, classifies the issue, drafts a helpful response, and requires human approval before handling urgent cases.",
        context=ContextGraph(),
    )
    result = Evaluator().evaluate(workflow)

    assert result.status == "passed"
    assert result.failed == 0
