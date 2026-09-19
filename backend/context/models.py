from __future__ import annotations

from typing import Any, Literal
from pydantic import BaseModel, Field

from backend.capabilities.models import CapabilitySpec

SourceKind = Literal["pdf", "url", "github", "text", "api_spec", "data"]


class Provenance(BaseModel):
    source_id: str
    locator: str | None = None
    quote: str | None = None
    confidence: float | None = Field(default=None, ge=0, le=1)


class Source(BaseModel):
    id: str
    kind: SourceKind
    name: str
    uri: str | None = None
    content_hash: str | None = None


class Requirement(BaseModel):
    id: str
    statement: str
    priority: Literal["low", "medium", "high", "critical"] = "medium"
    provenance: list[Provenance] = Field(default_factory=list)


class Constraint(BaseModel):
    id: str
    statement: str
    severity: Literal["info", "warning", "blocking"] = "info"
    provenance: list[Provenance] = Field(default_factory=list)


class ContextTool(BaseModel):
    id: str
    name: str
    description: str | None = None
    capabilities: list[str] = Field(default_factory=list)
    permissions: list[str] = Field(default_factory=list)
    side_effecting: bool = False
    requires_human_approval: bool = False
    execution_modes: list[str] = Field(default_factory=list)


class ContextExample(BaseModel):
    id: str
    input: Any
    expected: Any
    provenance: list[Provenance] = Field(default_factory=list)


class ContextEntity(BaseModel):
    id: str
    type: str
    name: str


class ContextGraph(BaseModel):
    version: Literal["0.1"] = "0.1"
    sources: list[Source] = Field(default_factory=list)
    requirements: list[Requirement] = Field(default_factory=list)
    constraints: list[Constraint] = Field(default_factory=list)
    tools: list[ContextTool] = Field(default_factory=list)
    capabilities: list[CapabilitySpec] = Field(default_factory=list)
    examples: list[ContextExample] = Field(default_factory=list)
    entities: list[ContextEntity] = Field(default_factory=list)
