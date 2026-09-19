from __future__ import annotations

from typing import Any, Literal
from pydantic import BaseModel, Field


CapabilityKind = Literal["builtin", "configured_api", "openapi", "mcp", "synthesized"]
CapabilityAccess = Literal["read", "write"]
CapabilityRuntime = Literal["registry", "openapi", "generated_http", "local_contract"]


class CapabilitySpec(BaseModel):
    """A credential-free, executable capability known to Specloom."""

    id: str = Field(min_length=1)
    kind: CapabilityKind
    name: str = Field(min_length=1)
    description: str = ""
    source_id: str | None = None
    operation_id: str | None = None
    method: str | None = None
    path: str | None = None
    base_url: str | None = None
    access: CapabilityAccess = "read"
    permissions: list[str] = Field(default_factory=list)
    side_effecting: bool = False
    requires_human_approval: bool = False
    auth_env: str | None = None
    auth_header: str = "Authorization"
    auth_prefix: str = "Bearer "
    input_schema: dict[str, Any] = Field(default_factory=dict)
    output_schema: dict[str, Any] = Field(default_factory=dict)
    tags: list[str] = Field(default_factory=list)
    runtime: CapabilityRuntime = "registry"
    implementation_artifacts: list[str] = Field(default_factory=list)
    provisioning_env: list[str] = Field(default_factory=list)
    synthesis_reason: str | None = None
    execution_modes: list[str] = Field(default_factory=list)

    @property
    def risk(self) -> str:
        return "side_effect" if self.side_effecting else "read"

    def to_context_tool(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "capabilities": list(self.tags),
            "permissions": list(self.permissions),
            "side_effecting": self.side_effecting,
            "requires_human_approval": self.requires_human_approval,
            "execution_modes": list(self.execution_modes)
            or (["mock", "sandbox", "live"] if self.side_effecting else ["live"]),
        }
