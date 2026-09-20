from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from backend.compiler.infrastructure import AWSDeploymentExecutor, AWSProductionDeployer, DeploymentExecutionError
from backend.compiler.models import Artifact
from backend.context.store import store
from backend.evaluation.evaluator import Evaluator
from backend.workflow.validator import validate_workflow
import os
import hashlib
import uuid
from datetime import datetime, timezone

router = APIRouter(prefix="/api/v1/projects", tags=["deploy"])





class GeneratedProductionDeployRequest(BaseModel):
    approved: bool = False
    recovery_run_id: str | None = Field(default=None, min_length=1, max_length=128)


class DeploymentRollbackRequest(BaseModel):
    approved: bool = False
    deployment_id: str = Field(min_length=1, max_length=128)


def _artifact_hashes(artifacts: list[Artifact]) -> dict[str, str]:
    return {item.path: item.sha256 for item in artifacts}


def _artifact_snapshot_id(artifact_hashes: dict[str, str]) -> str:
    material = "".join(
        f"{path}:{artifact_hashes[path]}\n"
        for path in sorted(artifact_hashes)
    )
    return "snap_" + hashlib.sha256(material.encode("utf-8")).hexdigest()[:24]


def _save_artifact_snapshot(
    project_id: str,
    artifacts: list[Artifact],
) -> str:
    artifact_map = {item.path: item.content for item in artifacts}
    snapshot_id = _artifact_snapshot_id(_artifact_hashes(artifacts))
    store.save_artifact_snapshot(project_id, snapshot_id, artifact_map)
    return snapshot_id


def _record_deployment(
    project_id: str,
    *,
    status: str,
    artifact_digest: str | None,
    container_image: str | None,
    stack_name: str | None,
    region: str | None,
    artifact_hashes: dict[str, str],
    artifact_snapshot_id: str | None = None,
    rollback_of: str | None = None,
    recovery_run_id: str | None = None,
    error: str | None = None,
) -> dict:
    record = {
        "kind": "deployment",
        "deployment_id": uuid.uuid4().hex,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "status": status,
        "artifact_digest": artifact_digest,
        "container_image": container_image,
        "stack_name": stack_name,
        "region": region,
        "artifact_hashes": artifact_hashes,
        "artifact_snapshot_id": artifact_snapshot_id,
        "rollback_of": rollback_of,
        "recovery_run_id": recovery_run_id,
    }
    if error:
        record["error"] = error
    store.record_run(project_id, record)
    return record


def _deployment_history(project_id: str) -> list[dict]:
    return [
        item
        for item in store.get(project_id).runs
        if item.get("kind") == "deployment"
    ]



@router.post("/{project_id}/deploy/generated")
def deploy_generated(
    project_id: str,
    request: GeneratedProductionDeployRequest,
) -> dict:
    if not request.approved:
        raise HTTPException(
            status_code=403,
            detail="generated production deployment requires explicit approval",
        )

    project = store.get(project_id)
    if not project.artifacts:
        raise HTTPException(status_code=404, detail="project has no generated artifacts")

    artifacts: list[Artifact] = []
    for path, content in project.artifacts.items():
        if path.endswith("cloudformation.yaml") or "deploy/" in path:
            kind = "infrastructure"
        elif path.endswith(".json") and "/spec/" in path:
            kind = "spec"
        elif path.endswith(".py") and "/tests/" in path:
            kind = "test"
        else:
            kind = "source"
        artifacts.append(Artifact(path=path, kind=kind, content=content).with_hash())

    deployment_plan = next(
        (item for item in artifacts if item.path == "generated/deploy/deployment-plan.json"),
        None,
    )
    if deployment_plan is None:
        raise HTTPException(status_code=422, detail="generated deployment plan is missing")

    import json
    plan = json.loads(deployment_plan.content)
    if not plan.get("production_allowed"):
        raise HTTPException(
            status_code=422,
            detail={
                "message": "production deployment is blocked by the compiled deployment plan",
                "blocking_reasons": plan.get("blocking_reasons", []),
            },
        )

    try:
        artifact_snapshot_id = _save_artifact_snapshot(project_id, artifacts)
    except (KeyError, ValueError, RuntimeError) as exc:
        raise HTTPException(status_code=422, detail=f"artifact snapshot failed: {exc}") from exc

    try:
        result = AWSProductionDeployer().deploy(artifacts=artifacts, approved=True)
    except DeploymentExecutionError as exc:
        _record_deployment(
            project_id,
            status="failed",
            artifact_digest=plan.get("artifact_digest"),
            container_image=None,
            stack_name=os.getenv("SPECL00M_AWS_STACK_NAME", "specloom-generated-system"),
            region=os.getenv("SPECL00M_AWS_REGION"),
            artifact_hashes=_artifact_hashes(artifacts),
            artifact_snapshot_id=artifact_snapshot_id,
            error=str(exc),
        )
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    record = _record_deployment(
        project_id,
        status="deployed",
        artifact_digest=plan.get("artifact_digest"),
        container_image=result.get("container_image"),
        stack_name=result.get("stack_name"),
        region=result.get("region"),
        artifact_hashes=_artifact_hashes(artifacts),
        artifact_snapshot_id=artifact_snapshot_id,
        recovery_run_id=request.recovery_run_id,
    )
    return {
        "project_id": project_id,
        "production": result,
        "artifact_digest": plan.get("artifact_digest"),
        "deployment_id": record["deployment_id"],
    }


@router.get("/{project_id}/deploy/history")
def deployment_history(project_id: str) -> dict:
    return {
        "project_id": project_id,
        "deployments": _deployment_history(project_id),
    }


@router.post("/{project_id}/deploy/rollback")
def rollback_generated(
    project_id: str,
    request: DeploymentRollbackRequest,
) -> dict:
    if not request.approved:
        raise HTTPException(status_code=403, detail="deployment rollback requires explicit approval")

    project = store.get(project_id)

    target = next(
        (
            item
            for item in _deployment_history(project_id)
            if item.get("deployment_id") == request.deployment_id
            and item.get("status") in {"deployed", "rolled_back"}
        ),
        None,
    )
    if target is None:
        raise HTTPException(status_code=404, detail="deployed rollback target not found")

    target_hashes = target.get("artifact_hashes") or {}
    snapshot_id = str(target.get("artifact_snapshot_id") or "").strip()
    if snapshot_id:
        try:
            snapshot_artifacts = store.get_artifact_snapshot(project_id, snapshot_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="deployment artifact snapshot not found") from exc
        except (ValueError, RuntimeError) as exc:
            raise HTTPException(status_code=422, detail=f"deployment artifact snapshot is invalid: {exc}") from exc

        snapshot_hashes = {
            path: hashlib.sha256(content.encode("utf-8")).hexdigest()
            for path, content in snapshot_artifacts.items()
        }
        if snapshot_hashes != target_hashes:
            raise HTTPException(
                status_code=409,
                detail={
                    "message": "stored deployment snapshot does not match the recorded artifact lineage",
                    "target_artifact_digest": target.get("artifact_digest"),
                },
            )
    else:
        # Legacy deployments created before immutable snapshots existed retain
        # the old fail-closed behavior.
        current_hashes = {
            path: hashlib.sha256(content.encode("utf-8")).hexdigest()
            for path, content in project.artifacts.items()
        }
        if target_hashes != current_hashes:
            raise HTTPException(
                status_code=409,
                detail={
                    "message": "legacy rollback target does not match the current immutable artifact set",
                    "target_artifact_digest": target.get("artifact_digest"),
                },
            )
        snapshot_artifacts = dict(project.artifacts)

    image = str(target.get("container_image") or "").strip()
    if not image:
        raise HTTPException(status_code=422, detail="rollback target has no immutable container image")

    artifacts = [
        Artifact(
            path=path,
            kind="infrastructure" if path.endswith("cloudformation.yaml") else "source",
            content=content,
        ).with_hash()
        for path, content in snapshot_artifacts.items()
    ]

    try:
        result = AWSDeploymentExecutor().deploy(
            artifacts=artifacts,
            approved=True,
            container_image=image,
        )
    except DeploymentExecutionError as exc:
        _record_deployment(
            project_id,
            status="rollback_failed",
            artifact_digest=target.get("artifact_digest"),
            container_image=image,
            stack_name=target.get("stack_name"),
            region=target.get("region"),
            artifact_hashes=target_hashes,
            artifact_snapshot_id=snapshot_id or None,
            rollback_of=target.get("deployment_id"),
            error=str(exc),
        )
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    record = _record_deployment(
        project_id,
        status="rolled_back",
        artifact_digest=target.get("artifact_digest"),
        container_image=image,
        stack_name=result.get("stack_name") or target.get("stack_name"),
        region=result.get("region") or target.get("region"),
        artifact_hashes=target_hashes,
        artifact_snapshot_id=snapshot_id or None,
        rollback_of=target.get("deployment_id"),
    )
    return {
        "project_id": project_id,
        "status": "rolled_back",
        "deployment_id": record["deployment_id"],
        "rollback_of": target.get("deployment_id"),
        "container_image": image,
        "artifact_digest": target.get("artifact_digest"),
    }


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
