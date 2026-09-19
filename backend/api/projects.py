from __future__ import annotations

from fastapi import APIRouter

from backend.context.store import store

router = APIRouter(prefix="/api/v1/projects", tags=["projects"])


@router.get("/{project_id}")
def get_project(project_id: str) -> dict:
    project = store.get(project_id)
    return {
        "project_id": project_id,
        "context": project.graph.model_dump(mode="json"),
        "workflow": project.workflow.model_dump(mode="json") if project.workflow else None,
        "workflow_versions": len(project.workflow_versions),
        "artifact_count": len(project.artifacts),
    }
