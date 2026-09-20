from backend.capabilities.models import CapabilitySpec
from backend.compiler.synthesizer import infer_capability_requirements
from backend.context.models import ContextGraph


def test_custom_capability_family_can_use_generic_explicit_write_intent():
    capability = CapabilitySpec(
        id="apiop:ticket:create",
        kind="openapi",
        name="Create ticket",
        description="Create a ticket",
        method="POST",
        path="/tickets",
        base_url="https://tickets.example.com",
        access="write",
        side_effecting=True,
        requires_human_approval=True,
        tags=["ticket", "api", "openapi", "write"],
    )
    result = infer_capability_requirements(
        "Create tickets in the ticket API.",
        ContextGraph(capabilities=[capability]),
    )
    assert result[0].access == "write"


def test_data_source_phrase_does_not_create_external_write_intent():
    capability = CapabilitySpec(
        id="synth:email:source",
        kind="synthesized",
        name="Email reader",
        description="Read incoming email",
        access="read",
        side_effecting=True,
        requires_human_approval=True,
        tags=["email", "synthesized"],
    )
    result = infer_capability_requirements(
        "Create a daily report from email messages.",
        ContextGraph(capabilities=[capability]),
    )
    assert result[0].access == "read"
