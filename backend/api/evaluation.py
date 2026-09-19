from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from backend.context.store import store
from backend.workflow.validator import validate_workflow

from backend.evaluation.evaluator import Evaluator
from backend.evaluation.repairer import Repairer
from backend.simulation.executor import Simulator
from backend.workflow.models import WorkflowIR

router = APIRouter(prefix="/api/v1/projects", tags=["evaluation"])
evaluator = Evaluator()
repairer = Repairer()

class RepairApplyRequest(BaseModel):
    workflow: WorkflowIR
    target_node: str
    path: str
    new_value: object


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


@router.post("/{project_id}/repair/apply")
def apply_repair(project_id: str, request: RepairApplyRequest) -> dict:
    if request.path != "config.mode":
        raise HTTPException(status_code=400, detail="only config.mode repairs are currently supported")

    patched = request.workflow.model_copy(deep=True)
    target = next((node for node in patched.nodes if node.id == request.target_node), None)
    if target is None:
        raise HTTPException(status_code=404, detail="repair target node not found")
    if target.type != "tool":
        raise HTTPException(status_code=400, detail="repair target must be a tool node")
    if request.new_value not in {"sandbox", "mock"}:
        raise HTTPException(status_code=400, detail="safe repair mode must be sandbox or mock")

    target.config["mode"] = request.new_value
    errors = validate_workflow(patched)
    if errors:
        raise HTTPException(status_code=422, detail={"validation_errors": errors})

    project = store.save_workflow(project_id, patched)
    return {
        "project_id": project_id,
        "version": len(project.workflow_versions),
        "workflow": patched.model_dump(mode="json"),
        "applied": True,
    }
