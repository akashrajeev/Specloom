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
    return {
        "project_id": project_id,
        **evaluator.evaluate(workflow).model_dump(mode="json"),
    }


@router.post("/{project_id}/repair")
def repair(project_id: str, workflow: WorkflowIR) -> dict:
    first = Simulator().run(workflow, {"approved": True})
    if first.status != "failed":
        return {
            "project_id": project_id,
            "repaired": False,
            "reason": "no repairable simulator failure found",
        }

    try:
        result = repairer.repair_from_error(
            workflow,
            failed_node=first.failed_node,
            error=first.error,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    return {
        "project_id": project_id,
        **result.model_dump(mode="json"),
    }
