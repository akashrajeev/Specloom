from __future__ import annotations

import os
from datetime import datetime, timezone

from backend.context.store import store

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from backend.runtime.executor import RuntimeExecutor
from backend.simulation.executor import Simulator
from backend.workflow.models import WorkflowIR

router = APIRouter(prefix="/api/v1/projects", tags=["runtime"])


class RunRequest(BaseModel):
    workflow: WorkflowIR
    input_data: dict = Field(default_factory=dict)


class TriggerRequest(BaseModel):
    input_data: dict = Field(default_factory=dict)


def _runtime_executor() -> RuntimeExecutor:
    runtime_mode = os.getenv("SPECL00M_RUNTIME_MODE", "local").lower()
    if runtime_mode == "bedrock":
        from backend.runtime.bedrock_runner import BedrockAgentRunner
        return RuntimeExecutor(agent_runner=BedrockAgentRunner())
    if runtime_mode == "sagemaker":
        from backend.runtime.sagemaker_runner import SageMakerAgentRunner
        return RuntimeExecutor(agent_runner=SageMakerAgentRunner())
    return RuntimeExecutor()


def _run_and_record(project_id: str, workflow: WorkflowIR, input_data: dict, *, trigger: str) -> dict:
    result = _runtime_executor().run(workflow, input_data)
    run_id = f"run_{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S%f')}"
    store.record_run(
        project_id,
        {
            "run_id": run_id,
            "kind": "runtime",
            "trigger": trigger,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "input_data": input_data,
            "workflow_snapshot": workflow.model_dump(mode="json"),
            **result,
        },
    )
    return {"project_id": project_id, "run_id": run_id, **result}


@router.post("/{project_id}/run")
def run(project_id: str, request: RunRequest) -> dict:
    try:
        store.set_workflow(project_id, request.workflow)
        return _run_and_record(
            project_id,
            request.workflow,
            request.input_data,
            trigger="api",
        )
    except (RuntimeError, ValueError, PermissionError, OSError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/{project_id}/trigger")
def trigger(project_id: str, request: TriggerRequest) -> dict:
    project = store.get(project_id)
    if project.workflow is None:
        raise HTTPException(status_code=404, detail="project has no workflow")

    workflow = project.workflow
    try:
        return _run_and_record(
            project_id,
            workflow,
            request.input_data,
            trigger=str(workflow.trigger.config.get("mode", "manual")),
        )
    except (RuntimeError, ValueError, PermissionError, OSError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/{project_id}/runs/{run_id}/approve")
def approve_and_resume(project_id: str, run_id: str) -> dict:
    project = store.get(project_id)
    pending = next((run for run in project.runs if run.get("run_id") == run_id), None)
    if pending is None:
        raise HTTPException(status_code=404, detail="run not found")
    if pending.get("status") != "waiting":
        raise HTTPException(status_code=409, detail="run is not waiting for approval")

    workflow_payload = pending.get("workflow_snapshot")
    if not workflow_payload:
        if project.workflow is None:
            raise HTTPException(status_code=404, detail="workflow snapshot unavailable")
        workflow_payload = project.workflow.model_dump(mode="json")

    workflow = WorkflowIR.model_validate(workflow_payload)
    input_data = dict(pending.get("input_data") or {})
    input_data["approved"] = True
    run_kind = str(pending.get("kind", "runtime"))

    try:
        if run_kind == "simulation":
            simulation = Simulator().run(workflow, input_data)
            result = simulation.model_dump(mode="json")
        else:
            result = _runtime_executor().run(workflow, input_data)
    except (RuntimeError, ValueError, PermissionError, OSError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    resolved_at = datetime.now(timezone.utc).isoformat()
    resume_id = f"resume_{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S%f')}"
    store.update_run(project_id, run_id, {
        "resolved_at": resolved_at,
        "resolved_by": "human_approval",
        "resolved_run_id": resume_id,
    })

    record = {
        "run_id": resume_id,
        "kind": run_kind,
        "created_at": resolved_at,
        "parent_run_id": run_id,
        "approval": {"approved": True},
        "input_data": input_data,
        "workflow_snapshot": workflow.model_dump(mode="json"),
        **result,
    }
    store.record_run(project_id, record)
    return {
        "project_id": project_id,
        "run_id": resume_id,
        "parent_run_id": run_id,
        **result,
    }
