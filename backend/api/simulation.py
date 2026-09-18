from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from backend.simulation.executor import Simulator
from backend.workflow.models import WorkflowIR

router = APIRouter(prefix="/api/v1/projects", tags=["simulation"])
simulator = Simulator()

class SimulationRequest(BaseModel):
    workflow: WorkflowIR
    input_data: dict = Field(default_factory=dict)

@router.post("/{project_id}/simulate")
def simulate(project_id: str, request: SimulationRequest) -> dict:
    try:
        result = simulator.run(request.workflow, request.input_data)
    except (OSError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"project_id": project_id, **result.model_dump(mode="json")}
