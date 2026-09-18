from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from backend.simulation.executor import Simulator
from backend.workflow.loader import load_workflow

router = APIRouter(prefix="/api/v1/projects", tags=["simulation"])
simulator = Simulator()

class SimulationRequest(BaseModel):
    approved: bool = False

@router.post("/{project_id}/simulate")
def simulate(project_id: str, request: SimulationRequest) -> dict:
    del project_id  # project persistence comes with the durable control plane.
    try:
        workflow = load_workflow("examples/showcase-workflow.json")
        result = simulator.run(workflow, request.model_dump())
    except (OSError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return result.model_dump(mode="json")
