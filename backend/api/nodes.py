from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from backend.context.store import store
from backend.workflow.models import WorkflowIR
from backend.workflow.validator import validate_workflow

router = APIRouter(prefix="/api/v1/projects", tags=["nodes"])


class NodeModeUpdate(BaseModel):
    mode: Literal["mock", "sandbox", "live"]


@router.patch("/{project_id}/nodes/{node_id}/mode")
def update_node_mode(project_id: str, node_id: str, request: NodeModeUpdate) -> dict:
    project = store.get(project_id)
    if project.workflow is None:
        raise HTTPException(status_code=404, detail="project has no workflow")

    patched = WorkflowIR.model_validate(project.workflow.model_dump(mode="json"))
    node = next((item for item in patched.nodes if item.id == node_id), None)
    if node is None:
        raise HTTPException(status_code=404, detail="node not found")
    if node.type != "tool":
        raise HTTPException(status_code=400, detail="only tool node modes can be changed")

    node.config["mode"] = request.mode
    errors = validate_workflow(patched)
    if errors:
        raise HTTPException(status_code=422, detail={"validation_errors": errors})

    saved = store.save_workflow(project_id, patched)
    return {
        "project_id": project_id,
        "version": len(saved.workflow_versions),
        "workflow": patched.model_dump(mode="json"),
    }
