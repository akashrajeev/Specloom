from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from backend.agents.architect import BuildRequest, ConfiguredArchitect
from backend.context.service import analyze_sources
from backend.context.gaps import detect_gaps
from backend.context.store import store
from backend.workflow.compiler import compile_workflow

router = APIRouter(prefix="/api/v1/projects", tags=["build"])
architect = ConfiguredArchitect()


class BuildRequestBody(BaseModel):
    goal: str = Field(min_length=10, max_length=5000)


@router.post("/{project_id}/build")
def build(project_id: str, request: BuildRequestBody) -> dict:
    project = store.get(project_id)
    project.graph = analyze_sources(project.graph, project.documents)
    gaps = detect_gaps(request.goal, project.graph)
    if any(gap.severity == "blocking" for gap in gaps):
        return {
            "project_id": project_id,
            "ready": False,
            "architect_mode": architect.mode,
            "gaps": [gap.__dict__ for gap in gaps],
        }

    try:
        workflow = architect.build(
            BuildRequest(goal=request.goal, project_id=project_id),
            project.graph,
        )
        plan = compile_workflow(workflow)
        store.save_workflow(project_id, workflow)
    except (RuntimeError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    return {
        "project_id": project_id,
        "architect_mode": architect.mode,
        "workflow": workflow.model_dump(mode="json"),
        "version": len(store.get(project_id).workflow_versions),
        "ready": True,
        "gaps": [],
        "execution_plan": {
            "workflow_id": plan.workflow_id,
            "ordered_nodes": [node.__dict__ for node in plan.ordered_nodes],
        },
    }
