from __future__ import annotations

from fastapi import APIRouter, HTTPException

from backend.context.store import store

router = APIRouter(prefix="/api/v1/projects", tags=["artifacts"])


def _artifact_metadata(path: str, content: str) -> dict[str, object]:
    import hashlib

    return {
        "path": path,
        "size": len(content.encode("utf-8")),
        "sha256": hashlib.sha256(content.encode("utf-8")).hexdigest(),
    }


@router.get("/{project_id}/artifacts")
def list_artifacts(project_id: str) -> dict:
    project = store.get(project_id)
    return {
        "project_id": project_id,
        "count": len(project.artifacts),
        "artifacts": [
            _artifact_metadata(path, content)
            for path, content in sorted(project.artifacts.items())
        ],
    }


@router.get("/{project_id}/artifacts/{artifact_path:path}")
def get_artifact(project_id: str, artifact_path: str) -> dict:
    project = store.get(project_id)
    path = artifact_path.strip("/")
    if not path or path not in project.artifacts:
        raise HTTPException(status_code=404, detail="artifact not found")
    content = project.artifacts[path]
    metadata = _artifact_metadata(path, content)
    return {
        **metadata,
        "content": content,
    }
