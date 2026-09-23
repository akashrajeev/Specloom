from __future__ import annotations

from fastapi import APIRouter

from backend.context.store import store

router = APIRouter(prefix="/api/v1/projects", tags=["projects"])


@router.get("")
def list_projects(limit: int = 50) -> dict:
    """Projects that hold at least one built workflow, newest version summary first."""
    limit = max(1, min(limit, 100))
    items = []
    project_ids = list(store.list_project_ids(limit=limit))
    # The seeded default project exists even before anything is saved for it.
    if "researchhunter" not in project_ids:
        project_ids.insert(0, "researchhunter")
    for project_id in project_ids[:limit]:
        try:
            project = store.get(project_id)
        except PermissionError:
            continue
        workflow = project.workflow
        items.append({
            "project_id": project_id,
            "name": workflow.name if workflow else project_id,
            "goal": workflow.description if workflow else None,
            "workflow_id": workflow.id if workflow else None,
            "node_count": len(workflow.nodes) if workflow else 0,
            "workflow_versions": len(project.workflow_versions),
            "run_count": len(project.runs),
        })
    return {"projects": items}


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
