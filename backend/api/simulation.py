from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from datetime import datetime, timezone

from backend.context.store import store

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
        store.set_workflow(project_id, request.workflow)
        result = simulator.run(request.workflow, request.input_data)
    except (OSError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    data = result.model_dump(mode="json")
    run_id = f"sim_{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S%f')}"
    store.record_run(
        project_id,
        {
            "run_id": run_id,
            "kind": "simulation",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "input_data": request.input_data,
            "workflow_snapshot": request.workflow.model_dump(mode="json"),
            **data,
        },
    )
    return {"project_id": project_id, "run_id": run_id, **data}
