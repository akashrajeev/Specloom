from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from backend.tools.gateway import ToolGateway, ToolInvocation
from backend.workflow.compiler import compile_workflow
from backend.workflow.models import Node, WorkflowIR
from backend.workflow.validator import assert_valid_workflow


@dataclass(frozen=True)
class RuntimeEvent:
    sequence: int
    node_id: str
    node_type: str
    status: str
    message: str


class RuntimeExecutor:
    """Execute validated Workflow IR using deterministic tools and agent runners."""

    def __init__(self, agent_runner: Callable[[Node, Any], Any] | None = None) -> None:
        self.agent_runner = agent_runner or self._default_agent_runner
        self.tool_gateway = ToolGateway()

    def run(self, workflow: WorkflowIR, input_data: dict[str, Any] | None = None) -> dict[str, Any]:
        assert_valid_workflow(workflow)
        plan = compile_workflow(workflow)
        node_map = {workflow.trigger.id: workflow.trigger, **{node.id: node for node in workflow.nodes}}
        payload: Any = dict(input_data or {})
        events: list[RuntimeEvent] = []

        for sequence, compiled in enumerate(plan.ordered_nodes, start=1):
            node = node_map[compiled.id]

            if node.type == "trigger":
                events.append(RuntimeEvent(sequence, node.id, node.type, "completed", "Trigger accepted."))
                continue

            if node.type == "human_approval":
                if not bool(payload.get("approved", False)):
                    events.append(RuntimeEvent(sequence, node.id, node.type, "waiting", "Human approval required."))
                    return self._result(workflow, payload, events)
                events.append(RuntimeEvent(sequence, node.id, node.type, "completed", "Human approval granted."))
                continue

            if node.type == "agent":
                payload = self.agent_runner(node, payload)
                events.append(RuntimeEvent(sequence, node.id, node.type, "completed", "Agent completed."))
                continue

            if node.type == "tool":
                tool_ref = str(node.config.get("tool_ref", ""))
                mode = str(node.config.get("mode", "sandbox"))
                approved = bool(payload.get("approved", False))
                result = self.tool_gateway.invoke(
                    ToolInvocation(tool_id=tool_ref, mode=mode, input=payload),
                    approved=approved,
                )
                payload = result
                events.append(RuntimeEvent(sequence, node.id, node.type, "completed", f"Tool {tool_ref} completed."))
                continue

            if node.type == "condition":
                payload = {**payload, "_branch": self._evaluate_condition(node, payload)}
                events.append(RuntimeEvent(sequence, node.id, node.type, "completed", "Condition evaluated."))
                continue

            if node.type == "parallel":
                events.append(RuntimeEvent(sequence, node.id, node.type, "completed", "Parallel branches accepted by runtime."))
                continue

            if node.type == "loop":
                collection = payload.get(str(node.config.get("collection", "items")), [])
                maximum = int(node.config.get("max_iterations", 1))
                events.append(
                    RuntimeEvent(
                        sequence,
                        node.id,
                        node.type,
                        "completed",
                        f"Loop bounded to {min(len(collection), maximum)} iteration(s).",
                    )
                )
                continue

            if node.type == "output":
                events.append(RuntimeEvent(sequence, node.id, node.type, "completed", "Output produced."))
                return self._result(workflow, payload, events)

        return self._result(workflow, payload, events)

    @staticmethod
    def _default_agent_runner(node: Node, payload: Any) -> Any:
        return {
            "agent": node.id,
            "role": node.config.get("role"),
            "input": payload,
            "status": "completed",
        }

    @staticmethod
    def _evaluate_condition(node: Node, payload: dict[str, Any]) -> str:
        expression = str(node.config.get("expression", "")).strip()
        if expression == "approved":
            return "true" if bool(payload.get("approved")) else "false"
        return "true" if bool(payload) else "false"

    @staticmethod
    def _result(workflow: WorkflowIR, payload: Any, events: list[RuntimeEvent]) -> dict[str, Any]:
        return {
            "workflow_id": workflow.id,
            "status": "waiting" if events and events[-1].status == "waiting" else "completed",
            "output": payload,
            "events": [event.__dict__ for event in events],
        }
