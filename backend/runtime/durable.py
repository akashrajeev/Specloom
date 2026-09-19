from __future__ import annotations

import json
import os
import re
from typing import Any

import boto3

from backend.workflow.models import WorkflowIR
from backend.workflow.stepfunctions import compile_step_functions


class DurableConfigurationError(RuntimeError):
    pass


class DurableWorkflowManager:
    """Create/update and start a Standard Step Functions state machine per project."""

    def __init__(
        self,
        *,
        role_arn: str | None = None,
        worker_arn: str | None = None,
        approval_arn: str | None = None,
    ) -> None:
        self.role_arn = role_arn or os.getenv("SPECL00M_STEP_FUNCTIONS_ROLE_ARN", "")
        self.worker_arn = worker_arn or os.getenv("SPECL00M_STEP_FUNCTIONS_WORKER_ARN", "")
        self.approval_arn = approval_arn or os.getenv(
            "SPECL00M_STEP_FUNCTIONS_APPROVAL_ARN",
            self.worker_arn,
        )
        self.name_prefix = os.getenv("SPECL00M_STEP_FUNCTIONS_NAME_PREFIX", "specloom")
        self.client = boto3.client("stepfunctions")

    def ensure(self, project_id: str, workflow: WorkflowIR) -> dict[str, Any]:
        if not self.role_arn:
            raise DurableConfigurationError("SPECL00M_STEP_FUNCTIONS_ROLE_ARN is required")
        if not self.worker_arn:
            raise DurableConfigurationError("SPECL00M_STEP_FUNCTIONS_WORKER_ARN is required")

        definition = compile_step_functions(
            workflow,
            worker_arn=self.worker_arn,
            approval_arn=self.approval_arn,
            project_id=project_id,
        )
        name = self._machine_name(project_id)

        existing = self._find(name)
        if existing:
            response = self.client.update_state_machine(
                stateMachineArn=existing["stateMachineArn"],
                definition=json.dumps(definition, separators=(",", ":")),
                roleArn=self.role_arn,
            )
            return {
                "state_machine_arn": existing["stateMachineArn"],
                "name": name,
                "updated": True,
                "definition": definition,
                "revision_id": response.get("updateDate"),
            }

        response = self.client.create_state_machine(
            name=name,
            definition=json.dumps(definition, separators=(",", ":")),
            roleArn=self.role_arn,
            type="STANDARD",
            tags=[
                {"key": "Application", "value": "Specloom"},
                {"key": "ProjectId", "value": project_id},
                {"key": "WorkflowId", "value": workflow.id},
            ],
        )
        return {
            "state_machine_arn": response["stateMachineArn"],
            "name": name,
            "created": True,
            "definition": definition,
        }

    def start(
        self,
        *,
        project_id: str,
        workflow: WorkflowIR,
        input_data: dict[str, Any] | None = None,
        execution_name: str | None = None,
    ) -> dict[str, Any]:
        ensured = self.ensure(project_id, workflow)
        name = execution_name or self._execution_name(workflow)
        response = self.client.start_execution(
            stateMachineArn=ensured["state_machine_arn"],
            name=name,
            input=json.dumps(input_data or {}, separators=(",", ":")),
        )
        return {
            "state_machine_arn": ensured["state_machine_arn"],
            "execution_arn": response["executionArn"],
            "start_date": response.get("startDate"),
            "status": "RUNNING",
        }

    def describe(self, execution_arn: str) -> dict[str, Any]:
        response = self.client.describe_execution(executionArn=execution_arn)
        return {
            "execution_arn": execution_arn,
            "status": response.get("status"),
            "start_date": response.get("startDate"),
            "stop_date": response.get("stopDate"),
            "output": _parse_json(response.get("output")),
            "error": response.get("error"),
            "cause": response.get("cause"),
        }

    def _find(self, name: str) -> dict[str, Any] | None:
        token = None
        while True:
            kwargs = {}
            if token:
                kwargs["nextToken"] = token
            response = self.client.list_state_machines(**kwargs)
            for item in response.get("stateMachines", []):
                if item.get("name") == name:
                    return item
            token = response.get("nextToken")
            if not token:
                return None

    def _machine_name(self, project_id: str) -> str:
        clean = re.sub(r"[^A-Za-z0-9_-]", "-", project_id).strip("-") or "project"
        return f"{self.name_prefix}-{clean}"[:80]

    @staticmethod
    def _execution_name(workflow: WorkflowIR) -> str:
        base = re.sub(r"[^A-Za-z0-9_-]", "-", workflow.id).strip("-") or "workflow"
        return f"{base}-{os.urandom(6).hex()}"[:80]


def _parse_json(value: Any) -> Any:
    if not value:
        return None
    try:
        return json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return value
