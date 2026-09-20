from unittest.mock import patch

from backend.compiler.universal_repair import (
    RepairRoute,
    UniversalRepairController,
)
from backend.context.store import store


def test_failure_classifier_escalates_systemic_failures():
    workflow = UniversalRepairController.classify(
        {"error": "workflow approval policy mismatch"}
    )
    assert workflow == RepairRoute(
        layer="workflow",
        reason="runtime diagnostics indicate workflow/control-flow semantics",
        rebuild_required=True,
    )

    capability = UniversalRepairController.classify(
        {"error": "tool_ref adapter capability unavailable"}
    )
    assert capability.layer == "capability"
    assert capability.rebuild_required is True

    implementation = UniversalRepairController.classify(
        {"error": "domain implementation returned invalid value"}
    )
    assert implementation.layer == "implementation"
    assert implementation.rebuild_required is False


def test_full_rebuild_is_bounded_and_recorded(monkeypatch):
    monkeypatch.setenv("SPECL00M_AUTOREBUILD_MODE", "on")
    monkeypatch.setenv("SPECL00M_AUTOREBUILD_ATTEMPTS", "2")

    project_id = "universal-rebuild-bounded"
    store.record_run(
        project_id,
        {
            "kind": "runtime",
            "run_id": "runtime-1",
            "status": "failed",
            "error": "architecture mismatch",
        },
    )

    first_result = {
        "ready": True,
        "production_ready": True,
        "artifact_status": {"count": 5},
        "staging": {"status": "passed"},
    }

    with patch(
        "backend.api.build.build",
        return_value=first_result,
    ) as build:
        decision = UniversalRepairController().rebuild(
            project_id,
            run_id="runtime-1",
            failure={"error": "architecture mismatch"},
        )

    build.assert_called_once()
    assert decision.status == "rebuilt"
    assert decision.production_ready is True
    assert decision.staging_verified is True

    runtime = next(
        item
        for item in store.get(project_id).runs
        if item["run_id"] == "runtime-1"
    )
    assert runtime["autonomous_rebuild_attempted"] is True
    assert runtime["autonomous_rebuild_route"] == "architecture"


def test_full_rebuild_refuses_second_attempt_for_same_incident(monkeypatch):
    monkeypatch.setenv("SPECL00M_AUTOREBUILD_MODE", "on")

    project_id = "universal-rebuild-repeat"
    store.record_run(
        project_id,
        {
            "kind": "runtime",
            "run_id": "runtime-2",
            "status": "failed",
            "error": "architecture mismatch",
            "autonomous_rebuild_attempted": True,
        },
    )

    with patch("backend.api.build.build") as build:
        decision = UniversalRepairController().rebuild(
            project_id,
            run_id="runtime-2",
            failure={"error": "architecture mismatch"},
        )

    build.assert_not_called()
    assert decision.status == "blocked"
    assert "already been attempted" in decision.reason


def test_full_rebuild_is_disabled_by_default(monkeypatch):
    monkeypatch.delenv("SPECL00M_AUTOREBUILD_MODE", raising=False)

    decision = UniversalRepairController().rebuild(
        "universal-rebuild-disabled",
        run_id="runtime-3",
        failure={"error": "workflow mismatch"},
    )

    assert decision.status == "disabled"
    assert decision.route is not None
    assert decision.route.layer == "workflow"
