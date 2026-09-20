from backend.capabilities.models import CapabilitySpec
from backend.compiler.synthesizer import infer_capability_requirements, synthesize_missing_capabilities
from backend.context.models import ContextGraph


def test_external_data_use_does_not_become_write_side_effect():
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



def test_open_world_discovered_write_capability_is_provider_neutral():
    from backend.compiler.capability_discovery import DiscoveredCapability
    from backend.compiler.synthesizer import synthesize_missing_capabilities

    discovered = [
        DiscoveredCapability(
            family="crm",
            purpose="Create and update customer leads.",
            access="write",
            side_effecting=True,
            requires_human_approval=True,
            evidence=["goal explicitly requests lead creation"],
        )
    ]

    capabilities, requirements, plans = synthesize_missing_capabilities(
        "Create a lead in our CRM when a qualified customer is detected.",
        ContextGraph(),
        discovered=discovered,
    )

    assert len(capabilities) == 1
    assert capabilities[0].id.startswith("synth:crm:")
    assert capabilities[0].base_url is None
    assert capabilities[0].path is None
    assert capabilities[0].access == "write"
    assert capabilities[0].side_effecting is True
    assert capabilities[0].requires_human_approval is True
    assert requirements[0].family == "crm"
    assert requirements[0].access == "write"
    assert plans[0].configuration_required is True


def test_universal_compiler_can_add_open_world_family_without_inventing_provider(monkeypatch):
    import backend.compiler.universal as universal_module

    from backend.compiler.capability_discovery import (
        CapabilityDiscovery,
        DiscoveredCapability,
    )

    class FakeDiscovery:
        def __init__(self):
            pass

        def discover(self, *, goal, context):
            return CapabilityDiscovery(
                capabilities=[
                    DiscoveredCapability(
                        family="erp",
                        purpose="Create purchase orders in an ERP.",
                        access="write",
                        side_effecting=True,
                        requires_human_approval=True,
                        evidence=["goal contains purchase order creation"],
                    )
                ]
            )

    monkeypatch.setenv("SPECL00M_CAPABILITY_MODE", "bedrock")
    monkeypatch.setattr(
        universal_module,
        "BedrockCapabilityDiscovery",
        FakeDiscovery,
    )

    compiler = universal_module.UniversalCompiler()
    prepared = compiler.prepare(
        "Create a purchase order in the ERP after approval.",
        ContextGraph(),
    )

    discovered = [
        item
        for item in prepared.capabilities
        if item.id.startswith("synth:erp:")
    ]
    assert len(discovered) == 1
    capability = discovered[0]
    assert capability.base_url is None
    assert capability.path is None
    assert capability.access == "write"
    assert capability.requires_human_approval is True
