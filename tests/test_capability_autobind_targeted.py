from backend.capabilities.models import CapabilitySpec
from backend.compiler.capability_autobind import auto_bind_required_capabilities
from backend.context.models import ContextGraph
from backend.workflow.models import Node, Trigger, WorkflowIR


def _workflow() -> WorkflowIR:
    return WorkflowIR(
        ir_version="0.1",
        id="autobind-targeted",
        name="Autobind targeted",
        description="test",
        trigger=Trigger(
            id="start",
            type="trigger",
            name="Start",
            config={"mode": "manual"},
        ),
        nodes=[
            Node(id="agent", type="agent", name="Agent", config={"tools": []}),
            Node(id="output", type="output", name="Output", config={}),
        ],
        edges=[
            {"from": "start", "to": "agent"},
            {"from": "agent", "to": "output"},
        ],
        variables=[],
        policies=[],
        tests=[],
    )


def test_autobind_uses_goal_to_ignore_unrelated_context_capabilities():
    email = CapabilitySpec(
        id="synth:email:goal",
        kind="synthesized",
        name="Email adapter",
        description="Send email",
        access="write",
        side_effecting=True,
        requires_human_approval=True,
        tags=["email", "synthesized"],
    )
    slack = CapabilitySpec(
        id="synth:slack:unrelated",
        kind="synthesized",
        name="Slack adapter",
        description="Post messages",
        access="write",
        side_effecting=True,
        requires_human_approval=True,
        tags=["slack", "synthesized"],
    )

    result, _ = auto_bind_required_capabilities(
        _workflow(),
        ContextGraph(capabilities=[email, slack]),
        goal="Every morning send a summary to my email inbox.",
    )

    refs = {
        node.config.get("tool_ref")
        for node in result.nodes
        if node.type == "tool"
    }
    assert email.id in refs
    assert slack.id not in refs
