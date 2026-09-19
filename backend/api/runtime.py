from __future__ import annotations

import os
from datetime import datetime, timezone

from backend.context.store import store

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from backend.runtime.executor import RuntimeExecutor
from backend.workflow.models import WorkflowIR

router = APIRouter(prefix="/api/v1/projects", tags=["runtime"])


class RunRequest(BaseModel):
    workflow: WorkflowIR
    input_data: dict = Field(default_factory=dict)


@router.post("/{project_id}/run")
def run(project_id: str, request: RunRequest) -> dict:
    try:
        if os.getenv("SPECL00M_RUNTIME_MODE", "local").lower() == "bedrock":
            from backend.runtime.bedrock_runner import BedrockAgentRunner
            executor = RuntimeExecutor(agent_runner=BedrockAgentRunner())
        else:
            executor = RuntimeExecutor()
        result = executor.run(request.workflow, request.input_data)
    except (RuntimeError, ValueError, PermissionError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    run_record = {
        "run_id": f"run_{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S%f')}",
        "kind": "runtime",
        "created_at": datetime.now(timezone.utc).isoformat(),
        **result,
    }
    store.record_run(project_id, run_record)
    return {"project_id": project_id, **result}
