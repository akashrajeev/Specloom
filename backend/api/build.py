from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from backend.agents.architect import BuildRequest, ConfiguredArchitect
from backend.context.service import analyze_sources
from backend.context.ingestion import ingest_text
from backend.context.gaps import Gap, detect_gaps
from backend.context.models import Provenance, Requirement
from backend.context.store import store
from backend.workflow.compiler import compile_workflow

router = APIRouter(prefix="/api/v1/projects", tags=["build"])
architect = ConfiguredArchitect()


class BuildRequestBody(BaseModel):
    goal: str = Field(min_length=10, max_length=5000)
    gap_answers: dict[str, str] = Field(default_factory=dict)


@router.post("/{project_id}/build")
def build(project_id: str, request: BuildRequestBody) -> dict:
    project = store.get(project_id)
    if request.gap_answers:
        answers = [
            f"Gap {gap_id}: {answer.strip()}"
            for gap_id, answer in request.gap_answers.items()
            if answer.strip()
        ]
        if answers:
            answer_source = ingest_text("Build answers", "\n".join(answers))
            store.add_source(project_id, answer_source)
            project = store.get(project_id)
            for gap_id, answer in request.gap_answers.items():
                cleaned = answer.strip()
                if not cleaned:
                    continue
                statement = f"User clarification for {gap_id}: {cleaned}"
                project.graph.requirements.append(
                    Requirement(
                        id="req_gap_" + gap_id.replace("-", "_"),
                        statement=statement,
                        priority="high",
                        provenance=[Provenance(
                            source_id=answer_source.source.id,
                            locator="build-answer",
                            quote=cleaned[:280],
                            confidence=1.0,
                        )],
                    )
                )
            store.persist(project_id)
    project = store.get(project_id)
    project.graph = analyze_sources(project.graph, project.documents)
    store.persist(project_id)
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
