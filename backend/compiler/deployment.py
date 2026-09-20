from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from .models import Artifact, SoftwareSpec, artifact_digest


class DeploymentStage(BaseModel):
    name: Literal["development", "staging", "production"]
    required: bool = True
    approval_required: bool = False
    health_check: str = "/health"
    rollback_target: str | None = None


class DeploymentPlan(BaseModel):
    version: Literal["0.1"] = "0.1"
    system_id: str
    artifact_digest: str
    stages: list[DeploymentStage] = Field(default_factory=list)
    production_allowed: bool = False
    blocking_reasons: list[str] = Field(default_factory=list)


class DeploymentCompiler:
    """Compile immutable artifact promotion rules without mutating infrastructure."""

    def compile(
        self,
        spec: SoftwareSpec,
        artifacts: list[Artifact],
        *,
        provisioning_ready: bool,
    ) -> DeploymentPlan:
        digest = artifact_digest(artifacts)

        reasons: list[str] = []
        if spec.synthesized_capabilities and not provisioning_ready:
            reasons.append(
                "required synthesized capability provisioning is not complete"
            )
        if not spec.implementation_materialized:
            reasons.append(
                "domain implementation is not materialized; production deployment requires a verified implementation"
            )
        if not spec.acceptance_proven:
            reasons.append(
                "semantic acceptance proof is incomplete; required behavior is not backed by verifier-owned acceptance cases"
            )
        if not artifacts:
            reasons.append("no generated artifacts are available")

        stages = [
            DeploymentStage(
                name="development",
                required=True,
                approval_required=False,
                rollback_target=None,
            ),
            DeploymentStage(
                name="staging",
                required=True,
                approval_required=False,
                rollback_target="development",
            ),
            DeploymentStage(
                name="production",
                required=True,
                approval_required=True,
                rollback_target="staging",
            ),
        ]

        return DeploymentPlan(
            system_id=spec.id,
            artifact_digest=digest,
            stages=stages,
            production_allowed=not reasons,
            blocking_reasons=reasons,
        )
