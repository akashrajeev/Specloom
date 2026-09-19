from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from backend.context.store import store
from backend.provenance.service import build_node_provenance, build_workflow_provenance

router = APIRouter(prefix="/api/v1/projects", tags=["provenance"])


@router.get("/{project_id}/provenance")
def provenance(project_id: str, node_id: str | None = Query(default=None)) -> dict:
    project = store.get(project_id)
    if project.workflow is None:
        raise HTTPException(status_code=404, detail="project has no generated workflow")

    try:
        if node_id:
            return build_node_provenance(project.graph, project.workflow, node_id)
        return build_workflow_provenance(project.graph, project.workflow)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
