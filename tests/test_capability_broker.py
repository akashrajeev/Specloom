from __future__ import annotations

from backend.capabilities.models import CapabilitySpec
from backend.compiler.broker import CapabilityBroker
from backend.compiler.models import CapabilityRequirement
from backend.context.models import ContextGraph


def test_capability_broker_selects_configured_contract_over_missing_synthesis():
    capability = CapabilitySpec(
        id="apiop:mail:send-email",
        kind="openapi",
        name="Send email",
        description="Send an email message",
        access="write",
        side_effecting=True,
        tags=["email"],
        base_url="https://mail.example",
        method="POST",
        path="/send",
    )
    requirement = CapabilityRequirement(
        id="capreq_email",
        family="email",
        purpose="Send email",
        access="write",
        external=True,
    )
    plan = CapabilityBroker().plan(
        [requirement],
        ContextGraph(capabilities=[capability]),
    )[0]

    assert plan.selected is not None
    assert plan.selected.capability_id == capability.id
    assert plan.needs_synthesis is False


def test_capability_broker_marks_unknown_external_family_for_synthesis():
    requirement = CapabilityRequirement(
        id="capreq_crm",
        family="crm",
        purpose="Update CRM",
        access="write",
        external=True,
    )
    plan = CapabilityBroker().plan(
        [requirement],
        ContextGraph(),
    )[0]

    assert plan.selected is None
    assert plan.needs_synthesis is True



def test_capability_broker_prefers_verified_openapi_over_synthesized_placeholder():
    verified = CapabilitySpec(
        id="apiop:crm:create-lead",
        kind="openapi",
        name="Create CRM lead",
        description="Create a CRM lead",
        access="write",
        side_effecting=True,
        tags=["crm", "lead"],
        base_url="https://crm.example",
        method="POST",
        path="/leads",
    )
    placeholder = CapabilitySpec(
        id="synth:crm:lead:placeholder",
        kind="synthesized",
        name="CRM lead adapter",
        description="Create a CRM lead",
        access="write",
        side_effecting=True,
        tags=["crm", "lead"],
    )
    requirement = CapabilityRequirement(
        id="capreq_crm",
        family="crm",
        purpose="Create CRM leads",
        access="write",
        external=True,
    )

    plan = CapabilityBroker().plan(
        [requirement],
        ContextGraph(capabilities=[placeholder, verified]),
    )[0]

    assert plan.selected is not None
    assert plan.selected.capability_id == verified.id
