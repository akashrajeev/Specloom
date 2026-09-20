from unittest.mock import patch

from backend.context.models import ContextGraph
from backend.context.store import store
from backend.runtime.executor import RuntimeExecutor
from backend.workflow.models import Node, Trigger, WorkflowIR


def _workflow() -> WorkflowIR:
    return WorkflowIR(
        ir_version="0.1",
        id="recovery-test",
        name="Recovery test",
        description="Repair a generated runtime after a failed execution.",
        trigger=Trigger(
            id="start",
            type="trigger",
            name="Start",
            config={"mode": "manual"},
        ),
        nodes=[
            Node(
                id="agent",
                type="agent",
                name="Agent",
                config={"role": "Do work"},
            ),
            Node(
                id="output",
                type="output",
                name="Output",
                config={"mode": "return"},
            ),
        ],
        edges=[
            {"from": "start", "to": "agent"},
            {"from": "agent", "to": "output"},
        ],
        variables=[],
        policies=[],
        tests=[],
    )


def test_failed_runtime_execution_invokes_autonomous_recovery():
    project_id = "runtime-recovery-test"
    workflow = _workflow()
    store.set_workflow(project_id, workflow)
    store.get(project_id).artifacts = {
        "generated/repository/app/api.py": "from fastapi import FastAPI\n",
    }

    recovery = {
        "status": "repaired",
        "reason": "verified",
        "attempts": 1,
        "errors": [],
    }

    with patch("backend.api.runtime.RuntimeExecutor.run", return_value={
        "workflow_id": workflow.id,
        "status": "failed",
        "output": {},
        "events": [{"sequence": 1, "status": "failed", "message": "boom"}],
    }), patch(
        "backend.api.runtime.AutonomousRecoveryEngine.recover"
    ) as recover:
        recover.return_value = type("Decision", (), recovery)()
        from backend.api.runtime import _run_and_record
        result = _run_and_record(
            project_id,
            workflow,
            {"input": "x"},
            trigger="test",
        )

    recover.assert_called_once()
    assert result["recovery"]["status"] == "repaired"
    run = next(item for item in store.get(project_id).runs if item["run_id"] == result["run_id"])
    assert run["recovery_attempted"] is True


def test_recovery_is_bounded_and_configuration_gated(monkeypatch):
    from backend.compiler.recovery import AutonomousRecoveryEngine

    monkeypatch.setenv("SPECL00M_AUTORECOVERY_MODE", "off")
    engine = AutonomousRecoveryEngine()
    decision = engine.recover(
        "recovery-disabled",
        run_id="run-1",
        failure={"error": "boom"},
    )
    assert decision.status == "disabled"
    assert decision.attempts == 0
