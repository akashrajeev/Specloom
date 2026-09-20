from backend.agents.architect import BuildRequest, ShowcaseArchitect
from backend.context.models import ContextGraph
from backend.workflow.validator import validate_workflow


def test_showcase_fallback_builds_goal_aware_workflow():
    context = ContextGraph()
    workflow = ShowcaseArchitect().build(
        BuildRequest(
            goal="Build a support triage system that reviews urgent customer requests.",
            project_id="quota-fallback-demo",
        ),
        context,
    )

    assert workflow.description.startswith("Build a support triage system")
    assert workflow.trigger.config["mode"] == "manual"
    assert any(node.type == "human_approval" for node in workflow.nodes)
    assert any(node.type == "output" for node in workflow.nodes)
    assert validate_workflow(workflow) == []
