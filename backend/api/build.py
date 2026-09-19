from __future__ import annotations

import os

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from backend.agents.architect import BuildRequest, ConfiguredArchitect
from backend.context.service import analyze_sources
from backend.context.ingestion import ingest_text
from backend.context.gaps import detect_gaps
from backend.context.models import Constraint, Provenance, Requirement
from backend.context.store import store
from backend.workflow.compiler import compile_workflow
from backend.workflow.validator import validate_architecture_coverage
from backend.evaluation.testgen import augment_with_generated_tests
from backend.agents.reviewer import ArchitectureReview, BedrockArchitectureReviewer

router = APIRouter(prefix="/api/v1/projects", tags=["build"])
architect = ConfiguredArchitect()


class BuildRequestBody(BaseModel):
    goal: str = Field(min_length=10, max_length=5000)
    gap_answers: dict[str, str] = Field(default_factory=dict)


@router.post("/{project_id}/build")
def build(project_id: str, request: BuildRequestBody) -> dict:
    project = store.get(project_id)
    existing_gaps = {
        gap.id: gap
        for gap in detect_gaps(request.goal, project.graph)
    }
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
            requirement_ids = {item.id for item in project.graph.requirements}
            constraint_ids = {item.id for item in project.graph.constraints}
            for gap_id, answer in request.gap_answers.items():
                cleaned = answer.strip()
                gap = existing_gaps.get(gap_id)
                if not cleaned or gap is None:
                    continue
                statement = f"User clarification for {gap_id}: {cleaned}"
                provenance = [Provenance(
                    source_id=answer_source.source.id,
                    locator="build-answer",
                    quote=cleaned[:280],
                    confidence=1.0,
                )]
                if gap.category == "safety":
                    item = Constraint(
                        id="con_gap_" + gap_id.replace("-", "_"),
                        statement=statement,
                        severity="blocking",
                        provenance=provenance,
                    )
                    if item.id in constraint_ids:
                        project.graph.constraints = [
                            current if current.id != item.id else item
                            for current in project.graph.constraints
                        ]
                    else:
                        project.graph.constraints.append(item)
                        constraint_ids.add(item.id)
                else:
                    item = Requirement(
                        id="req_gap_" + gap_id.replace("-", "_"),
                        statement=statement,
                        priority="high",
                        provenance=provenance,
                    )
                    if item.id in requirement_ids:
                        project.graph.requirements = [
                            current if current.id != item.id else item
                            for current in project.graph.requirements
                        ]
                    else:
                        project.graph.requirements.append(item)
                        requirement_ids.add(item.id)
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

    review_mode = os.getenv("SPECL00M_REVIEW_MODE", "none").lower()
    review: ArchitectureReview | None = None

    try:
        workflow = architect.build(
            BuildRequest(goal=request.goal, project_id=project_id),
            project.graph,
        )

        max_review_revisions = 2 if review_mode == "bedrock" else 0
        for attempt in range(max_review_revisions + 1):
            workflow = augment_with_generated_tests(workflow, project.graph)
            coverage_errors = validate_architecture_coverage(workflow, project.graph)
            if coverage_errors:
                raise ValueError(
                    "architect produced incomplete coverage: "
                    + "; ".join(coverage_errors)
                )

            # Compile before semantic review so the reviewer never approves a
            # workflow that the local compiler cannot represent.
            plan = compile_workflow(workflow)

            if review_mode != "bedrock":
                review = ArchitectureReview(
                    status="passed",
                    summary="Semantic review disabled; deterministic compiler checks passed.",
                    findings=[],
                )
                break

            reviewer = BedrockArchitectureReviewer()
            review = reviewer.review(
                goal=request.goal,
                context=project.graph,
                workflow=workflow,
            )
            blocking = [
                item.model_dump(mode="json")
                for item in review.findings
                if item.severity == "blocking"
            ]
            if not blocking:
                break
            if attempt >= max_review_revisions:
                raise ValueError(
                    "semantic review rejected the architecture after "
                    f"{max_review_revisions} revision(s): "
                    + "; ".join(item["message"] for item in blocking)
                )
            workflow = architect.revise(
                BuildRequest(goal=request.goal, project_id=project_id),
                project.graph,
                workflow,
                blocking,
            )

        assert review is not None
        # Rebuild the final proof suite after the last revision.
        workflow = augment_with_generated_tests(workflow, project.graph)
        plan = compile_workflow(workflow)
        store.save_workflow(project_id, workflow)
    except (RuntimeError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    return {
        "project_id": project_id,
        "architect_mode": architect.mode,
        "review_mode": review_mode,
        "review": review.model_dump(mode="json") if review else None,
        "workflow": workflow.model_dump(mode="json"),
        "version": len(store.get(project_id).workflow_versions),
        "ready": True,
        "gaps": [],
        "execution_plan": {
            "workflow_id": plan.workflow_id,
            "ordered_nodes": [node.__dict__ for node in plan.ordered_nodes],
        },
    }
