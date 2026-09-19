from __future__ import annotations

import json

from mangum import Mangum

from backend.main import app
from backend.context.store import store

_handler = Mangum(app, lifespan="off")


def handler(event, context):
    if isinstance(event, dict) and event.get("source") == "aws.events":
        detail = event.get("detail", {})
        project_id = str(detail.get("project_id", "researchhunter"))
        project = store.get(project_id)
        if project.workflow is None:
            return {
                "statusCode": 404,
                "body": json.dumps({"error": "project has no workflow"}),
            }

        from backend.runtime.executor import RuntimeExecutor

        result = RuntimeExecutor().run(
            project.workflow,
            detail.get("input_data") or {},
        )
        return {
            "statusCode": 200,
            "body": json.dumps(
                {"project_id": project_id, **result},
                default=str,
            ),
        }

    return _handler(event, context)
