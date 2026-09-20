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
        "artifact_snapshot_id": "snap-repaired",
        "staging_verified": True,
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


def test_control_loop_reports_healthy_runtime_without_recovery():
    from backend.compiler.control_loop import AutonomousControlLoop
    project_id = "control-healthy-test"
    store.record_run(project_id, {
        "kind": "runtime",
        "run_id": "run-ok",
        "status": "completed",
    })

    decision = AutonomousControlLoop().tick(project_id)

    assert decision.status == "healthy"
    assert decision.runtime_run_id == "run-ok"


def test_control_loop_reuses_verified_recovery_and_requires_redeployment_approval():
    from backend.compiler.control_loop import AutonomousControlLoop
    project_id = "control-recovered-test"
    store.record_run(project_id, {
        "kind": "runtime",
        "run_id": "run-failed",
        "status": "failed",
        "error": "timeout",
        "recovery_attempted": True,
        "recovery": {
            "status": "repaired",
            "reason": "verified",
            "attempts": 1,
            "artifact_snapshot_id": "snap-repaired",
            "staging_verified": True,
        },
    })

    decision = AutonomousControlLoop().tick(project_id)

    assert decision.status == "recovered"
    assert decision.requires_approval is True
    assert decision.next_action == "review_and_approve_redeployment"


def test_control_loop_exposes_historical_rollback_after_unrepaired_failure():
    from backend.compiler.control_loop import AutonomousControlLoop
    project_id = "control-rollback-test"
    store.record_run(project_id, {
        "kind": "runtime",
        "run_id": "run-failed",
        "status": "failed",
        "error": "boom",
        "recovery_attempted": True,
        "recovery": {
            "status": "failed",
            "reason": "verification failed",
            "attempts": 2,
        },
    })
    target = {
        "kind": "deployment",
        "deployment_id": "dep-stable",
        "status": "deployed",
        "container_image": "registry/app:stable",
        "artifact_snapshot_id": "snap_stable",
    }
    store.record_run(project_id, target)

    decision = AutonomousControlLoop().tick(project_id)

    assert decision.status == "rollback_available"
    assert decision.rollback_target["deployment_id"] == "dep-stable"
    assert decision.requires_approval is True


def test_control_loop_does_not_recover_again_when_runtime_is_already_handled():
    from backend.compiler.control_loop import AutonomousControlLoop
    project_id = "control-no-repeat-test"
    store.record_run(project_id, {
        "kind": "runtime",
        "run_id": "run-failed",
        "status": "failed",
        "error": "boom",
        "recovery_attempted": True,
        "recovery": {"status": "disabled", "reason": "off"},
    })

    with patch("backend.compiler.control_loop.AutonomousRecoveryEngine.recover") as recover:
        decision = AutonomousControlLoop().tick(project_id)

    recover.assert_not_called()
    assert decision.status == "blocked"


def test_control_tick_endpoint_only_rolls_back_with_explicit_approval():
    from backend.api.runtime import ControlTickRequest, control_tick

    project_id = "control-endpoint-test"
    store.record_run(project_id, {
        "kind": "runtime",
        "run_id": "run-failed",
        "status": "failed",
        "error": "boom",
        "recovery_attempted": True,
        "recovery": {"status": "failed", "reason": "unrepaired"},
    })
    store.record_run(project_id, {
        "kind": "deployment",
        "deployment_id": "dep-stable",
        "status": "deployed",
        "container_image": "registry/app:stable",
        "artifact_snapshot_id": "snap-stable",
    })

    with patch("backend.api.deploy.rollback_generated") as rollback:
        try:
            control_tick(
                project_id,
                ControlTickRequest(approved=False),
            )
        except Exception as exc:
            raise AssertionError(f"unexpected control tick error: {exc}") from exc
        rollback.assert_not_called()

        rollback.return_value = {
            "project_id": project_id,
            "status": "rolled_back",
            "deployment_id": "dep-rollback",
            "rollback_of": "dep-stable",
        }
        result = control_tick(
            project_id,
            ControlTickRequest(approved=True),
        )

    rollback.assert_called_once()
    assert result["status"] == "rolled_back"
    assert result["next_action"] == "observe"


def test_control_tick_redeploys_verified_recovery_only_with_explicit_approval():
    from backend.api.runtime import ControlTickRequest, control_tick

    project_id = "control-redeploy-test"
    store.record_run(project_id, {
        "kind": "runtime",
        "run_id": "run-repair",
        "status": "failed",
        "error": "timeout",
        "recovery_attempted": True,
        "recovery": {
            "status": "repaired",
            "reason": "verified",
            "attempts": 1,
            "artifact_snapshot_id": "snap-repaired",
            "staging_verified": True,
        },
    })

    redeployment = {
        "project_id": project_id,
        "production": {"status": "deployed"},
        "artifact_digest": "sha-repaired",
        "deployment_id": "dep-repaired",
    }

    with patch("backend.api.deploy.deploy_generated", return_value=redeployment) as deploy:
        result = control_tick(
            project_id,
            ControlTickRequest(approved=False),
        )
        deploy.assert_not_called()
        assert result["status"] == "recovered"
        assert result["requires_approval"] is True

        result = control_tick(
            project_id,
            ControlTickRequest(approved=True),
        )

    deploy.assert_called_once()
    request = deploy.call_args.args[1]
    assert request.approved is True
    assert request.recovery_run_id == "run-repair"
    assert request.artifact_snapshot_id == "snap-repaired"
    assert result["status"] == "redeployed"
    assert result["next_action"] == "observe"

    runtime = next(
        item for item in store.get(project_id).runs if item["run_id"] == "run-repair"
    )
    assert runtime["recovery_redeployment"]["status"] == "deployed"
    assert runtime["recovery_redeployment"]["deployment_id"] == "dep-repaired"


def test_control_loop_stops_reapproval_after_redeployment():
    from backend.compiler.control_loop import AutonomousControlLoop

    project_id = "control-redeploy-stable-test"
    store.record_run(project_id, {
        "kind": "runtime",
        "run_id": "run-repaired",
        "status": "failed",
        "recovery": {"status": "repaired"},
        "recovery_redeployment": {
            "status": "deployed",
            "deployment_id": "dep-repaired",
        },
    })

    decision = AutonomousControlLoop().tick(project_id)

    assert decision.status == "redeployed"
    assert decision.requires_approval is False
    assert decision.next_action == "observe"



def test_control_loop_can_escalate_to_full_rebuild():
    from unittest.mock import patch
    from backend.compiler.control_loop import AutonomousControlLoop

    project_id = "control-rebuild-test"
    store.record_run(project_id, {
        "kind": "runtime",
        "run_id": "run-failed-rebuild",
        "status": "failed",
        "error": "architecture mismatch",
        "recovery_attempted": True,
        "recovery": {
            "status": "failed",
            "reason": "source repair exhausted",
            "attempts": 2,
        },
    })

    class Decision:
        status = "rebuilt"
        reason = "new verified build"
        attempts = 1
        build_run_id = "build-new"
        production_ready = True
        staging_verified = True
        route = type("Route", (), {"layer": "architecture"})()
        result = {"production_ready": True}

    with patch(
        "backend.compiler.control_loop.UniversalRepairController.rebuild",
        return_value=Decision(),
    ):
        decision = AutonomousControlLoop().tick(project_id)

    assert decision.status == "rebuild_ready"
    assert decision.requires_approval is True
    assert decision.next_action == "approve_rebuilt_deployment"
    assert decision.rebuild["build_run_id"] == "build-new"


def test_control_loop_full_rebuild_can_be_review_only():
    from unittest.mock import patch
    from backend.compiler.control_loop import AutonomousControlLoop

    project_id = "control-rebuild-review-test"
    store.record_run(project_id, {
        "kind": "runtime",
        "run_id": "run-failed-review",
        "status": "failed",
        "error": "workflow mismatch",
        "recovery_attempted": True,
        "recovery": {
            "status": "failed",
            "reason": "source repair exhausted",
            "attempts": 2,
        },
    })

    class Decision:
        status = "rebuilt"
        reason = "verified but not production-ready"
        attempts = 1
        build_run_id = "build-review"
        production_ready = False
        staging_verified = True
        route = type("Route", (), {"layer": "workflow"})()
        result = {"production_ready": False}

    with patch(
        "backend.compiler.control_loop.UniversalRepairController.rebuild",
        return_value=Decision(),
    ):
        decision = AutonomousControlLoop().tick(project_id)

    assert decision.status == "rebuild_ready"
    assert decision.requires_approval is False
    assert decision.next_action == "review_rebuilt_build"
