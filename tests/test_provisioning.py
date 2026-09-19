from __future__ import annotations

from backend.capabilities.models import CapabilitySpec
from backend.compiler.models import ServiceSpec, SoftwareSpec
from backend.compiler.provisioning import ProvisioningCompiler
from backend.context.models import ContextGraph


def test_provisioning_plan_surfaces_synthesized_capability_requirements():
    capability = CapabilitySpec(
        id="synth:email:abc123",
        kind="synthesized",
        name="Email delivery",
        description="Send email",
        access="write",
        side_effecting=True,
        requires_human_approval=True,
        provisioning_env=[
            "SPECL00M_SYNTH_EMAIL_BASE_URL",
            "SPECL00M_SYNTH_EMAIL_PATH",
            "SPECL00M_SYNTH_EMAIL_METHOD",
            "SPECL00M_SYNTH_EMAIL_API_KEY",
        ],
        synthesis_reason="Goal requires sending email.",
        runtime="generated_http",
    )
    spec = SoftwareSpec(
        id="system-test",
        name="Test",
        goal="Send email",
        services=[ServiceSpec(id="runtime", name="Runtime", runtime="python")],
    )
    plan = ProvisioningCompiler().compile(
        spec,
        ContextGraph(capabilities=[capability]),
    )

    assert plan.inputs[0].capability_id == capability.id
    assert "SPECL00M_SYNTH_EMAIL_API_KEY" in plan.environment
    assert any(item.kind == "secret_store" for item in plan.resources)
    assert plan.ready is False


def test_provisioning_plan_adds_database_for_data_models():
    spec = SoftwareSpec(
        id="system-db",
        name="DB",
        goal="Store records",
    )
    spec.data_models = [{"name": "Record", "fields": [{"name": "id", "type": "string"}]}]
    plan = ProvisioningCompiler().compile(spec, ContextGraph())
    assert any(item.kind == "database" for item in plan.resources)


def test_required_database_resource_blocks_provisioning_readiness():
    spec = SoftwareSpec(
        id="system-db-ready",
        name="DB",
        goal="Store records",
        data_models=[{"name": "Record", "fields": [{"name": "id", "type": "string"}]}],
    )
    plan = ProvisioningCompiler().compile(spec, ContextGraph())
    assert any(item.required and item.kind == "database" for item in plan.resources)
    assert plan.ready is False
