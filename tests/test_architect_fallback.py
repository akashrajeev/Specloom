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
