from __future__ import annotations

import json

from backend.capabilities.models import CapabilitySpec
from backend.compiler.universal import UniversalCompiler
from backend.context.models import ContextGraph
from backend.tools.gateway import ToolGateway, ToolInvocation
from backend.workflow.models import WorkflowIR


def _workflow() -> WorkflowIR:
    return WorkflowIR.model_validate(
        {
            "ir_version": "0.1",
            "id": "software-compiler-test",
            "name": "Generated System",
            "trigger": {
                "id": "start",
                "type": "trigger",
                "name": "Start",
                "config": {"mode": "manual"},
            },
            "nodes": [
                {
                    "id": "work",
                    "type": "agent",
                    "name": "Work",
                    "config": {
                        "role": "Prepare the requested result",
                        "model": "amazon.nova-lite-v1:0",
                        "tools": [],
                    },
                },
                {
                    "id": "out",
                    "type": "output",
                    "name": "Return",
                    "config": {"mode": "return"},
                },
            ],
            "edges": [
                {"from": "start", "to": "work"},
                {"from": "work", "to": "out"},
            ],
            "variables": [],
            "policies": [],
            "tests": [],
        }
    )


def test_prepare_turns_missing_email_into_first_class_capability():
    context = ContextGraph()
    prepared = UniversalCompiler().prepare(
        "Create a daily service that sends status summaries by email.",
        context,
    )

    synthesized = [
        item for item in prepared.capabilities
        if item.kind == "synthesized" and "email" in item.tags
    ]
    assert len(synthesized) == 1
    capability = synthesized[0]
    assert capability.runtime == "generated_http"
    assert capability.side_effecting is True
    assert capability.requires_human_approval is True
    assert "SPECL00M_SYNTH_EMAIL_BASE_URL" in capability.provisioning_env


def test_compile_produces_implementation_bundle_for_missing_capability():
    compiler = UniversalCompiler()
    context = compiler.prepare(
        "Create a service that sends status summaries by email.",
        ContextGraph(),
    )
    bundle = compiler.compile(
        "Create a service that sends status summaries by email.",
        context,
        _workflow(),
    )

    paths = {artifact.path for artifact in bundle.artifacts}
    assert "generated/spec/system-spec.json" in paths
    assert "generated/spec/workflow-ir.json" in paths
    assert "generated/backend/app.py" in paths
    assert "generated/capabilities/email.py" in paths
    assert "generated/tests/test_email.py" in paths
    assert bundle.requires_provisioning is True
    assert not any(
        diagnostic.severity == "blocking"
        for diagnostic in bundle.diagnostics
    )

    system_spec = next(
        artifact for artifact in bundle.artifacts
        if artifact.path == "generated/spec/system-spec.json"
    )
    assert json.loads(system_spec.content)["version"] == "0.1"
    assert all(artifact.sha256 for artifact in bundle.artifacts)


def test_synthesized_capability_sandbox_is_network_free():
    capability = CapabilitySpec(
        id="synth:email:test",
        kind="synthesized",
        name="Synthesized email adapter",
        description="test",
        access="write",
        permissions=["READ", "WRITE"],
        side_effecting=True,
        requires_human_approval=True,
        runtime="generated_http",
        provisioning_env=[
            "SPECL00M_SYNTH_EMAIL_BASE_URL",
            "SPECL00M_SYNTH_EMAIL_PATH",
            "SPECL00M_SYNTH_EMAIL_METHOD",
            "SPECL00M_SYNTH_EMAIL_API_KEY",
        ],
        execution_modes=["mock", "sandbox", "live"],
    )
    result = ToolGateway().invoke(
        ToolInvocation(
            tool_id=capability.id,
            mode="sandbox",
            input={"body": {"to": "operator@example.com"}},
            capability=capability.model_dump(mode="json"),
        ),
        approved=True,
    )
    assert result["status"] == "simulated"
    assert result["tool"] == capability.id


def test_compile_carries_existing_goal_relevant_capability_into_software_spec():
    capability = CapabilitySpec(
        id="apiop:ticket:create",
        kind="openapi",
        name="Create ticket",
        description="Create a ticket",
        method="POST",
        path="/tickets",
        base_url="https://tickets.example.com",
        access="write",
        permissions=["READ", "WRITE"],
        side_effecting=True,
        requires_human_approval=True,
        tags=["ticket", "api", "openapi", "write"],
    )
    context = ContextGraph(capabilities=[capability])
    bundle = UniversalCompiler().compile(
        "Create tickets in the ticket API.",
        context,
        _workflow(),
    )

    assert any(
        item.id == "capreq:apiop:ticket:create"
        and item.family == "ticket"
        and item.access == "write"
        for item in bundle.spec.capability_requirements
    )
    assert any(
        item["requirement_id"] == "capreq:apiop:ticket:create"
        and item["selected"] is not None
        for item in bundle.capability_bindings
    )


def test_production_gate_requires_materialized_domain_implementation():
    compiler = UniversalCompiler()
    goal = "Create a service that summarizes incoming support requests."
    bundle = compiler.compile(goal, ContextGraph(), _workflow())

    assert bundle.spec.implementation_mode == "deterministic"
    assert bundle.spec.implementation_materialized is False
    assert bundle.deployment["production_allowed"] is False
    assert any(
        "domain implementation is not materialized" in reason
        for reason in bundle.deployment["blocking_reasons"]
    )

    deployment_artifact = next(
        artifact for artifact in bundle.artifacts
        if artifact.path == "generated/deploy/deployment-plan.json"
    )
    plan = json.loads(deployment_artifact.content)
    assert plan["production_allowed"] is False
    assert plan["blocking_reasons"] == bundle.deployment["blocking_reasons"]

    from backend.compiler.models import artifact_snapshot_id

    deployable = [
        artifact
        for artifact in bundle.artifacts
        if artifact.path != "generated/deploy/deployment-plan.json"
    ]
    digest_material = "|".join(
        f"{artifact.path}:{artifact.sha256}"
        for artifact in sorted(deployable, key=lambda item: item.path)
    )
    expected_digest = __import__("hashlib").sha256(
        digest_material.encode("utf-8")
    ).hexdigest()
    assert plan["artifact_digest"] == expected_digest
    assert artifact_snapshot_id(
        bundle.artifacts
    ).startswith("snap_")
