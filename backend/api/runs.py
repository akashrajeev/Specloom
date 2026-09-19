from __future__ import annotations

from fastapi import APIRouter

from backend.context.store import store

router = APIRouter(prefix="/api/v1/projects", tags=["runs"])


@router.get("/{project_id}/runs")
def runs(project_id: str, limit: int = 20) -> dict:
    project = store.get(project_id)
    safe_limit = max(1, min(limit, 50))
    return {
        "project_id": project_id,
        "runs": project.runs[:safe_limit],
    }
