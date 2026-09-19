from backend.workflow.models import WorkflowIR
from backend.workflow.stepfunctions import compile_step_functions


def workflow_base(nodes, edges):
    return WorkflowIR.model_validate(
        {
            "ir_version": "0.1",
            "id": "durable",
            "name": "Durable",
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


def test_step_functions_compiles_linear_workflow_with_retry():
    workflow = workflow_base(
        [
            {
                "id": "agent",
                "type": "agent",
                "name": "Analyze",
                "config": {"role": "Analyze", "output_mode": "structured"},
                "retry": {"max_attempts": 3, "backoff_seconds": 2},
                "timeout_seconds": 45,
            },
            {
                "id": "out",
                "type": "output",
                "name": "Return",
                "config": {"mode": "return"},
            },
        ],
        [
            {"from": "start", "to": "agent"},
            {"from": "agent", "to": "out"},
        ],
    )

    definition = compile_step_functions(
        workflow,
        worker_arn="arn:aws:lambda:us-east-1:123:function:specloom-worker",
        approval_arn="arn:aws:lambda:us-east-1:123:function:specloom-approval",
        project_id="demo",
    )

    assert definition["StartAt"] == "agent"
    agent = definition["States"]["agent"]
    assert agent["Type"] == "Task"
    assert agent["TimeoutSeconds"] == 45
    assert agent["Retry"][0]["MaxAttempts"] == 3
    assert agent["Next"] == "out"
    assert definition["States"]["out"]["End"] is True


def test_step_functions_compiles_condition_to_choice_router():
    workflow = workflow_base(
        [
            {
                "id": "condition",
                "type": "condition",
                "name": "Approved?",
                "config": {
                    "expression": "approved",
                    "branches": ["yes", "no"],
                },
            },
            {
                "id": "yes",
                "type": "output",
                "name": "Yes",
                "config": {"mode": "return"},
            },
            {
                "id": "no",
                "type": "output",
                "name": "No",
                "config": {"mode": "return"},
            },
        ],
        [
            {"from": "start", "to": "condition"},
            {"from": "condition", "to": "yes", "condition": "true"},
            {"from": "condition", "to": "no", "condition": "false"},
        ],
    )

    definition = compile_step_functions(
        workflow,
        worker_arn="worker",
        approval_arn="approval",
        project_id="demo",
    )

    router = definition["States"]["condition__route"]
    assert router["Type"] == "Choice"
    assert {item["StringEquals"] for item in router["Choices"]} == {"true", "false"}


def test_step_functions_compiles_parallel_with_join():
    workflow = workflow_base(
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
                "config": {"role": "Left", "output_mode": "structured"},
            },
            {
                "id": "right",
                "type": "agent",
                "name": "Right",
                "config": {"role": "Right", "output_mode": "structured"},
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

    definition = compile_step_functions(
        workflow,
        worker_arn="worker",
        approval_arn="approval",
        project_id="demo",
    )

    parallel = definition["States"]["parallel"]
    assert parallel["Type"] == "Parallel"
    assert len(parallel["Branches"]) == 2
    assert parallel["Next"] == "join"
    for branch in parallel["Branches"]:
        assert branch["States"][branch["StartAt"]]["End"] is True


def test_step_functions_compiles_human_approval_as_callback():
    workflow = workflow_base(
        [
            {
                "id": "approval",
                "type": "human_approval",
                "name": "Review",
                "config": {"prompt": "Approve?", "approvers": ["owner"]},
            },
            {
                "id": "out",
                "type": "output",
                "name": "Return",
                "config": {"mode": "return"},
            },
        ],
        [
            {"from": "start", "to": "approval"},
            {"from": "approval", "to": "out"},
        ],
    )

    definition = compile_step_functions(
        workflow,
        worker_arn="worker",
        approval_arn="approval",
        project_id="demo",
    )

    state = definition["States"]["approval"]
    assert state["Resource"] == "arn:aws:states:::lambda:invoke.waitForTaskToken"
    assert state["Parameters"]["Payload"]["task_token.$"] == "$$.Task.Token"
    assert state["Next"] == "out"


def test_step_functions_compiles_bounded_loop_as_worker_task():
    workflow = workflow_base(
        [
            {
                "id": "loop",
                "type": "loop",
                "name": "Process items",
                "config": {
                    "collection": "items",
                    "body": "body",
                    "max_iterations": 7,
                },
            },
            {
                "id": "body",
                "type": "agent",
                "name": "Process",
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

    definition = compile_step_functions(
        workflow,
        worker_arn="worker",
        approval_arn="approval",
        project_id="demo",
    )

    loop_state = definition["States"]["loop"]
    assert loop_state["Type"] == "Map"
    assert loop_state["ItemsPath"] == "$.items"
    assert loop_state["MaxConcurrency"] >= 1
    item_states = loop_state["ItemProcessor"]["States"]
    item_state = next(iter(item_states.values()))
    assert item_state["Parameters"]["Payload"]["node_type"] == "agent"
    assert loop_state["ItemProcessor"]["StartAt"] in item_states
    assert loop_state["Next"] == "out"
