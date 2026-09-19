from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from backend.tools.gateway import ToolGateway, ToolInvocation
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
    """Graph-driven Workflow IR executor with bounded branching and loops."""

    def __init__(self, agent_runner: Callable[[Node, Any], Any] | None = None) -> None:
        self.agent_runner = agent_runner or self._default_agent_runner
        self.tool_gateway = ToolGateway()

    def run(self, workflow: WorkflowIR, input_data: dict[str, Any] | None = None) -> dict[str, Any]:
        assert_valid_workflow(workflow)

        node_map = {
            workflow.trigger.id: workflow.trigger,
            **{node.id: node for node in workflow.nodes},
        }
        outgoing: dict[str, list[dict[str, Any]]] = {}
        for edge in workflow.edges:
            outgoing.setdefault(edge["from"], []).append(edge)

        payload: Any = dict(input_data or {})
        events: list[RuntimeEvent] = []
        sequence = 0
        terminal_status = "completed"

        def emit(node: Node, status: str, message: str) -> None:
            nonlocal sequence
            sequence += 1
            events.append(RuntimeEvent(sequence, node.id, node.type, status, message))

        def execute_node(node: Node, current: Any) -> tuple[str, Any]:
            if node.type == "trigger":
                emit(node, "completed", f"Trigger accepted ({node.config.get('mode')}).")
                return "completed", current

            if node.type == "human_approval":
                approved = bool(current.get("approved", False)) if isinstance(current, dict) else False
                if not approved:
                    emit(node, "waiting", "Human approval required before continuing.")
                    return "waiting", current
                emit(node, "completed", "Human approval granted.")
                return "completed", current

            if node.type == "agent":
                try:
                    result = self.agent_runner(node, current)
                except Exception as exc:
                    emit(node, "failed", f"Agent failed: {exc}")
                    return "failed", current
                emit(node, "completed", f"Agent completed: {node.config.get('role', node.name)}.")
                return "completed", result

            if node.type == "tool":
                tool_ref = str(node.config.get("tool_ref", ""))
                mode = str(node.config.get("mode", "sandbox"))
                approved = bool(current.get("approved", False)) if isinstance(current, dict) else False
                try:
                    result = self.tool_gateway.invoke(
                        ToolInvocation(tool_id=tool_ref, mode=mode, input=current),
                        approved=approved,
                    )
                except (PermissionError, ValueError, RuntimeError) as exc:
                    emit(node, "failed", str(exc))
                    return "failed", current
                emit(node, "completed", f"Tool {tool_ref} completed.")
                return "completed", result

            if node.type == "condition":
                branch = self._evaluate_condition(node, current if isinstance(current, dict) else {})
                emit(node, "completed", f"Condition evaluated: {branch}.")
                return "completed", {**current, "_branch": branch} if isinstance(current, dict) else {"_branch": branch}

            if node.type == "parallel":
                emit(node, "completed", "Parallel fan-out/fan-in completed.")
                return "completed", current

            if node.type == "loop":
                return self._execute_loop(node, current, node_map, execute_node, emit)

            if node.type == "output":
                emit(node, "completed", f"Output produced ({node.config.get('mode')}).")
                return "completed", current

            raise RuntimeError(f"unsupported node type: {node.type}")

        def walk(start_id: str, current: Any, stop_ids: set[str] | None = None) -> tuple[str, Any, str | None]:
            nonlocal terminal_status
            stop_ids = stop_ids or set()
            current_id = start_id

            while current_id not in stop_ids:
                node = node_map[current_id]
                status, current = execute_node(node, current)

                if status != "completed":
                    terminal_status = status
                    return status, current, current_id

                if node.type == "output":
                    terminal_status = "completed"
                    return "completed", current, node.id

                if node.type == "condition":
                    branch = str(current.get("_branch", "true")) if isinstance(current, dict) else "true"
                    next_id = self._select_condition_edge(outgoing.get(node.id, []), branch)
                    if next_id is None:
                        terminal_status = "completed"
                        return "completed", current, node.id
                    current_id = next_id
                    continue

                if node.type == "parallel":
                    branches = [str(value) for value in node.config.get("branches", [])]
                    join = self._find_parallel_join(branches, outgoing, node_map)
                    merged = dict(current) if isinstance(current, dict) else current
                    for branch in branches:
                        status, branch_payload, _ = walk(branch, dict(merged) if isinstance(merged, dict) else merged, {join} if join else set())
                        if status != "completed":
                            terminal_status = status
                            return status, branch_payload, branch
                        if isinstance(branch_payload, dict):
                            merged.update(branch_payload)
                    current = merged
                    if join is None:
                        return "completed", current, node.id
                    current_id = join
                    continue

                edges = outgoing.get(node.id, [])
                if not edges:
                    return "completed", current, node.id
                current_id = edges[0]["to"]

            return "completed", current, current_id

        status, payload, _ = walk(workflow.trigger.id, payload)
        if status == "completed":
            terminal_status = "completed"

        return {
            "workflow_id": workflow.id,
            "status": terminal_status,
            "output": payload,
            "events": [event.__dict__ for event in events],
        }

    def _execute_loop(
        self,
        node: Node,
        payload: Any,
        node_map: dict[str, Node],
        execute_node: Callable[[Node, Any], tuple[str, Any]],
        emit: Callable[[Node, str, str], None],
    ) -> tuple[str, Any]:
        collection_key = str(node.config.get("collection", "items"))
        body_id = str(node.config.get("body", ""))
        maximum = int(node.config.get("max_iterations", 1))
        collection = payload.get(collection_key, []) if isinstance(payload, dict) else []

        if not isinstance(collection, list):
            emit(node, "failed", f"Loop collection '{collection_key}' is not a list.")
            return "failed", payload

        body_node = node_map.get(body_id)
        if body_node is None:
            emit(node, "failed", f"Loop body node '{body_id}' does not exist.")
            return "failed", payload

        count = min(len(collection), maximum)
        emit(node, "started", f"Loop starting with {count} bounded iteration(s).")
        result = dict(payload) if isinstance(payload, dict) else payload

        for index, item in enumerate(collection[:maximum]):
            iteration_payload = dict(result) if isinstance(result, dict) else {"value": result}
            iteration_payload["loop_item"] = item
            iteration_payload["loop_index"] = index
            status, iteration_result = execute_node(body_node, iteration_payload)
            if status != "completed":
                return status, iteration_result
            if isinstance(iteration_result, dict):
                result = iteration_result

            stop_condition = str(node.config.get("stop_condition", "")).strip().lower()
            if stop_condition == "approved" and bool(result.get("approved")):
                break

        emit(node, "completed", f"Loop completed {min(len(collection), maximum)} iteration(s).")
        return "completed", result

    @staticmethod
    def _select_condition_edge(edges: list[dict[str, Any]], branch: str) -> str | None:
        normalized = branch.lower()
        for edge in edges:
            value = edge.get("condition") or edge.get("label")
            if value is not None and str(value).lower() == normalized:
                return str(edge["to"])
        return str(edges[0]["to"]) if edges else None

    @staticmethod
    def _find_parallel_join(
        branches: list[str],
        outgoing: dict[str, list[dict[str, Any]]],
        node_map: dict[str, Node],
    ) -> str | None:
        if not branches:
            return None
        reachable_sets = []
        for branch in branches:
            seen: set[str] = set()
            frontier = [branch]
            while frontier:
                current = frontier.pop()
                if current in seen:
                    continue
                seen.add(current)
                for edge in outgoing.get(current, []):
                    frontier.append(str(edge["to"]))
            reachable_sets.append(seen)

        common = set.intersection(*reachable_sets) if reachable_sets else set()
        common.difference_update(branches)
        if not common:
            return None

        # Prefer the earliest terminal-ish common node by graph size, then stable id.
        scored = []
        for candidate in common:
            score = sum(1 for edge in outgoing.get(candidate, []) if edge["to"] in common)
            scored.append((score, candidate))
        return sorted(scored)[0][1]

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
        expression = str(node.config.get("expression", "")).strip().lower()
        if expression == "approved":
            return "true" if bool(payload.get("approved")) else "false"
        if expression in payload:
            return "true" if bool(payload[expression]) else "false"
        return "true" if bool(payload) else "false"

    @staticmethod
    def _result(workflow: WorkflowIR, payload: Any, events: list[RuntimeEvent]) -> dict[str, Any]:
        return {
            "workflow_id": workflow.id,
            "status": "waiting" if events and events[-1].status == "waiting" else "completed",
            "output": payload,
            "events": [event.__dict__ for event in events],
        }
