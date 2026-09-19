from __future__ import annotations

from fastapi import APIRouter, HTTPException

from backend.context.store import store

router = APIRouter(prefix="/api/v1/projects", tags=["versions"])


@router.get("/{project_id}/versions")
def versions(project_id: str) -> dict:
    project = store.get(project_id)
    active_id = project.workflow.id if project.workflow else None
    return {
        "project_id": project_id,
        "active_workflow_id": active_id,
        "versions": [
            {
                "version": index + 1,
                "workflow_id": workflow.id,
                "name": workflow.name,
                "description": workflow.description,
                "active": workflow.id == active_id,
            }
            for index, workflow in enumerate(project.workflow_versions)
        ],
    }


@router.post("/{project_id}/versions/{version}/activate")
def activate_version(project_id: str, version: int) -> dict:
    project = store.get(project_id)
    if version < 1 or version > len(project.workflow_versions):
        raise HTTPException(status_code=404, detail="workflow version not found")

    workflow = project.workflow_versions[version - 1]
    store.set_workflow(project_id, workflow)
    return {
        "project_id": project_id,
        "version": version,
        "workflow": workflow.model_dump(mode="json"),
    }
