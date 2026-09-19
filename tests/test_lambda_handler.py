from __future__ import annotations

import os
import sys
import types

from backend.context.store import store
from backend.lambda_handler import handler
from backend.workflow.loader import load_workflow


def test_lambda_routes_scheduled_event_to_durable_runtime(monkeypatch):
    workflow = load_workflow("examples/showcase-workflow.json")
    project_id = "scheduled-durable-test"
    store.set_workflow(project_id, workflow)

    class FakeManager:
        def __init__(self):
            pass

        def start(self, **kwargs):
            assert kwargs["project_id"] == project_id
            assert kwargs["workflow"].id == workflow.id
            assert kwargs["input_data"]["source"] == "schedule"
            return {
                "state_machine_arn": "arn:aws:states:example",
                "execution_arn": "arn:aws:states:exec:123",
                "status": "RUNNING",
            }

    fake_runtime = types.ModuleType("backend.runtime.durable")
    fake_runtime.DurableWorkflowManager = FakeManager
    monkeypatch.setitem(sys.modules, "backend.runtime.durable", fake_runtime)
    monkeypatch.setenv("SPECL00M_RUNTIME_MODE", "stepfunctions")

    response = handler(
        {
            "source": "aws.events",
            "detail": {
                "project_id": project_id,
                "input_data": {"source": "schedule"},
            },
        },
        None,
    )

    assert response["statusCode"] == 200
    payload = __import__("json").loads(response["body"])
    assert payload["status"] == "running"
    assert payload["durable"]["execution_arn"] == "arn:aws:states:exec:123"


def test_lambda_routes_node_worker_event_to_node_worker(monkeypatch):
    class FakeWorker:
        def execute(self, **kwargs):
            assert kwargs["project_id"] == "node-test"
            assert kwargs["node_id"] == "agent"
            assert kwargs["payload"] == {"value": 1}
            return {"value": 2}

    fake_worker = types.ModuleType("backend.runtime.node_worker")
    fake_worker.NodeWorker = FakeWorker
    monkeypatch.setitem(sys.modules, "backend.runtime.node_worker", fake_worker)

    result = handler(
        {
            "source": "specloom.node",
            "project_id": "node-test",
            "node_id": "agent",
            "input": {"value": 1},
        },
        None,
    )

    assert result == {"value": 2}
