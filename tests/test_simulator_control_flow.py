from backend.simulation.executor import Simulator
from backend.workflow.models import WorkflowIR


def _workflow(nodes, edges):
    return WorkflowIR.model_validate(
        {
            "ir_version": "0.1",
            "id": "control-flow",
            "name": "Control flow",
            "trigger": {
                "id": "start",
                "type": "trigger",
                "name": "Start",
                "config": {"mode": "manual"},
            },
            "nodes": nodes,
            "edges": edges,
            "variables": [],
            "policies": [],
            "tests": [],
        }
    )


def test_simulator_honors_condition_branch():
    workflow = _workflow(
        [
            {
                "id": "condition",
                "type": "condition",
                "name": "Approved?",
                "config": {
                    "expression": "approved",
                    "branches": ["approved", "rejected"],
                },
            },
            {
                "id": "approved",
                "type": "output",
                "name": "Approved",
                "config": {"mode": "return"},
            },
            {
                "id": "rejected",
                "type": "output",
                "name": "Rejected",
                "config": {"mode": "return"},
            },
        ],
        [
            {"from": "start", "to": "condition"},
            {"from": "condition", "to": "approved", "condition": "true"},
            {"from": "condition", "to": "rejected", "condition": "false"},
        ],
    )

    result = Simulator().run(workflow, {"approved": False})
    assert result.status == "passed"
    assert [event.node_id for event in result.events][-1] == "rejected"


def test_simulator_executes_parallel_branches_before_join():
    workflow = _workflow(
        [
            {
                "id": "parallel",
                "type": "parallel",
                "name": "Parallel",
                "config": {"branches": ["left", "right"]},
            },
            {
                "id": "left",
                "type": "agent",
                "name": "Left",
                "config": {"role": "Left branch", "output_mode": "structured"},
            },
            {
                "id": "right",
                "type": "agent",
                "name": "Right",
                "config": {"role": "Right branch", "output_mode": "structured"},
            },
            {
                "id": "join",
                "type": "output",
                "name": "Join",
                "config": {"mode": "return"},
            },
        ],
        [
            {"from": "start", "to": "parallel"},
            {"from": "left", "to": "join"},
            {"from": "right", "to": "join"},
            {"from": "parallel", "to": "join"},
        ],
    )

    result = Simulator().run(workflow, {})
    assert result.status == "passed"
    event_ids = [event.node_id for event in result.events]
    assert event_ids.index("left") < event_ids.index("join")
    assert event_ids.index("right") < event_ids.index("join")


def test_simulator_respects_bounded_loop():
    workflow = _workflow(
        [
            {
                "id": "loop",
                "type": "loop",
                "name": "Loop",
                "config": {
                    "collection": "items",
                    "body": "body",
                    "max_iterations": 2,
                },
            },
            {
                "id": "body",
                "type": "agent",
                "name": "Body",
                "config": {"role": "Process item", "output_mode": "structured"},
            },
            {
                "id": "out",
                "type": "output",
                "name": "Return",
                "config": {"mode": "return"},
            },
        ],
        [
            {"from": "start", "to": "loop"},
            {"from": "loop", "to": "out"},
        ],
    )

    result = Simulator().run(workflow, {"items": ["a", "b", "c"]})
    assert result.status == "passed"
    body_events = [event for event in result.events if event.node_id == "body"]
    assert len(body_events) == 2
