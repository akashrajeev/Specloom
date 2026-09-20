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
