from __future__ import annotations

from typing import Any, Literal
from pydantic import BaseModel, Field


class SimulationEvent(BaseModel):
    sequence: int
    node_id: str
    node_type: str
    status: Literal["started", "completed", "waiting", "failed", "skipped"]
    message: str
    duration_ms: int = Field(ge=0)
    input_summary: Any = None
    output_summary: Any = None


class SimulationResult(BaseModel):
    workflow_id: str
    status: Literal["passed", "failed", "waiting"]
    events: list[SimulationEvent]
    output: Any = None
    failed_node: str | None = None
    error: str | None = None
    side_effects: list[dict[str, Any]] = []
    metrics: dict[str, Any] = {}
