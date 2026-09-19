from __future__ import annotations

import os
from typing import Any

from backend.context.store import store
from backend.tools.gateway import ToolGateway, ToolInvocation
from backend.workflow.models import Node
from backend.workflow.validator import assert_valid_workflow


class NodeExecutionError(RuntimeError):
    pass


class NodeWorker:
    """Execute one validated Workflow IR node for durable Step Functions tasks."""

    def __init__(self) -> None:
        self.gateway = ToolGateway()

    def execute(
        self,
        *,
        project_id: str,
        node_id: str,
        payload: Any,
    ) -> dict[str, Any]:
        project = store.get(project_id)
        if project.workflow is None:
            raise NodeExecutionError("project has no workflow")

        workflow = project.workflow
        assert_valid_workflow(workflow)

        if isinstance(payload, dict) and payload.get("_specloom_map_iteration"):
            original = payload.get("input", {})
            if isinstance(original, dict):
                payload = {
                    **original,
                    "loop_item": payload.get("loop_item"),
                    "loop_index": payload.get("loop_index"),
                }

        node = next((item for item in workflow.nodes if item.id == node_id), None)
        if node is None:
            if workflow.trigger.id == node_id:
                node = workflow.trigger
            else:
                raise NodeExecutionError(f"workflow node not found: {node_id}")

        status, output = self._execute(node, payload)
        if status != "completed":
            raise NodeExecutionError(str(output))

        return output


    def _execute(self, node: Node, payload: Any) -> tuple[str, Any]:
        if node.type == "trigger":
            return "completed", payload

        if node.type == "agent":
            try:
                from backend.runtime.bedrock_runner import BedrockAgentRunner
                result = BedrockAgentRunner()(node, payload)
            except ImportError:
                result = {
                    "agent": node.id,
                    "role": node.config.get("role"),
                    "input": payload,
                    "status": "completed",
                }
            if isinstance(payload, dict) and isinstance(result, dict):
                control = {
                    key: payload[key]
                    for key in ("approved", "run_id")
                    if key in payload
                }
                result = {**control, **result}
            return "completed", result

        if node.type == "tool":
            tool_ref = str(node.config.get("tool_ref", ""))
            mode = str(node.config.get("mode", "sandbox"))
            approved = bool(payload.get("approved", False)) if isinstance(payload, dict) else False
            try:
                result = self.gateway.invoke(
                    ToolInvocation(
                        tool_id=tool_ref,
                        mode=mode,
                        input=payload,
                        capability=node.config.get("capability"),
                    ),
                    approved=approved,
                )
            except (PermissionError, ValueError, RuntimeError) as exc:
                return "failed", str(exc)
            return "completed", result

        if node.type == "condition":
            expression = str(node.config.get("expression", "")).strip().lower()
            branch = "true"
            if isinstance(payload, dict):
                if expression == "approved":
                    branch = "true" if bool(payload.get("approved")) else "false"
                elif expression in payload:
                    branch = "true" if bool(payload.get(expression)) else "false"
                else:
                    branch = "true" if bool(payload) else "false"
            return "completed", {
                **payload,
                "_branch": branch,
            } if isinstance(payload, dict) else {"_branch": branch, "value": payload}

        if node.type == "loop":
            collection_key = str(node.config.get("collection", "items"))
            body_id = str(node.config.get("body", ""))
            maximum = int(node.config.get("max_iterations", 1))
            collection = payload.get(collection_key, []) if isinstance(payload, dict) else []
            if not isinstance(collection, list):
                return "failed", f"loop collection '{collection_key}' is not a list"
            project_context = store.get(project_id)
            body = (
                next((item for item in project_context.workflow.nodes if item.id == body_id), None)
                if project_context.workflow
                else None
            )
            if body is None:
                return "failed", f"loop body node '{body_id}' does not exist"
            result = dict(payload) if isinstance(payload, dict) else {"value": payload}
            for index, item in enumerate(collection[:maximum]):
                iteration = {**result, "loop_item": item, "loop_index": index}
                status, iteration_result = self._execute(body, iteration)
                if status != "completed":
                    return status, iteration_result
                if isinstance(iteration_result, dict):
                    result = iteration_result
            return "completed", result

        if node.type == "output":
            return "completed", payload

        if node.type == "parallel":
            return "completed", payload

        if node.type == "human_approval":
            return "failed", "human approval is handled by the durable approval state, not the node worker"

        raise NodeExecutionError(f"unsupported node type: {node.type}")
