from __future__ import annotations

import json
import os
from datetime import datetime, timezone

from mangum import Mangum

from backend.context.store import store
from backend.storage.build_jobs import build_jobs
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
    if isinstance(event, dict) and event.get("source") == "specloom.build":
        detail = event.get("detail", event)
        from backend.api.build import BuildRequestBody, build
        project_id = str(detail["project_id"])
        run_id = str(detail["run_id"])
        try:
            build_jobs.update(
                project_id,
                run_id,
                status="running",
                current_stage="compile",
            )
            store.update_run(
                project_id,
                run_id,
                {
                    "status": "running",
                    "current_stage": "compile",
                },
            )
            result = build(
                project_id,
                BuildRequestBody(
                    goal=str(detail["goal"]),
                    gap_answers=dict(detail.get("gap_answers") or {}),
                ),
            )
            build_jobs.update(
                project_id,
                run_id,
                status="completed",
                current_stage="complete",
                build=result,
                llm=_llm_status(),
            )
            store.update_run(
                project_id,
                run_id,
                {
                    "status": "completed",
                    "current_stage": "complete",
                    "build": result,
                },
            )
            return {"status": "completed", "project_id": project_id, "run_id": run_id}
        except Exception as exc:
            build_jobs.update(
                project_id,
                run_id,
                status="failed",
                current_stage="compile",
                error=str(exc),
                llm=_llm_status(),
            )
            store.update_run(
                project_id,
                run_id,
                {
                    "status": "failed",
                    "current_stage": "compile",
                    "error": str(exc),
                },
            )
            return {"status": "failed", "project_id": project_id, "run_id": run_id, "error": str(exc)}

    if isinstance(event, dict) and event.get("source") == "specloom.loop_guard":
        detail = event.get("detail", event)
        return _loop_guard(detail)

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

    if isinstance(event, dict) and event.get("source") == "aws.events" and (event.get("detail") or {}).get("sweep"):
        from backend.runtime.schedule import sweep
        return {"statusCode": 200, "body": json.dumps(sweep(), default=str)}

    if isinstance(event, dict) and event.get("source") == "aws.events":
        detail = event.get("detail", {})
        project_id = str(detail.get("project_id", "researchhunter"))
        project = store.get(project_id)
        if project.workflow is None:
            return {
                "statusCode": 404,
                "body": json.dumps({"error": "project has no workflow"}),
            }

        if (project.workflow.trigger.config or {}).get("schedule_enabled") is False:
            return {"statusCode": 200, "body": json.dumps({"project_id": project_id, "skipped": "schedule paused"})}

        input_data = detail.get("input_data") or {}
        run_id = f"scheduled_{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S%f')}"
        runtime_mode = os.getenv("SPECL00M_RUNTIME_MODE", "local").lower()
        if runtime_mode == "stepfunctions":
            from backend.runtime.durable import DurableWorkflowManager
            durable = DurableWorkflowManager().start(
                project_id=project_id,
                workflow=project.workflow,
                input_data={**input_data, "specloom_run_id": run_id},
                execution_name=run_id,
            )
            result = {
                "workflow_id": project.workflow.id,
                "status": "running",
                "output": None,
                "events": [],
                "durable": durable,
            }
        else:
            result = _executor().run(project.workflow, input_data)
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



def _llm_status() -> dict:
    try:
        from backend.llm import provider_status
        return provider_status()
    except Exception:  # noqa: BLE001
        return {}


def _loop_guard(detail: dict) -> dict:
    payload = dict(detail.get("input") or {})
    collection_key = str(detail.get("collection") or "items")
    maximum = int(detail.get("max_iterations") or 1)
    values = payload.get(collection_key, [])
    if not isinstance(values, list):
        raise ValueError(f"loop collection '{collection_key}' is not a list")
    payload[collection_key] = values[:maximum]
    payload["_specloom_loop_bound"] = {
        "collection": collection_key,
        "max_iterations": maximum,
        "original_count": len(values),
        "processed_count": min(len(values), maximum),
    }
    return payload
