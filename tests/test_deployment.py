from __future__ import annotations

from backend.compiler.deployment import DeploymentCompiler
from backend.compiler.models import Artifact, SoftwareSpec


def test_deployment_plan_requires_staged_promotion():
    spec = SoftwareSpec(
        id="system-deploy",
        name="Deploy",
        goal="Run a production service",
    )
    artifacts = [
        Artifact(
            path="generated/app.py",
            kind="source",
            content="print('ok')",
        ).with_hash()
    ]

    plan = DeploymentCompiler().compile(
        spec,
        artifacts,
        provisioning_ready=True,
    )

    assert [stage.name for stage in plan.stages] == [
        "development",
        "staging",
        "production",
    ]
    assert plan.stages[-1].approval_required is True
    assert plan.production_allowed is True
    assert plan.artifact_digest
