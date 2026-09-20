from __future__ import annotations

import hashlib
from typing import Any, Literal

from pydantic import BaseModel, Field


ArtifactKind = Literal[
    "spec",
    "source",
    "test",
    "config",
    "infrastructure",
    "documentation",
]


class CapabilityRequirement(BaseModel):
    id: str
    family: str
    purpose: str
    access: Literal["read", "write"] = "read"
    external: bool = False
    required: bool = True


class SynthesizedCapabilityPlan(BaseModel):
    capability_id: str
    family: str
    rationale: str
    runtime: Literal["generated_http", "local_contract"] = "generated_http"
    provisioning_env: list[str] = Field(default_factory=list)
    artifact_paths: list[str] = Field(default_factory=list)
    configuration_required: bool = True


class ServiceSpec(BaseModel):
    id: str
    name: str
    runtime: str
    responsibilities: list[str] = Field(default_factory=list)
    interfaces: list[str] = Field(default_factory=list)


class DataModelSpec(BaseModel):
    name: str
    fields: list[dict[str, Any]] = Field(default_factory=list)


class SoftwareSpec(BaseModel):
    """Provider-neutral specification for the software surrounding Workflow IR."""

    version: Literal["0.1"] = "0.1"
    id: str
    name: str
    goal: str
    architecture_style: Literal["agent_service", "api_service", "application"] = "agent_service"
    services: list[ServiceSpec] = Field(default_factory=list)
    capability_requirements: list[CapabilityRequirement] = Field(default_factory=list)
    synthesized_capabilities: list[SynthesizedCapabilityPlan] = Field(default_factory=list)
    data_models: list[DataModelSpec] = Field(default_factory=list)
    environment: list[str] = Field(default_factory=list)
    deployment_targets: list[str] = Field(default_factory=lambda: ["container"])
    implementation_mode: Literal["deterministic", "bedrock", "off"] = "deterministic"
    implementation_materialized: bool = True
    acceptance_proven: bool = True
    acceptance_reviewed: bool = True
    acceptance_origin: Literal["user", "model", "mixed", "none"] = "user"
    acceptance_case_count: int = 0
    acceptance_unverified_criteria: list[str] = Field(default_factory=list)
    contract_proven: bool = True
    contract_unverified_families: list[str] = Field(default_factory=list)
    problem_decomposition: dict[str, Any] = Field(default_factory=dict)
    implementation_uncovered_steps: list[str] = Field(default_factory=list)
    workflow_id: str | None = None
    source_refs: list[str] = Field(default_factory=list)


class Artifact(BaseModel):
    path: str = Field(min_length=1)
    kind: ArtifactKind
    content: str
    executable: bool = False
    generated_from: list[str] = Field(default_factory=list)
    sha256: str = ""

    def with_hash(self) -> "Artifact":
        digest = hashlib.sha256(self.content.encode("utf-8")).hexdigest()
        return self.model_copy(update={"sha256": digest})


def artifact_digest(
    artifacts: list[Artifact],
    *,
    exclude_paths: set[str] | None = None,
) -> str:
    excluded = exclude_paths or set()
    material = "|".join(
        f"{item.path}:{item.with_hash().sha256}"
        for item in sorted(artifacts, key=lambda item: item.path)
        if item.path not in excluded
    )
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def artifact_snapshot_id(artifacts: list[Artifact]) -> str:
    """Derive the immutable snapshot identity from every artifact path + hash."""
    material = "".join(
        f"{item.path}:{item.with_hash().sha256}\n"
        for item in sorted(artifacts, key=lambda item: item.path)
    )
    return "snap_" + hashlib.sha256(material.encode("utf-8")).hexdigest()[:24]


class CompilerDiagnostic(BaseModel):
    severity: Literal["info", "warning", "blocking"]
    code: str
    message: str
    capability_id: str | None = None
    artifact_path: str | None = None


class CompilationBundle(BaseModel):
    spec: SoftwareSpec
    artifacts: list[Artifact] = Field(default_factory=list)
    diagnostics: list[CompilerDiagnostic] = Field(default_factory=list)
    ready_for_runtime: bool = False
    requires_provisioning: bool = False
    system_ir: dict[str, Any] = Field(default_factory=dict)
    verification: dict[str, Any] = Field(default_factory=dict)
    provisioning: dict[str, Any] = Field(default_factory=dict)
    deployment: dict[str, Any] = Field(default_factory=dict)
    dependencies: dict[str, Any] = Field(default_factory=dict)
    capability_bindings: list[dict[str, Any]] = Field(default_factory=list)
    acceptance_review: dict[str, Any] = Field(default_factory=dict)

    def artifact_map(self) -> dict[str, str]:
        return {artifact.path: artifact.content for artifact in self.artifacts}
