from __future__ import annotations

from typing import Any

from backend.workflow.models import Node, WorkflowIR
from backend.workflow.validator import assert_valid_workflow

from .models import SimulationEvent, SimulationResult


class SimulationError(RuntimeError):
    pass


class Simulator:
    """Deterministic, side-effect-safe executor for validating generated workflows."""

    def run(self, ir: WorkflowIR, input_data: dict[str, Any] | None = None) -> SimulationResult:
        assert_valid_workflow(ir)

        node_map = {
            ir.trigger.id: ir.trigger,
            **{node.id: node for node in ir.nodes},
        }
        outgoing: dict[str, list[dict[str, Any]]] = {}
        for edge in ir.edges:
            outgoing.setdefault(str(edge["from"]), []).append(edge)

        payload: Any = dict(input_data or {})
        events: list[SimulationEvent] = []
        side_effects: list[dict[str, Any]] = []
        sequence = 0
        terminal_status = "passed"

        def emit(
            node: Node,
            status: str,
            message: str,
            input_summary: Any,
            output_summary: Any = None,
            duration_ms: int = 0,
        ) -> SimulationEvent:
            nonlocal sequence
            sequence += 1
            event = SimulationEvent(
                sequence=sequence,
                node_id=node.id,
                node_type=node.type,
                status=status,
                message=message,
                duration_ms=duration_ms,
                input_summary=input_summary,
                output_summary=output_summary,
            )
            events.append(event)
            return event

        def execute_node(node: Node, current: Any) -> tuple[str, Any]:
            if node.type == "trigger":
                event = emit(
                    node,
                    "completed",
                    f"Trigger accepted ({node.config.get('mode')}).",
                    current,
                    current,
                    40,
                )
                return "completed", event.output_summary

            if node.type == "agent":
                event = self._agent_event(node, current, sequence + 1)
                events.append(event)
                nonlocal_sequence[0] += 1
                return event.status, event.output_summary if event.output_summary is not None else current

            if node.type == "tool":
                event = self._tool_event(node, current, sequence + 1)
                events.append(event)
                nonlocal_sequence[0] += 1
                if event.status == "completed" and node.config.get("mode") == "sandbox":
                    side_effects.append(
                        {
                            "tool": node.config.get("tool_ref"),
                            "mode": "sandbox",
                            "result": "simulated side effect; no external write performed",
                        }
                    )
                return event.status, event.output_summary if event.output_summary is not None else current

            if node.type == "human_approval":
                approved = bool(current.get("approved", False)) if isinstance(current, dict) else False
                if not approved:
                    event = emit(
                        node,
                        "waiting",
                        "Waiting for human approval before continuing.",
                        current,
                        None,
                        0,
                    )
                    return "waiting", current
                event = emit(
                    node,
                    "completed",
                    "Human approval granted.",
                    current,
                    {**current, "approved": True} if isinstance(current, dict) else current,
                    120,
                )
                return "completed", event.output_summary

            if node.type == "condition":
                branch = self._evaluate_condition(node, current)
                next_payload = (
                    {**current, "_branch": branch}
                    if isinstance(current, dict)
                    else {"_branch": branch, "value": current}
                )
                event = emit(
                    node,
                    "completed",
                    f"Condition evaluated: {branch}.",
                    current,
                    next_payload,
                    20,
                )
                return "completed", event.output_summary

            if node.type == "parallel":
                event = emit(
                    node,
                    "completed",
                    f"Parallel fan-out simulated across {len(node.config.get('branches', []))} branches.",
                    current,
                    current,
                    90,
                )
                return "completed", event.output_summary

            if node.type == "loop":
                collection_key = str(node.config.get("collection", "items"))
                body_id = str(node.config.get("body", ""))
                maximum = int(node.config.get("max_iterations", 0))
                collection = current.get(collection_key, []) if isinstance(current, dict) else []
                if not isinstance(collection, list):
                    emit(
                        node,
                        "failed",
                        f"Loop collection '{collection_key}' is not a list.",
                        current,
                        None,
                        5,
                    )
                    return "failed", current
                body_node = node_map.get(body_id)
                if body_node is None:
                    emit(
                        node,
                        "failed",
                        f"Loop body node '{body_id}' does not exist.",
                        current,
                        None,
                        5,
                    )
                    return "failed", current

                bounded = collection[:maximum]
                emit(
                    node,
                    "started",
                    f"Loop starting with {len(bounded)} bounded iteration(s).",
                    current,
                    current,
                    10,
                )
                result = dict(current) if isinstance(current, dict) else {"value": current}
                for index, item in enumerate(bounded):
                    iteration_payload = {
                        **result,
                        "loop_item": item,
                        "loop_index": index,
                    }
                    status, iteration_result = execute_node(body_node, iteration_payload)
                    if status != "completed":
                        return status, iteration_result
                    if isinstance(iteration_result, dict):
                        result = iteration_result

                emit(
                    node,
                    "completed",
                    f"Loop completed {len(bounded)} iteration(s).",
                    current,
                    result,
                    max(25, len(bounded) * 15),
                )
                return "completed", result

            if node.type == "output":
                event = emit(
                    node,
                    "completed",
                    f"Output prepared ({node.config.get('mode')}).",
                    current,
                    current,
                    30,
                )
                return "completed", event.output_summary

            raise SimulationError(f"unsupported node type: {node.type}")

        # Agent/tool fixture helpers append their own events. Keep sequence monotonic.
        nonlocal_sequence = [sequence]

        def walk(start_id: str, current: Any, stop_ids: set[str] | None = None) -> tuple[str, Any, str | None]:
            nonlocal sequence, terminal_status
            stop_ids = stop_ids or set()
            current_id = start_id

            while current_id not in stop_ids:
                node = node_map[current_id]
                before = len(events)
                status, current = execute_node(node, current)
                if len(events) > before:
                    sequence = max(sequence, events[-1].sequence)

                if status != "completed":
                    terminal_status = status
                    return status, current, current_id

                if node.type == "output":
                    terminal_status = "passed"
                    return "completed", current, node.id

                if node.type == "condition":
                    branch = str(current.get("_branch", "true")) if isinstance(current, dict) else "true"
                    next_id = self._select_condition_edge(outgoing.get(node.id, []), branch)
                    if next_id is None:
                        return "completed", current, node.id
                    current_id = next_id
                    continue

                if node.type == "parallel":
                    branches = [str(value) for value in node.config.get("branches", [])]
                    join = self._find_parallel_join(branches, outgoing)
                    merged = dict(current) if isinstance(current, dict) else current
                    for branch in branches:
                        status, branch_payload, _ = walk(
                            branch,
                            dict(merged) if isinstance(merged, dict) else merged,
                            {join} if join else set(),
                        )
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
                current_id = str(edges[0]["to"])

            return "completed", current, current_id

        status, payload, _ = walk(ir.trigger.id, payload)
        if status == "waiting":
            terminal_status = "waiting"
        elif status == "failed":
            terminal_status = "failed"
        else:
            terminal_status = "passed"

        return SimulationResult(
            workflow_id=ir.id,
            status=terminal_status,
            events=events,
            output=payload,
            failed_node=next(
                (event.node_id for event in events if event.status == "failed"),
                None,
            ),
            error=next(
                (event.message for event in events if event.status == "failed"),
                None,
            ),
            side_effects=side_effects,
            metrics=self._metrics(events),
        )

    def _agent_event(self, node: Node, payload: Any, sequence: int) -> SimulationEvent:
        role = str(node.config.get("role", "")).lower()

        if "research" in role:
            items = [
                {"id": "paper-001", "title": "Efficient Tool-Using Agents", "relevant": True},
                {"id": "paper-002", "title": "Unrelated Medical Vision Study", "relevant": False},
                {"id": "paper-003", "title": "Reliable Agent Evaluation", "relevant": True},
                {"id": "paper-004", "title": "Efficient Tool-Using Agents", "relevant": True},
            ]
            output = {
                "items": items,
                **(
                    {"approved": payload["approved"]}
                    if isinstance(payload, dict) and "approved" in payload
                    else {}
                ),
            }
            return SimulationEvent(
                sequence=sequence,
                node_id=node.id,
                node_type=node.type,
                status="completed",
                message="Found 4 candidate research items.",
                duration_ms=420,
                input_summary=payload,
                output_summary=output,
            )

        if "relevance" in role or "judge relevance" in role:
            items = payload.get("items", []) if isinstance(payload, dict) else []
            selected = [item for item in items if item.get("relevant")]
            output = {
                "items": selected,
                **(
                    {"approved": payload["approved"]}
                    if isinstance(payload, dict) and "approved" in payload
                    else {}
                ),
            }
            return SimulationEvent(
                sequence=sequence,
                node_id=node.id,
                node_type=node.type,
                status="completed",
                message=f"Selected {len(selected)} relevant candidate(s).",
                duration_ms=280,
                input_summary=payload,
                output_summary=output,
            )

        if "dedup" in role:
            items = payload.get("items", []) if isinstance(payload, dict) else []
            seen: set[str] = set()
            unique: list[dict[str, Any]] = []
            for item in items:
                key = str(item.get("title", item.get("id")))
                if key not in seen:
                    seen.add(key)
                    unique.append(item)
            return SimulationEvent(
                sequence=sequence,
                node_id=node.id,
                node_type=node.type,
                status="completed",
                message=f"Collapsed {len(items)} item(s) to {len(unique)} unique item(s).",
                duration_ms=210,
                input_summary=payload,
                output_summary={"items": unique},
            )

        if "verify" in role:
            items = payload.get("items", []) if isinstance(payload, dict) else []
            verified = [{**item, "verified": True} for item in items]
            return SimulationEvent(
                sequence=sequence,
                node_id=node.id,
                node_type=node.type,
                status="completed",
                message=f"Verified {len(verified)} item(s).",
                duration_ms=260,
                input_summary=payload,
                output_summary={"items": verified},
            )

        return SimulationEvent(
            sequence=sequence,
            node_id=node.id,
            node_type=node.type,
            status="completed",
            message="Agent completed deterministic simulation fixture.",
            duration_ms=180,
            input_summary=payload,
            output_summary=payload,
        )

    def _tool_event(self, node: Node, payload: Any, sequence: int) -> SimulationEvent:
        tool_ref = str(node.config.get("tool_ref", "unknown"))
        mode = node.config.get("mode", "mock")

        if mode == "live":
            return SimulationEvent(
                sequence=sequence,
                node_id=node.id,
                node_type=node.type,
                status="failed",
                message="Live side effects are blocked by the simulator. Use sandbox or mock mode.",
                duration_ms=5,
                input_summary=payload,
            )

        if "github.create_issue" in tool_ref:
            count = len(payload.get("items", [])) if isinstance(payload, dict) else 0
            return SimulationEvent(
                sequence=sequence,
                node_id=node.id,
                node_type=node.type,
                status="completed",
                message=f"Simulated creation of {count} GitHub issue(s); no external write performed.",
                duration_ms=160,
                input_summary=payload,
                output_summary={**payload, "issues_created": count, "simulated": True},
            )

        return SimulationEvent(
            sequence=sequence,
            node_id=node.id,
            node_type=node.type,
            status="completed",
            message=f"Simulated tool call: {tool_ref}.",
            duration_ms=120,
            input_summary=payload,
            output_summary=payload,
        )

    @staticmethod
    def _evaluate_condition(node: Node, payload: Any) -> str:
        expression = str(node.config.get("expression", "")).strip().lower()
        if isinstance(payload, dict):
            if expression == "approved":
                return "true" if bool(payload.get("approved")) else "false"
            if expression in payload:
                return "true" if bool(payload[expression]) else "false"
        return "true" if bool(payload) else "false"

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
    ) -> str | None:
        if not branches:
            return None

        reachable_sets: list[set[str]] = []
        for branch in branches:
            seen: set[str] = set()
            frontier = [branch]
            while frontier:
                current = frontier.pop()
                if current in seen:
                    continue
                seen.add(current)
                frontier.extend(str(edge["to"]) for edge in outgoing.get(current, []))
            reachable_sets.append(seen)

        common = set.intersection(*reachable_sets) if reachable_sets else set()
        common.difference_update(branches)
        if not common:
            return None

        scored = []
        for candidate in common:
            internal_children = sum(
                1 for edge in outgoing.get(candidate, [])
                if str(edge["to"]) in common
            )
            scored.append((internal_children, candidate))
        return sorted(scored)[0][1]

    @staticmethod
    def _metrics(events: list[SimulationEvent]) -> dict[str, Any]:
        return {
            "nodes_executed": len(events),
            "duration_ms": sum(event.duration_ms for event in events),
            "completed": sum(event.status == "completed" for event in events),
            "waiting": sum(event.status == "waiting" for event in events),
            "failed": sum(event.status == "failed" for event in events),
        }
