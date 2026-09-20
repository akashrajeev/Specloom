from backend.capabilities.models import CapabilitySpec
from backend.compiler.synthesizer import infer_capability_requirements, synthesize_missing_capabilities
from backend.context.models import ContextGraph


def test_goal_can_use_external_data_without_creating_write_side_effect():
    email = CapabilitySpec(
        id="synth:email:reader",
        kind="synthesized",
        name="Email reader",
        description="Read incoming email",
        access="read",
        side_effecting=True,
        requires_human_approval=True,
        tags=["email", "synthesized"],
    )

    requirements = infer_capability_requirements(
        "Create a daily report from email messages.",
        ContextGraph(capabilities=[email]),
    )

    assert requirements[0].family == "email"
    assert requirements[0].access == "read"


def test_synthesized_capability_is_read_only_for_ambiguous_external_data_goal():
    capabilities, requirements, _ = synthesize_missing_capabilities(
        "Create a daily report from email messages.",
        ContextGraph(),
    )

    assert capabilities[0].access == "read"
    assert capabilities[0].side_effecting is False
    assert requirements[0].access == "read"


def test_explicit_email_send_remains_write_and_requires_approval():
    capabilities, requirements, _ = synthesize_missing_capabilities(
        "Every morning send the report to my email inbox.",
        ContextGraph(),
    )

    assert capabilities[0].access == "write"
    assert capabilities[0].side_effecting is True
    assert capabilities[0].requires_human_approval is True
    assert requirements[0].access == "write"
