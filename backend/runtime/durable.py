from __future__ import annotations

import json
import os
import re
from typing import Any

from backend.workflow.models import WorkflowIR

from backend.storage.dynamodb import from_dynamodb, to_dynamodb
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
        import boto3
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
        validation = self.client.validate_state_machine_definition(
            definition=json.dumps(definition, separators=(",", ":")),
            type="STANDARD",
        )
        if validation.get("result") != "OK":
            diagnostics = validation.get("diagnostics", [])
            raise DurableConfigurationError(
                "generated Step Functions definition failed AWS validation: "
                + json.dumps(diagnostics, separators=(",", ":"))
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
                "revision_id": _iso(response.get("updateDate")),
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
            "start_date": _iso(response.get("startDate")),
            "status": "RUNNING",
        }

    def describe(self, execution_arn: str) -> dict[str, Any]:
        response = self.client.describe_execution(executionArn=execution_arn)
        return {
            "execution_arn": execution_arn,
            "status": response.get("status"),
            "start_date": _iso(response.get("startDate")),
            "stop_date": _iso(response.get("stopDate")),
            "output": _parse_json(response.get("output")),
            "error": response.get("error"),
            "cause": response.get("cause"),
        }

    def history(self, execution_arn: str, workflow: WorkflowIR | None = None) -> list[dict[str, Any]]:
        response_events: list[dict[str, Any]] = []
        next_token: str | None = None
        state_map: dict[str, tuple[str, str]] = {}
        if workflow is not None:
            nodes = [workflow.trigger, *workflow.nodes]
            from backend.workflow.stepfunctions import _state_name
            state_map = {
                _state_name(node.id): (node.id, node.type)
                for node in nodes
            }
            state_map.update({
                f"{_state_name(node.id)}__route": (node.id, "condition")
                for node in workflow.nodes
                if node.type == "condition"
            })

        while True:
            kwargs: dict[str, Any] = {
                "executionArn": execution_arn,
                "maxResults": 100,
                "includeExecutionData": False,
            }
            if next_token:
                kwargs["nextToken"] = next_token
            page = self.client.get_execution_history(**kwargs)
            response_events.extend(page.get("events", []))
            next_token = page.get("nextToken")
            if not next_token:
                break
            if len(response_events) >= 1000:
                break

        result: list[dict[str, Any]] = []
        for event in response_events[-1000:]:
            event_type = str(event.get("type", ""))
            details = event.get("stateEnteredEventDetails") or event.get("stateExitedEventDetails")
            if not isinstance(details, dict):
                details = event.get("choiceStateEnteredEventDetails") or event.get("parallelStateEnteredEventDetails")
            state_name = str(details.get("name")) if isinstance(details, dict) and details.get("name") else ""
            node_id, node_type = state_map.get(state_name, (state_name, "control"))

            status = None
            message = None
            if "StateEntered" in event_type or event_type.endswith("StateEntered"):
                status = "started"
                message = f"{state_name or event_type} entered."
            elif "StateExited" in event_type or event_type.endswith("StateExited"):
                status = "completed"
                message = f"{state_name or event_type} exited successfully."
            elif event_type in {"ExecutionFailed", "ExecutionAborted", "ExecutionTimedOut"}:
                status = "failed"
                failure = event.get("executionFailedEventDetails") or {}
                message = str(failure.get("cause") or failure.get("error") or event_type)
                node_id = node_id or execution_arn
                node_type = "execution"

            if status:
                result.append(
                    {
                        "sequence": len(result) + 1,
                        "node_id": node_id,
                        "node_type": node_type,
                        "status": status,
                        "message": message or status,
                    }
                )
        return result

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


def _iso(value: Any) -> Any:
    """boto returns datetimes; stored run records (DynamoDB) need plain strings."""
    return value.isoformat() if hasattr(value, "isoformat") else value


def _parse_json(value: Any) -> Any:
    if not value:
        return None
    try:
        return json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return value


class DurableApprovalBroker:
    """Persist Step Functions callback tokens so approvals survive process restarts."""

    def __init__(self, table_name: str | None = None) -> None:
        import boto3
        self.table_name = table_name or os.getenv("SPECL00M_APPROVALS_TABLE", "")
        if not self.table_name:
            raise DurableConfigurationError("SPECL00M_APPROVALS_TABLE is required")
        self.table = boto3.resource("dynamodb").Table(self.table_name)
        self.sfn = boto3.client("stepfunctions")

    def record(
        self,
        *,
        approval_id: str,
        project_id: str,
        node_id: str,
        execution_arn: str,
        task_token: str,
        input_data: Any,
    ) -> dict[str, Any]:
        self.table.put_item(
            Item={
                "approval_id": approval_id,
                "project_id": project_id,
                "node_id": node_id,
                "execution_arn": execution_arn,
                "task_token": task_token,
                "input_data": to_dynamodb(input_data or {}),
                "status": "pending",
                "expires_at": int(__import__("time").time()) + 7 * 24 * 60 * 60,
            }
        )
        from backend.notify import telegram
        telegram.send_approval_request(
            approval_id=approval_id, project_id=project_id, node_id=node_id, input_data=input_data,
        )
        return {
            "status": "pending",
            "approval_id": approval_id,
            "project_id": project_id,
            "node_id": node_id,
        }

    def list_pending(self, *, project_id: str, limit: int = 20) -> list[dict[str, Any]]:
        response = self.table.query(
            IndexName="ProjectStatusIndex",
            KeyConditionExpression="project_id = :project_id AND #status = :pending",
            ExpressionAttributeNames={"#status": "status"},
            ExpressionAttributeValues={
                ":project_id": project_id,
                ":pending": "pending",
            },
            Limit=max(1, min(limit, 50)),
        )
        return [
            {
                "approval_id": item.get("approval_id"),
                "run_id": str(item.get("approval_id", "")).rsplit(":", 1)[0],
                "project_id": item.get("project_id"),
                "node_id": item.get("node_id"),
                "execution_arn": item.get("execution_arn"),
                "status": item.get("status"),
                "input_data": item.get("input_data") or {},
            }
            for item in response.get("Items", [])
        ]

    def _resolve(
        self,
        *,
        project_id: str,
        approval_id: str,
        decision: str,
        output_payload: dict[str, Any],
    ) -> dict[str, Any]:
        item = self.table.get_item(Key={"approval_id": approval_id}).get("Item")
        if not item or item.get("project_id") != project_id:
            raise DurableConfigurationError("pending durable approval not found")
        if item.get("status") != "pending":
            raise DurableConfigurationError("durable approval has already been resolved")

        try:
            self.table.update_item(
                Key={"approval_id": approval_id},
                UpdateExpression="SET #status = :resolving",
                ConditionExpression="#status = :pending",
                ExpressionAttributeNames={"#status": "status"},
                ExpressionAttributeValues={
                    ":resolving": "resolving",
                    ":pending": "pending",
                },
            )
        except self.table.meta.client.exceptions.ConditionalCheckFailedException as exc:
            raise DurableConfigurationError("durable approval has already been resolved") from exc

        try:
            if decision == "approved":
                self.sfn.send_task_success(
                    taskToken=str(item["task_token"]),
                    output=json.dumps(output_payload, separators=(",", ":")),
                )
            else:
                self.sfn.send_task_failure(
                    taskToken=str(item["task_token"]),
                    error="HumanRejected",
                    cause=str(output_payload.get("reason") or "Human approval rejected"),
                )
        except Exception:
            self.table.update_item(
                Key={"approval_id": approval_id},
                UpdateExpression="SET #status = :pending",
                ExpressionAttributeNames={"#status": "status"},
                ExpressionAttributeValues={":pending": "pending"},
            )
            raise

        self.table.update_item(
            Key={"approval_id": approval_id},
            UpdateExpression="SET #status = :resolved, resolved_at = :resolved_at",
            ExpressionAttributeNames={"#status": "status"},
            ExpressionAttributeValues={
                ":resolved": decision,
                # DynamoDB rejects Python floats; store an ISO timestamp.
                ":resolved_at": __import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat(),
            },
        )
        return {
            "approval_id": approval_id,
            "project_id": project_id,
            "execution_arn": item.get("execution_arn"),
            "status": decision,
        }

    def approve(self, *, project_id: str, approval_id: str) -> dict[str, Any]:
        return self._resolve(
            project_id=project_id,
            approval_id=approval_id,
            decision="approved",
            output_payload={**dict(self._input(approval_id, project_id) or {}), "approved": True},
        )

    def reject(self, *, project_id: str, approval_id: str, reason: str = "") -> dict[str, Any]:
        return self._resolve(
            project_id=project_id,
            approval_id=approval_id,
            decision="rejected",
            output_payload={"reason": reason or "Human approval rejected"},
        )

    def _input(self, approval_id: str, project_id: str) -> dict[str, Any]:
        item = self.table.get_item(Key={"approval_id": approval_id}).get("Item")
        if not item or item.get("project_id") != project_id:
            raise DurableConfigurationError("pending durable approval not found")
        return dict(item.get("input_data") or {})
