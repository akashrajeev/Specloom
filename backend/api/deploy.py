from __future__ import annotations

from fastapi import APIRouter

from backend.context.store import store
from backend.evaluation.evaluator import Evaluator
from backend.workflow.validator import validate_workflow
import os

router = APIRouter(prefix="/api/v1/projects", tags=["deploy"])



@router.get("/{project_id}/deploy/plan")
def deploy_plan(project_id: str) -> dict:
    """Return the exact production state-machine artifact Specloom would deploy."""
    project = store.get(project_id)
    if project.workflow is None:
        raise HTTPException(status_code=404, detail="project has no workflow")
    worker_arn = os.getenv("SPECL00M_STEP_FUNCTIONS_WORKER_ARN", "").strip()
    approval_arn = os.getenv("SPECL00M_STEP_FUNCTIONS_APPROVAL_ARN", "").strip() or worker_arn
    if not worker_arn:
        return {
            "project_id": project_id,
            "ready": False,
            "target": "aws_step_functions",
            "error": "SPECL00M_STEP_FUNCTIONS_WORKER_ARN is not configured",
        }
    try:
        from backend.workflow.stepfunctions import compile_step_functions
        definition = compile_step_functions(
            project.workflow,
            worker_arn=worker_arn,
            approval_arn=approval_arn,
            project_id=project_id,
        )
    except (ValueError, RuntimeError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {
        "project_id": project_id,
        "workflow_id": project.workflow.id,
        "ready": True,
        "target": "aws_step_functions",
        "worker_arn": worker_arn,
        "approval_arn": approval_arn or None,
        "definition": definition,
    }


@router.get("/{project_id}/deploy/check")
def deploy_check(project_id: str) -> dict:
    project = store.get(project_id)
    workflow = project.workflow

    checks: list[dict[str, object]] = []
    checks.append({
        "id": "workflow",
        "label": "Workflow is valid",
        "status": "pass" if workflow and not validate_workflow(workflow) else "fail",
    })

    if workflow:
        evaluation = Evaluator().evaluate(workflow)
        checks.append({
            "id": "tests",
            "label": "Generated tests pass",
            "status": "pass" if evaluation.status == "passed" else "fail",
            "detail": f"{evaluation.passed}/{len(evaluation.tests)} passed",
        })
    else:
        checks.append({"id": "tests", "label": "Generated tests pass", "status": "fail"})

    storage_mode = os.getenv("SPECL00M_STORAGE_MODE", "memory").lower()
    persistence_ready = (
        storage_mode == "aws"
        and bool(os.getenv("SPECL00M_DDB_TABLE"))
        and bool(os.getenv("SPECL00M_S3_BUCKET"))
    )
    checks.append({
        "id": "persistence",
        "label": "Durable AWS persistence configured",
        "status": "pass" if persistence_ready else "warn",
        "detail": storage_mode,
    })

    runtime_mode = os.getenv("SPECL00M_RUNTIME_MODE", "local").lower()
    runtime_ready = runtime_mode in {"local", "bedrock"} or (
        runtime_mode == "sagemaker"
        and bool(os.getenv("SPECL00M_SAGEMAKER_ENDPOINT_NAME"))
    ) or (
        runtime_mode == "stepfunctions"
        and bool(os.getenv("SPECL00M_STEP_FUNCTIONS_ROLE_ARN"))
        and bool(os.getenv("SPECL00M_STEP_FUNCTIONS_WORKER_ARN"))
        and bool(os.getenv("SPECL00M_STEP_FUNCTIONS_APPROVAL_ARN"))
    )
    checks.append({
        "id": "runtime",
        "label": "Agent runtime configured",
        "status": "pass" if runtime_ready else "warn",
        "detail": runtime_mode,
    })

    public_url = os.getenv("SPECL00M_PUBLIC_URL", "").strip()
    checks.append({
        "id": "public-url",
        "label": "Public URL configured",
        "status": "pass" if public_url else "warn",
        "detail": public_url or "Deploy frontend and set SPECL00M_PUBLIC_URL",
    })

    return {
        "project_id": project_id,
        "ready": all(item["status"] in {"pass", "warn"} for item in checks)
        and all(item["status"] != "fail" for item in checks),
        "checks": checks,
    }
