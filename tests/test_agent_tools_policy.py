from backend.context.models import ContextGraph
from backend.workflow.models import WorkflowIR
from backend.workflow.validator import validate_workflow


def test_agent_write_tool_is_rejected():
    ir = WorkflowIR.model_validate({
        "ir_version": "0.1",
        "id": "agent-write",
        "name": "Agent write",
        "trigger": {
            "id": "start",
            "type": "trigger",
            "name": "Start",
            "config": {"mode": "manual"},
        },
        "nodes": [
            {
                "id": "agent",
                "type": "agent",
                "name": "Agent",
                "config": {
                    "role": "do work",
                    "tools": ["github.create_issue"],
                    "output_mode": "structured",
                },
            },
            {
                "id": "output",
                "type": "output",
                "name": "Output",
                "config": {"mode": "return"},
            },
        ],
        "edges": [{"from": "start", "to": "agent"}, {"from": "agent", "to": "output"}],
        "variables": [],
        "policies": [],
        "tests": [],
    })
    errors = validate_workflow(ir)
    assert any("write-capable tool" in error for error in errors)
