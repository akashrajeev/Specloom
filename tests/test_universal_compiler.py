from __future__ import annotations

import pytest

from backend.capabilities.models import CapabilitySpec
from backend.capabilities.openapi import compile_openapi
from backend.context.models import ContextGraph
from backend.storage.repository import MemoryProjectRepository
from backend.tools.gateway import ToolGateway, ToolInvocation
from backend.workflow.models import WorkflowIR
from backend.workflow.stepfunctions import compile_step_functions


OPENAPI = """
openapi: 3.0.3
info:
  title: Ticket API
  version: 1.0.0
servers:
  - url: https://tickets.example.com
components:
  securitySchemes:
    bearerAuth:
      type: http
      scheme: bearer
security:
  - bearerAuth: []
paths:
  /tickets/{ticket_id}:
    get:
      operationId: get_ticket
      parameters:
        - in: path
          name: ticket_id
          required: true
          schema:
            type: string
      responses:
        "200":
          description: ok
          content:
            application/json:
              schema:
                type: object
  /tickets:
    post:
      operationId: create_ticket
      requestBody:
        required: true
        content:
          application/json:
            schema:
              type: object
              required: [title]
              properties:
                title:
                  type: string
      responses:
        "201":
          description: created
          content:
            application/json:
              schema:
                type: object
"""


def test_openapi_compiler_discovers_read_and_write_capabilities():
    caps = compile_openapi(
        OPENAPI,
        source_id="src_api",
        source_name="Ticket API",
        auth_env="TICKETS_TOKEN",
    )

    get = next(item for item in caps if item.operation_id == "get_ticket")
    create = next(item for item in caps if item.operation_id == "create_ticket")

    assert get.access == "read"
    assert get.method == "GET"
    assert get.path == "/tickets/{ticket_id}"
    assert "ticket_id" in get.input_schema["required"]
    assert get.auth_env == "TICKETS_TOKEN"

    assert create.access == "write"
    assert create.side_effecting is True
    assert create.requires_human_approval is True
    assert "body" in create.input_schema["required"]


def test_openapi_capability_mock_gateway_never_touches_network():
    capability = CapabilitySpec(
        id="apiop:ticket:create",
        kind="openapi",
        name="Create ticket",
        description="Create a ticket",
        method="POST",
        path="/tickets",
        base_url="https://tickets.example.com",
        access="write",
        permissions=["READ", "WRITE"],
        side_effecting=True,
        requires_human_approval=True,
        auth_env="TICKETS_TOKEN",
    )
    result = ToolGateway().invoke(
        ToolInvocation(
            tool_id=capability.id,
            mode="sandbox",
            input={"body": {"title": "test"}},
            capability=capability.model_dump(mode="json"),
        ),
        approved=True,
    )
    assert result["status"] == "simulated"
    assert result["tool"] == capability.id


def test_capability_write_policy_requires_approval():
    workflow = WorkflowIR.model_validate(
        {
            "ir_version": "0.1",
            "id": "api-policy",
            "name": "API policy",
            "trigger": {"id": "start", "type": "trigger", "name": "Start", "config": {"mode": "manual"}},
            "nodes": [
                {
                    "id": "approve",
                    "type": "human_approval",
                    "name": "Approve",
                    "config": {"prompt": "Approve"},
                },
                {
                    "id": "write",
                    "type": "tool",
                    "name": "Create ticket",
                    "policy_ref": "write-policy",
                    "config": {
                        "tool_ref": "apiop:ticket:create",
                        "mode": "sandbox",
                        "capability": {
                            "id": "apiop:ticket:create",
                            "kind": "openapi",
                            "name": "Create ticket",
                            "method": "POST",
                            "path": "/tickets",
                            "base_url": "https://tickets.example.com",
                            "access": "write",
                            "permissions": ["READ", "WRITE"],
                            "side_effecting": True,
                            "requires_human_approval": True,
                        },
                    },
                },
                {"id": "out", "type": "output", "name": "Return", "config": {"mode": "return"}},
            ],
            "edges": [
                {"from": "start", "to": "approve"},
                {"from": "approve", "to": "write"},
                {"from": "write", "to": "out"},
            ],
            "variables": [],
            "policies": [{"id": "write-policy", "rules": ["approval required"]}],
            "tests": [],
        }
    )
    from backend.workflow.validator import validate_workflow
    assert validate_workflow(workflow) == []


def test_durable_loop_compiles_to_map_state():
    workflow = WorkflowIR.model_validate(
        {
            "ir_version": "0.1",
            "id": "map-loop",
            "name": "Map loop",
            "trigger": {"id": "start", "type": "trigger", "name": "Start", "config": {"mode": "manual"}},
            "nodes": [
                {
                    "id": "loop",
                    "type": "loop",
                    "name": "Process items",
                    "config": {"collection": "items", "body": "worker", "max_iterations": 20, "max_concurrency": 4},
                },
                {
                    "id": "worker",
                    "type": "agent",
                    "name": "Process item",
                    "config": {"role": "Process the current loop item."},
                },
                {"id": "out", "type": "output", "name": "Return", "config": {"mode": "return"}},
            ],
            "edges": [
                {"from": "start", "to": "loop"},
                {"from": "loop", "to": "out"},
                {"from": "worker", "to": "out"},
            ],
            "variables": [],
            "policies": [],
            "tests": [],
        }
    )
    compiled = compile_step_functions(
        workflow,
        worker_arn="arn:aws:lambda:us-west-2:123:function:worker",
        approval_arn="arn:aws:lambda:us-west-2:123:function:approval",
        project_id="map-loop",
    )
    state = compiled["States"]["loop"]
    assert state["Type"] == "Map"
    assert state["ItemsPath"] == "$.items"
    assert state["MaxConcurrency"] == 4
    assert "ItemProcessor" in state


def test_workspace_isolation():
    from backend.context.store import ContextStore
    from backend.security.auth import _current_workspace

    store = ContextStore()
    token = _current_workspace.set("workspace-a")
    try:
        project = store.get("shared-project")
        assert project.workspace_id == "workspace-a"
    finally:
        _current_workspace.reset(token)

    token = _current_workspace.set("workspace-b")
    try:
        with pytest.raises(PermissionError):
            store.get("shared-project")
    finally:
        _current_workspace.reset(token)
