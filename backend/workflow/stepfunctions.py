from __future__ import annotations

import re
from typing import Any

from backend.workflow.models import Node, WorkflowIR


class StepFunctionsCompileError(ValueError):
    pass


def compile_step_functions(
    workflow: WorkflowIR,
    *,
    worker_arn: str,
    approval_arn: str,
    project_id: str,
) -> dict[str, Any]:
    """Compile Workflow IR into Amazon States Language.

    Each agent/tool/condition/loop/output executes as an isolated worker task.
    Step Functions owns graph progression, retries, parallel fan-out/fan-in,
    and human approval suspension. This keeps the IR portable while moving
    orchestration state out of the application process.
    """
    if not worker_arn:
        raise StepFunctionsCompileError("worker_arn is required")
    if not approval_arn:
        raise StepFunctionsCompileError("approval_arn is required")

    node_map = {
        workflow.trigger.id: workflow.trigger,
        **{node.id: node for node in workflow.nodes},
    }
    outgoing = _outgoing(workflow)
    first = outgoing.get(workflow.trigger.id, [])
    if len(first) != 1:
        raise StepFunctionsCompileError(
            "durable compiler currently requires exactly one trigger successor"
        )

    states: dict[str, Any] = {}
    compiled_ids: set[str] = set()
    _compile_path(
        first[0]["to"],
        node_map=node_map,
        outgoing=outgoing,
        root_states=states,
        compiled_ids=compiled_ids,
        worker_arn=worker_arn,
        approval_arn=approval_arn,
        project_id=project_id,
        stop_id=None,
        nested=False,
    )

    return {
        "Comment": f"Specloom durable execution for {workflow.name}",
        "QueryLanguage": "JSONPath",
        "StartAt": _state_name(str(first[0]["to"])),
        "States": states,
    }


def _compile_path(
    start_id: str,
    *,
    node_map: dict[str, Node],
    outgoing: dict[str, list[dict[str, Any]]],
    root_states: dict[str, Any],
    compiled_ids: set[str],
    worker_arn: str,
    approval_arn: str,
    project_id: str,
    stop_id: str | None,
    nested: bool,
) -> None:
    current_id = str(start_id)
    local_seen: set[str] = set()

    while current_id and current_id != stop_id:
        if current_id in local_seen:
            raise StepFunctionsCompileError(
                f"cycle detected while compiling durable path at {current_id}"
            )
        local_seen.add(current_id)

        node = node_map[current_id]
        name = _state_name(current_id)

        if node.type == "condition":
            if not nested:
                _compile_task_state(
                    root_states,
                    node,
                    worker_arn=worker_arn,
                    project_id=project_id,
                    end=False,
                    next_state=f"{name}__route",
                )
                choices = []
                for edge in outgoing.get(node.id, []):
                    branch = str(edge.get("condition") or edge.get("label") or "").strip()
                    if not branch:
                        continue
                    choices.append(
                        {
                            "Variable": "$._branch",
                            "StringEquals": branch,
                            "Next": _state_name(str(edge["to"])),
                        }
                    )
                if not choices:
                    raise StepFunctionsCompileError(
                        f"condition {node.id} has no labeled outgoing branches"
                    )
                root_states[f"{name}__route"] = {
                    "Type": "Choice",
                    "Choices": choices,
                    "Default": choices[0]["Next"],
                }
                for edge in outgoing.get(node.id, []):
                    _compile_path(
                        str(edge["to"]),
                        node_map=node_map,
                        outgoing=outgoing,
                        root_states=root_states,
                        compiled_ids=compiled_ids,
                        worker_arn=worker_arn,
                        approval_arn=approval_arn,
                        project_id=project_id,
                        stop_id=None,
                        nested=False,
                    )
                compiled_ids.add(node.id)
                return

            raise StepFunctionsCompileError(
                f"nested condition node {node.id} is not supported in durable branch compilation"
            )

        if node.type == "parallel":
            if nested:
                raise StepFunctionsCompileError(
                    f"nested parallel node {node.id} is not supported"
                )
            branches = [str(value) for value in node.config.get("branches", [])]
            join = _parallel_join(branches, outgoing)
            if not join:
                raise StepFunctionsCompileError(
                    f"parallel {node.id} requires a common join node"
                )

            parallel_state: dict[str, Any] = {
                "Type": "Parallel",
                "Branches": [],
            }
            for branch in branches:
                branch_states: dict[str, Any] = {}
                _compile_path(
                    branch,
                    node_map=node_map,
                    outgoing=outgoing,
                    root_states=branch_states,
                    compiled_ids=set(),
                    worker_arn=worker_arn,
                    approval_arn=approval_arn,
                    project_id=project_id,
                    stop_id=join,
                    nested=True,
                )
                branch_states = _ensure_branch_terminal(branch_states)
                parallel_state["Branches"].append(
                    {
                        "StartAt": _state_name(branch),
                        "States": branch_states,
                    }
                )

            next_edges = outgoing.get(join, [])
            parallel_state["Next"] = _state_name(join) if next_edges or join in node_map else _state_name(join)
            root_states[name] = parallel_state
            compiled_ids.add(node.id)

            _compile_path(
                join,
                node_map=node_map,
                outgoing=outgoing,
                root_states=root_states,
                compiled_ids=compiled_ids,
                worker_arn=worker_arn,
                approval_arn=approval_arn,
                project_id=project_id,
                stop_id=None,
                nested=False,
            )
            return

        if node.type == "loop":
            if nested:
                raise StepFunctionsCompileError(
                    f"nested loop node {node.id} is not supported in durable branch compilation"
                )
            next_id = _single_next(node.id, outgoing)
            body_id = str(node.config.get("body") or "")
            if body_id not in node_map:
                raise StepFunctionsCompileError(f"loop {node.id} body node {body_id!r} does not exist")
            if node.config.get("stop_condition"):
                raise StepFunctionsCompileError(
                    f"loop {node.id} uses stop_condition, which is not yet portable to durable Map execution"
                )
            map_name = _state_name(node.id)
            _compile_loop_guard_state(
                root_states,
                node,
                worker_arn=worker_arn,
                project_id=project_id,
                next_state=map_name,
            )
            _compile_map_state(
                root_states,
                node,
                body=node_map[body_id],
                worker_arn=worker_arn,
                project_id=project_id,
                end=next_id is None or next_id == stop_id,
                next_state=_state_name(next_id) if next_id and next_id != stop_id else None,
            )
            compiled_ids.add(node.id)
            if next_id:
                _compile_path(
                    next_id,
                    node_map=node_map,
                    outgoing=outgoing,
                    root_states=root_states,
                    compiled_ids=compiled_ids,
                    worker_arn=worker_arn,
                    approval_arn=approval_arn,
                    project_id=project_id,
                    stop_id=stop_id,
                    nested=nested,
                )
            return

        if node.type == "human_approval":
            next_id = _single_next(node.id, outgoing)
            state = {
                "Type": "Task",
                "Resource": "arn:aws:states:::lambda:invoke.waitForTaskToken",
                "Parameters": {
                    "FunctionName": approval_arn,
                    "Payload": {
                        "source": "specloom.approval",
                        "project_id": project_id,
                        "node_id": node.id,
                        "approval_id.$": f"States.Format('{{}}:{node.id}', $$.Execution.Name)",
                        "execution_arn.$": "$$.Execution.Id",
                        "task_token.$": "$$.Task.Token",
                        "input.$": "$",
                    },
                },
            }
            _attach_transition(
                state,
                next_id if next_id != stop_id else None,
                is_terminal=next_id is None or next_id == stop_id,
            )
            _attach_execution_controls(state, node)
            root_states[name] = state
            compiled_ids.add(node.id)
            if next_id:
                _compile_path(
                    next_id,
                    node_map=node_map,
                    outgoing=outgoing,
                    root_states=root_states,
                    compiled_ids=compiled_ids,
                    worker_arn=worker_arn,
                    approval_arn=approval_arn,
                    project_id=project_id,
                    stop_id=stop_id,
                    nested=nested,
                )
            return

        next_id = _single_next(node.id, outgoing)

        if node.type == "output":
            _compile_task_state(
                root_states,
                node,
                worker_arn=worker_arn,
                project_id=project_id,
                end=next_id is None or next_id == stop_id,
                next_state=_state_name(next_id) if next_id and next_id != stop_id else None,
            )
            compiled_ids.add(node.id)
            return

        _compile_task_state(
            root_states,
            node,
            worker_arn=worker_arn,
            project_id=project_id,
            end=next_id is None or next_id == stop_id,
            next_state=_state_name(next_id) if next_id and next_id != stop_id else None,
        )
        compiled_ids.add(node.id)

        if not next_id:
            return
        current_id = next_id



def _compile_loop_guard_state(
    states: dict[str, Any],
    loop: Node,
    *,
    worker_arn: str,
    project_id: str,
    next_state: str,
) -> None:
    guard: dict[str, Any] = {
        "Type": "Task",
        "Resource": "arn:aws:states:::lambda:invoke",
        "Parameters": {
            "FunctionName": worker_arn,
            "Payload": {
                "source": "specloom.loop_guard",
                "project_id": project_id,
                "collection": str(loop.config.get("collection", "items")),
                "max_iterations": int(loop.config["max_iterations"]),
                "input.$": "$",
            },
        },
        "OutputPath": "$.Payload",
        "Next": next_state,
    }
    _attach_execution_controls(guard, loop)
    states[_state_name(f"{loop.id}__guard")] = guard


def _compile_map_state(
    states: dict[str, Any],
    loop: Node,
    *,
    body: Node,
    worker_arn: str,
    project_id: str,
    end: bool,
    next_state: str | None,
) -> None:
    if body.type in {"condition", "parallel", "loop", "human_approval"}:
        raise StepFunctionsCompileError(
            f"durable Map loop body {body.id} must be a single agent/tool/output node"
        )

    maximum = loop.config.get("max_iterations")
    if not isinstance(maximum, int) or not 1 <= maximum <= 1000:
        raise StepFunctionsCompileError(f"loop {loop.id} requires max_iterations between 1 and 1000")

    concurrency = loop.config.get("max_concurrency", 10)
    if not isinstance(concurrency, int) or not 1 <= concurrency <= 40:
        raise StepFunctionsCompileError(f"loop {loop.id} max_concurrency must be between 1 and 40")

    item_state_name = _state_name(f"{loop.id}__item")
    item_state: dict[str, Any] = {
        "Type": "Task",
        "Resource": "arn:aws:states:::lambda:invoke",
        "Parameters": {
            "FunctionName": worker_arn,
            "Payload": {
                "source": "specloom.node",
                "project_id": project_id,
                "node_id": body.id,
                "node_type": body.type,
                "loop_item.$": "$.Map.Item.Value",
                "loop_index.$": "$.Map.Item.Index",
                "input.$": "$.workflow_input",
            },
        },
        "OutputPath": "$.Payload",
        "End": True,
    }
    _attach_execution_controls(item_state, body)

    state: dict[str, Any] = {
        "Type": "Map",
        "ItemsPath": _collection_path(str(loop.config.get("collection", "items"))),
        "MaxConcurrency": concurrency,
        "ItemSelector": {
            "workflow_input.$": "$",
            "loop_item.$": "$.Map.Item.Value",
            "loop_index.$": "$.Map.Item.Index",
        },
        "ItemProcessor": {
            "ProcessorConfig": {"Mode": "INLINE"},
            "StartAt": item_state_name,
            "States": {item_state_name: item_state},
        },
    }
    if end:
        state["End"] = True
    elif next_state:
        state["Next"] = next_state
    state["ResultPath"] = f"$.{_safe_json_path(loop.id)}_results"
    _attach_execution_controls(state, loop)
    states[_state_name(loop.id)] = state


def _safe_json_path(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_]", "_", value)[:60] or "loop"


def _compile_task_state(
    states: dict[str, Any],
    node: Node,
    *,
    worker_arn: str,
    project_id: str,
    end: bool,
    next_state: str | None,
) -> None:
    state: dict[str, Any] = {
        "Type": "Task",
        "Resource": "arn:aws:states:::lambda:invoke",
        "Parameters": {
            "FunctionName": worker_arn,
            "Payload": {
                "source": "specloom.node",
                "project_id": project_id,
                "node_id": node.id,
                "node_type": node.type,
                "input.$": "$",
            },
        },
        "OutputPath": "$.Payload",
    }
    _attach_execution_controls(state, node)
    _attach_transition(state, next_state, is_terminal=end)
    states[_state_name(node.id)] = state


def _attach_transition(state: dict[str, Any], next_state: str | None, *, is_terminal: bool) -> None:
    if is_terminal:
        state["End"] = True
    elif next_state:
        state["Next"] = next_state


def _attach_execution_controls(state: dict[str, Any], node: Node) -> None:
    if node.timeout_seconds:
        state["TimeoutSeconds"] = node.timeout_seconds
    if node.retry:
        state["Retry"] = [
            {
                "ErrorEquals": ["States.ALL"],
                "MaxAttempts": max(1, int(node.retry.max_attempts)),
                "BackoffRate": 2.0,
                "IntervalSeconds": max(1, int(node.retry.backoff_seconds or 1)),
            }
        ]


def _single_next(node_id: str, outgoing: dict[str, list[dict[str, Any]]]) -> str | None:
    edges = outgoing.get(node_id, [])
    if len(edges) > 1:
        raise StepFunctionsCompileError(
            f"node {node_id} has multiple ordinary successors; use condition or parallel"
        )
    return str(edges[0]["to"]) if edges else None


def _parallel_join(
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
    return sorted(common)[0]


def _ensure_branch_terminal(states: dict[str, Any]) -> dict[str, Any]:
    terminal_candidates = [
        name for name, value in states.items()
        if value.get("Next") is None and not value.get("Choices")
        and not value.get("End")
    ]
    for name in terminal_candidates:
        states[name]["End"] = True
    return states


def _outgoing(workflow: WorkflowIR) -> dict[str, list[dict[str, Any]]]:
    outgoing: dict[str, list[dict[str, Any]]] = {}
    for edge in workflow.edges:
        outgoing.setdefault(str(edge["from"]), []).append(edge)
    return outgoing


def _collection_path(value: str) -> str:
    normalized = value.strip()
    if normalized.startswith("$"):
        return normalized
    return "$." + normalized


def _state_name(node_id: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_]", "_", node_id)
    return cleaned[:70] or "State"
