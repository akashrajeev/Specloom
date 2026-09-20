from backend.capabilities.models import CapabilitySpec
from backend.compiler.capability_autobind import auto_bind_required_capabilities
from backend.compiler.synthesizer import infer_capability_requirements
from backend.context.models import ContextGraph
from backend.workflow.models import Node, Trigger, WorkflowIR


def _workflow() -> WorkflowIR:
    return WorkflowIR(
        ir_version="0.1",
        id="canonical-capability-test",
        name="Canonical capability test",
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


def test_canonical_requirement_inference_is_goal_scoped():
    email = CapabilitySpec(
        id="synth:email:canonical",
        kind="synthesized",
        name="Synthesized email adapter",
        description="Send email",
        access="write",
        side_effecting=True,
        requires_human_approval=True,
        tags=["email", "synthesized", "generated_http"],
    )
    slack = CapabilitySpec(
        id="synth:slack:canonical",
        kind="synthesized",
        name="Synthesized slack adapter",
        description="Post Slack message",
        access="write",
        side_effecting=True,
        requires_human_approval=True,
        tags=["slack", "synthesized", "generated_http"],
    )
    context = ContextGraph(capabilities=[email, slack])

    requirements = infer_capability_requirements(
        "Every morning send a summary to my email inbox.",
        context,
    )

    assert [item.family for item in requirements] == ["email"]
    assert requirements[0].id == "capreq:synth:email:canonical"
    assert requirements[0].access == "write"


def test_autobinder_consumes_the_same_canonical_requirement_shape():
    email = CapabilitySpec(
        id="synth:email:canonical",
        kind="synthesized",
        name="Synthesized email adapter",
        description="Send email",
        access="write",
        side_effecting=True,
        requires_human_approval=True,
        tags=["email", "synthesized", "generated_http"],
    )
    context = ContextGraph(capabilities=[email])
    requirements = infer_capability_requirements(
        "Send a report to email.",
        context,
    )

    result, changes = auto_bind_required_capabilities(
        _workflow(),
        context,
        goal="Send a report to email.",
    )

    assert requirements[0].id == "capreq:synth:email:canonical"
    assert requirements[0].family == "email"
    assert any("synth:email:canonical" in change for change in changes)
    assert any(
        node.type == "tool"
        and node.config.get("tool_ref") == email.id
        for node in result.nodes
    )
