from __future__ import annotations

from fastapi import APIRouter, HTTPException

from backend.evaluation.evaluator import Evaluator
from backend.evaluation.repairer import Repairer
from backend.simulation.executor import Simulator
from backend.workflow.models import WorkflowIR

router = APIRouter(prefix="/api/v1/projects", tags=["evaluation"])
evaluator = Evaluator()
repairer = Repairer()

@router.post("/{project_id}/evaluate")
def evaluate(project_id: str, workflow: WorkflowIR) -> dict:
    del project_id
    return evaluator.evaluate(workflow).model_dump(mode="json")

@router.post("/{project_id}/repair")
def repair(project_id: str, workflow: WorkflowIR) -> dict:
    del project_id
    first = Simulator().run(workflow, {"approved": True})
    if first.status != "failed":
        return {"repaired": False, "reason": "no simulator failure to repair"}
    try:
        result = repairer.repair_from_error(
            workflow,
            failed_node=first.failed_node,
            error=first.error,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return result.model_dump(mode="json")
