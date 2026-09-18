from __future__ import annotations

from typing import Any, Literal
from pydantic import BaseModel, Field


class TestResult(BaseModel):
    test_id: str
    name: str
    status: Literal["passed", "failed"]
    message: str
    simulation_status: Literal["passed", "failed", "waiting"]
    evidence: dict[str, Any] = Field(default_factory=dict)


class EvaluationResult(BaseModel):
    workflow_id: str
    status: Literal["passed", "failed"]
    tests: list[TestResult]
    passed: int
    failed: int


class IRPatch(BaseModel):
    description: str
    target_node: str
    path: str
    old_value: Any
    new_value: Any
    rationale: str


class RepairResult(BaseModel):
    repaired: bool
    patch: IRPatch | None = None
    workflow: dict[str, Any] | None = None
