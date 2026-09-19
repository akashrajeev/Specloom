from __future__ import annotations

import json
import os
from datetime import datetime, timezone

from mangum import Mangum

from backend.context.store import store
from backend.main import app
from backend.runtime.executor import RuntimeExecutor

_handler = Mangum(app, lifespan="off")


def _executor() -> RuntimeExecutor:
    runtime_mode = os.getenv("SPECL00M_RUNTIME_MODE", "local").lower()
    if runtime_mode == "bedrock":
        from backend.runtime.bedrock_runner import BedrockAgentRunner
        return RuntimeExecutor(agent_runner=BedrockAgentRunner())
    if runtime_mode == "sagemaker":
        from backend.runtime.sagemaker_runner import SageMakerAgentRunner
        return RuntimeExecutor(agent_runner=SageMakerAgentRunner())
    return RuntimeExecutor()


def handler(event, context):
    if isinstance(event, dict) and event.get("source") == "specloom.node":
        detail = event.get("detail", event)
        from backend.runtime.node_worker import NodeWorker

        return NodeWorker().execute(
            project_id=str(detail["project_id"]),
            node_id=str(detail["node_id"]),
            payload=detail.get("input", {}),
        )

    if isinstance(event, dict) and event.get("source") == "specloom.approval":
        detail = event.get("detail", event)
        from backend.runtime.durable import DurableApprovalBroker

        return DurableApprovalBroker().record(
            approval_id=str(detail["approval_id"]),
            project_id=str(detail["project_id"]),
            node_id=str(detail["node_id"]),
            execution_arn=str(detail["execution_arn"]),
            task_token=str(detail["task_token"]),
            input_data=detail.get("input", {}),
        )

    if isinstance(event, dict) and event.get("source") == "aws.events":
        detail = event.get("detail", {})
        project_id = str(detail.get("project_id", "researchhunter"))
        project = store.get(project_id)
        if project.workflow is None:
            return {
                "statusCode": 404,
                "body": json.dumps({"error": "project has no workflow"}),
            }

        input_data = detail.get("input_data") or {}
        result = _executor().run(project.workflow, input_data)
        run_id = f"scheduled_{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S%f')}"
        store.record_run(
            project_id,
            {
                "run_id": run_id,
                "kind": "runtime",
                "trigger": "eventbridge",
                "created_at": datetime.now(timezone.utc).isoformat(),
                "input_data": input_data,
                "workflow_snapshot": project.workflow.model_dump(mode="json"),
                **result,
            },
        )
        return {
            "statusCode": 200,
            "body": json.dumps(
                {"project_id": project_id, "run_id": run_id, **result},
                default=str,
            ),
        }

    return _handler(event, context)
