from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, Field

from backend.capabilities.models import CapabilitySpec
from backend.context.models import ContextGraph

from .models import DataModelSpec, SoftwareSpec


class ProvisioningInput(BaseModel):
    capability_id: str
    name: str
    kind: str
    access: Literal["read", "write"]
    required_env: list[str] = Field(default_factory=list)
    reason: str
    human_action: str


class ProvisioningResource(BaseModel):
    id: str
    kind: Literal["database", "object_storage", "queue", "cache", "secret_store", "compute"]
    purpose: str
    required: bool = True


class ProvisioningPlan(BaseModel):
    version: Literal["0.1"] = "0.1"
    system_id: str
    environment: list[str] = Field(default_factory=list)
    inputs: list[ProvisioningInput] = Field(default_factory=list)
    resources: list[ProvisioningResource] = Field(default_factory=list)
    deployment_targets: list[str] = Field(default_factory=list)
    policy_requirements: list[str] = Field(default_factory=list)
    ready: bool = False


class ProvisioningCompiler:
    """Translate provider-neutral software requirements into explicit human/operator work."""

    def compile(
        self,
        spec: SoftwareSpec,
        context: ContextGraph,
    ) -> ProvisioningPlan:
        inputs: list[ProvisioningInput] = []
        for capability in context.capabilities:
            if capability.kind != "synthesized":
                continue
            inputs.append(
                ProvisioningInput(
                    capability_id=capability.id,
                    name=capability.name,
                    kind=capability.kind,
                    access=capability.access,
                    required_env=capability.provisioning_env,
                    reason=capability.synthesis_reason
                    or "Generated external capability contract requires a trusted provider binding.",
                    human_action=(
                        "Configure the documented provider endpoint and credentials, "
                        "verify scopes, then enable live execution."
                    ),
                )
            )

        resources: list[ProvisioningResource] = []
        if spec.data_models:
            resources.append(
                ProvisioningResource(
                    id="primary-database",
                    kind="database",
                    purpose="Persist generated application domain state.",
                )
            )

        if any("cache" in responsibility.lower() for service in spec.services for responsibility in service.responsibilities):
            resources.append(
                ProvisioningResource(
                    id="application-cache",
                    kind="cache",
                    purpose="Provide shared low-latency transient state when required by generated services.",
                    required=False,
                )
            )

        if any(
            capability.kind == "synthesized" and capability.access == "write"
            for capability in context.capabilities
        ):
            resources.append(
                ProvisioningResource(
                    id="secret-store",
                    kind="secret_store",
                    purpose="Store external credentials outside generated source.",
                )
            )

        policy_requirements = [
            "side-effecting actions require explicit approval before live execution",
            "generated external endpoints must use HTTPS",
            "credentials must remain in environment/secret references, never source artifacts",
            "deployment promotion must be staged",
        ]

        required_env = sorted({
            env
            for item in inputs
            for env in item.required_env
        })

        ready = not inputs
        if inputs:
            ready = all(
                self._placeholder_is_explicit(env)
                for env in required_env
            )

        return ProvisioningPlan(
            system_id=spec.id,
            environment=required_env,
            inputs=inputs,
            resources=resources,
            deployment_targets=list(spec.deployment_targets),
            policy_requirements=policy_requirements,
            ready=ready,
        )

    @staticmethod
    def _placeholder_is_explicit(value: str) -> bool:
        return bool(re.fullmatch(r"[A-Z][A-Z0-9_]{0,127}", value))
