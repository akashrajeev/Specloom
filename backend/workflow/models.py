from __future__ import annotations

from typing import Any, Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator

NodeType = Literal["trigger","agent","tool","condition","parallel","loop","human_approval","output"]


class RetryPolicy(BaseModel):
    model_config = ConfigDict(extra="allow")
    max_attempts: int = Field(default=0, ge=0, le=10)
    backoff_seconds: float = Field(default=0, ge=0)


class Node(BaseModel):
    model_config = ConfigDict(extra="allow")
    id: str = Field(pattern=r"^[A-Za-z][A-Za-z0-9_-]*$")
    type: NodeType
    name: str = Field(min_length=1)
    description: str | None = None
    config: dict[str, Any] = Field(default_factory=dict)
    input_contract: dict[str, Any] | None = None
    output_contract: dict[str, Any] | None = None
    policy_ref: str | None = None
    retry: RetryPolicy | None = None
    timeout_seconds: int | None = Field(default=None, ge=1)


class Trigger(Node):
    type: Literal["trigger"]

    @model_validator(mode="after")
    def validate_trigger(self) -> "Trigger":
        if self.config.get("mode") not in {"manual","schedule","webhook","event"}:
            raise ValueError("trigger.config.mode must be manual, schedule, webhook, or event")
        return self


class WorkflowIR(BaseModel):
    model_config = ConfigDict(extra="allow")
    ir_version: Literal["0.1"]
    id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    description: str | None = None
    trigger: Trigger
    nodes: list[Node] = Field(min_length=1)
    edges: list[dict[str, Any]]
    variables: list[dict[str, Any]]
    policies: list[dict[str, Any]]
    tests: list[dict[str, Any]]

    @model_validator(mode="before")
    @classmethod
    def normalize_edge_keys(cls, data: Any) -> Any:
        # Some model providers write edges as source/target; the IR uses from/to.
        if isinstance(data, dict) and isinstance(data.get("edges"), list):
            edges = []
            for edge in data["edges"]:
                if isinstance(edge, dict):
                    edge = dict(edge)
                    for key, alias in (("from", ("source", "from_", "from_node", "src")), ("to", ("target", "to_node", "dst"))):
                        if key not in edge:
                            for name in alias:
                                if name in edge:
                                    edge[key] = edge.pop(name)
                                    break
                edges.append(edge)
            data = {**data, "edges": edges}
        return data

    @model_validator(mode="after")
    def validate_graph_refs(self) -> "WorkflowIR":
        node_ids = {self.trigger.id, *(node.id for node in self.nodes)}
        if len(node_ids) != len(self.nodes) + 1:
            raise ValueError("duplicate node ids")
        for edge in self.edges:
            if edge.get("from") not in node_ids:
                raise ValueError(f"unknown edge source: {edge.get('from')}")
            if edge.get("to") not in node_ids:
                raise ValueError(f"unknown edge target: {edge.get('to')}")
        return self
