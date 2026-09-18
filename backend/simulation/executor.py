from __future__ import annotations

from collections import defaultdict
from typing import Any

from backend.workflow.compiler import compile_workflow
from backend.workflow.models import Node, WorkflowIR

from .models import SimulationEvent, SimulationResult


class SimulationError(RuntimeError):
    pass


class Simulator:
    """Deterministic, side-effect-safe executor for validating generated workflows.

    The simulator intentionally uses predictable fixtures instead of calling real
    LLMs or external write APIs. This gives the evaluator a stable environment
    for tests and the UI a reliable execution trace.
    """

    def run(self, ir: WorkflowIR, input_data: dict[str, Any] | None = None) -> SimulationResult:
        payload: Any = dict(input_data or {})
        plan = compile_workflow(ir)
        node_map = {ir.trigger.id: ir.trigger, **{node.id: node for node in ir.nodes}}
        events: list[SimulationEvent] = []
        side_effects: list[dict[str, Any]] = []
        sequence = 0

        for compiled in plan.ordered_nodes:
            node = node_map[compiled.id]
            sequence += 1
            event = self._execute_node(node, payload, sequence)

            events.append(event)

            if event.status == "failed":
                return SimulationResult(
                    workflow_id=ir.id,
                    status="failed",
                    events=events,
                    output=payload,
                    failed_node=node.id,
                    error=event.message,
                    side_effects=side_effects,
                    metrics=self._metrics(events),
                )

            if event.status == "waiting":
                return SimulationResult(
                    workflow_id=ir.id,
                    status="waiting",
                    events=events,
                    output=payload,
                    side_effects=side_effects,
                    metrics=self._metrics(events),
                )

            if event.output_summary is not None:
                payload = event.output_summary

            if node.type == "tool" and node.config.get("mode") == "sandbox":
                side_effects.append(
                    {
                        "tool": node.config.get("tool_ref"),
                        "mode": "sandbox",
                        "result": "simulated side effect; no external write performed",
                    }
                )

        return SimulationResult(
            workflow_id=ir.id,
            status="passed",
            events=events,
            output=payload,
            side_effects=side_effects,
            metrics=self._metrics(events),
        )

    def _execute_node(self, node: Node, payload: Any, sequence: int) -> SimulationEvent:
        node_type = node.type

        if node_type == "trigger":
            return SimulationEvent(
                sequence=sequence,
                node_id=node.id,
                node_type=node_type,
                status="completed",
                message=f"Trigger accepted ({node.config.get('mode')}).",
                duration_ms=40,
                input_summary=payload,
                output_summary=payload,
            )

        if node_type == "agent":
            return self._agent_event(node, payload, sequence)

        if node_type == "tool":
            return self._tool_event(node, payload, sequence)

        if node_type == "human_approval":
            approved = bool(payload.get("approved", False)) if isinstance(payload, dict) else False
            if not approved:
                return SimulationEvent(
                    sequence=sequence,
                    node_id=node.id,
                    node_type=node_type,
                    status="waiting",
                    message="Waiting for human approval before continuing.",
                    duration_ms=0,
                    input_summary=payload,
                    output_summary=None,
                )
            return SimulationEvent(
                sequence=sequence,
                node_id=node.id,
                node_type=node_type,
                status="completed",
                message="Human approval granted.",
                duration_ms=120,
                input_summary=payload,
                output_summary={**payload, "approved": True},
            )

        if node_type == "condition":
            expression = node.config.get("expression", "")
            branch = "true" if bool(payload) else "false"
            return SimulationEvent(
                sequence=sequence,
                node_id=node.id,
                node_type=node_type,
                status="completed",
                message=f"Condition evaluated: {expression or branch}.",
                duration_ms=20,
                input_summary=payload,
                output_summary={**payload, "_branch": branch} if isinstance(payload, dict) else {"_branch": branch, "value": payload},
            )

        if node_type == "parallel":
            return SimulationEvent(
                sequence=sequence,
                node_id=node.id,
                node_type=node_type,
                status="completed",
                message=f"Parallel fan-out simulated across {len(node.config.get('branches', []))} branches.",
                duration_ms=90,
                input_summary=payload,
                output_summary=payload,
            )

        if node_type == "loop":
            max_iterations = int(node.config.get("max_iterations", 0))
            collection_key = str(node.config.get("collection", "items"))
            collection = payload.get(collection_key, []) if isinstance(payload, dict) else []
            iterations = min(len(collection), max_iterations)
            return SimulationEvent(
                sequence=sequence,
                node_id=node.id,
                node_type=node_type,
                status="completed",
                message=f"Loop evaluated {iterations} iteration(s), bounded by {max_iterations}.",
                duration_ms=max(25, iterations * 15),
                input_summary=payload,
                output_summary=payload,
            )

        if node_type == "output":
            return SimulationEvent(
                sequence=sequence,
                node_id=node.id,
                node_type=node_type,
                status="completed",
                message=f"Output prepared ({node.config.get('mode')}).",
                duration_ms=30,
                input_summary=payload,
                output_summary=payload,
            )

        raise SimulationError(f"unsupported node type: {node_type}")

    def _agent_event(self, node: Node, payload: Any, sequence: int) -> SimulationEvent:
        role = str(node.config.get("role", "")).lower()

        if "research" in role:
            items = [
                {"id": "paper-001", "title": "Efficient Tool-Using Agents", "relevant": True},
                {"id": "paper-002", "title": "Unrelated Medical Vision Study", "relevant": False},
                {"id": "paper-003", "title": "Reliable Agent Evaluation", "relevant": True},
                {"id": "paper-004", "title": "Efficient Tool-Using Agents", "relevant": True},
            ]
            return SimulationEvent(
                sequence=sequence, node_id=node.id, node_type=node.type,
                status="completed", message="Found 4 candidate research items.",
                duration_ms=420, input_summary=payload,
                output_summary={"items": items},
            )

        if "relevance" in role or "judge relevance" in role:
            items = payload.get("items", []) if isinstance(payload, dict) else []
            selected = [item for item in items if item.get("relevant")]
            return SimulationEvent(
                sequence=sequence, node_id=node.id, node_type=node.type,
                status="completed", message=f"Selected {len(selected)} relevant candidate(s).",
                duration_ms=280, input_summary=payload,
                output_summary={"items": selected},
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
                sequence=sequence, node_id=node.id, node_type=node.type,
                status="completed", message=f"Collapsed {len(items)} item(s) to {len(unique)} unique item(s).",
                duration_ms=210, input_summary=payload,
                output_summary={"items": unique},
            )

        if "verify" in role:
            items = payload.get("items", []) if isinstance(payload, dict) else []
            verified = [{**item, "verified": True} for item in items]
            return SimulationEvent(
                sequence=sequence, node_id=node.id, node_type=node.type,
                status="completed", message=f"Verified {len(verified)} item(s).",
                duration_ms=260, input_summary=payload,
                output_summary={"items": verified},
            )

        return SimulationEvent(
            sequence=sequence, node_id=node.id, node_type=node.type,
            status="completed", message="Agent completed deterministic simulation fixture.",
            duration_ms=180, input_summary=payload,
            output_summary=payload,
        )

    def _tool_event(self, node: Node, payload: Any, sequence: int) -> SimulationEvent:
        tool_ref = str(node.config.get("tool_ref", "unknown"))
        mode = node.config.get("mode", "mock")

        if mode == "live":
            return SimulationEvent(
                sequence=sequence, node_id=node.id, node_type=node.type,
                status="failed",
                message="Live side effects are blocked by the simulator. Use sandbox or mock mode.",
                duration_ms=5, input_summary=payload,
            )

        if "github.create_issue" in tool_ref:
            count = len(payload.get("items", [])) if isinstance(payload, dict) else 0
            return SimulationEvent(
                sequence=sequence, node_id=node.id, node_type=node.type,
                status="completed",
                message=f"Simulated creation of {count} GitHub issue(s); no external write performed.",
                duration_ms=160,
                input_summary=payload,
                output_summary={**payload, "issues_created": count, "simulated": True},
            )

        return SimulationEvent(
            sequence=sequence, node_id=node.id, node_type=node.type,
            status="completed",
            message=f"Simulated tool call: {tool_ref}.",
            duration_ms=120,
            input_summary=payload,
            output_summary=payload,
        )

    @staticmethod
    def _metrics(events: list[SimulationEvent]) -> dict[str, Any]:
        return {
            "nodes_executed": len(events),
            "duration_ms": sum(event.duration_ms for event in events),
            "completed": sum(event.status == "completed" for event in events),
            "waiting": sum(event.status == "waiting" for event in events),
            "failed": sum(event.status == "failed" for event in events),
        }
