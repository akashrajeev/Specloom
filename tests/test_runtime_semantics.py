from backend.runtime.executor import RuntimeExecutor
from backend.workflow.models import WorkflowIR


def workflow(body):
    return WorkflowIR.model_validate(body)


def test_condition_selects_matching_edge():
    ir = workflow({
        "ir_version": "0.1",
        "id": "condition-test",
        "name": "Condition test",
        "trigger": {"id": "start", "type": "trigger", "name": "Start", "config": {"mode": "manual"}},
        "nodes": [
            {"id": "check", "type": "condition", "name": "Check", "config": {"expression": "approved", "branches": ["true", "false"]}},
            {"id": "yes", "type": "output", "name": "Approved", "config": {"mode": "return"}},
            {"id": "no", "type": "output", "name": "Rejected", "config": {"mode": "return"}},
        ],
        "edges": [
            {"from": "start", "to": "check"},
            {"from": "check", "to": "yes", "condition": "true"},
            {"from": "check", "to": "no", "condition": "false"},
        ],
        "variables": [],
        "policies": [],
        "tests": [],
    })

    result = RuntimeExecutor().run(ir, {"approved": False})
    assert result["status"] == "completed"
    assert [event["node_id"] for event in result["events"]] == ["start", "check", "no"]


def test_loop_executes_bounded_body():
    ir = workflow({
        "ir_version": "0.1",
        "id": "loop-test",
        "name": "Loop test",
        "trigger": {"id": "start", "type": "trigger", "name": "Start", "config": {"mode": "manual"}},
        "nodes": [
            {"id": "loop", "type": "loop", "name": "Loop", "config": {"collection": "items", "body": "body", "max_iterations": 2}},
            {"id": "body", "type": "agent", "name": "Body", "config": {"role": "process item", "output_mode": "structured"}},
            {"id": "out", "type": "output", "name": "Output", "config": {"mode": "return"}},
        ],
        "edges": [
            {"from": "start", "to": "loop"},
            {"from": "loop", "to": "out"},
        ],
        "variables": [],
        "policies": [],
        "tests": [],
    })

    result = RuntimeExecutor().run(ir, {"items": ["a", "b", "c"]})
    ids = [event["node_id"] for event in result["events"]]
    assert result["status"] == "completed"
    assert ids.count("body") == 2
    assert ids[-1] == "out"


def test_parallel_fans_out_and_fans_in():
    ir = workflow({
        "ir_version": "0.1",
        "id": "parallel-test",
        "name": "Parallel test",
        "trigger": {"id": "start", "type": "trigger", "name": "Start", "config": {"mode": "manual"}},
        "nodes": [
            {"id": "fan", "type": "parallel", "name": "Parallel", "config": {"branches": ["left", "right"]}},
            {"id": "left", "type": "agent", "name": "Left", "config": {"role": "left", "output_mode": "structured"}},
            {"id": "right", "type": "agent", "name": "Right", "config": {"role": "right", "output_mode": "structured"}},
            {"id": "out", "type": "output", "name": "Output", "config": {"mode": "return"}},
        ],
        "edges": [
            {"from": "start", "to": "fan"},
            {"from": "fan", "to": "left"},
            {"from": "fan", "to": "right"},
            {"from": "left", "to": "out"},
            {"from": "right", "to": "out"},
        ],
        "variables": [],
        "policies": [],
        "tests": [],
    })

    result = RuntimeExecutor().run(ir, {})
    ids = [event["node_id"] for event in result["events"]]
    assert result["status"] == "completed"
    assert ids.count("left") == 1
    assert ids.count("right") == 1
    assert ids.count("out") == 1
