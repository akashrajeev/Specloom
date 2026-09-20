from __future__ import annotations

from unittest.mock import patch

from backend.api.build import AutoBuildRequest, autobuild


def test_autobuild_returns_built_result_without_production_approval():
    fake = {
        "ready": True,
        "production_ready": True,
        "staging": {"status": "passed"},
        "artifact_status": {"count": 10},
    }
    with patch("backend.api.build.build", return_value=fake) as build_call:
        result = autobuild(
            "autobuild-test",
            AutoBuildRequest(
                goal="Build a simple generated service.",
                target="artifact",
            ),
        )

    assert result["status"] == "built"
    assert result["build"] == fake
    request_body = build_call.call_args.args[1]
    assert request_body.autonomous is True
    assert request_body.require_staging is False
    assert result["state"]["status"] == "completed"
    assert result["run_id"] == result["state"]["run_id"]
    request_body = build_call.call_args.args[1]
    assert request_body.autonomous is True
    assert request_body.require_staging is False
    assert result["state"]["status"] == "completed"
    assert result["run_id"] == result["state"]["run_id"]


def test_autobuild_stops_before_production_without_approval():
    fake = {
        "ready": True,
        "production_ready": True,
        "staging": {"status": "passed"},
    }
    with patch("backend.api.build.build", return_value=fake) as build_call:
        result = autobuild(
            "autobuild-approval-test",
            AutoBuildRequest(
                goal="Build a deployable generated service.",
                target="production",
                approved=False,
            ),
        )

    assert result["status"] == "awaiting_approval"
    request_body = build_call.call_args.args[1]
    assert request_body.autonomous is True
    assert request_body.require_staging is True
    assert result["state"]["current_stage"] == "promote"
    request_body = build_call.call_args.args[1]
    assert request_body.autonomous is True
    assert request_body.require_staging is True
    assert result["state"]["current_stage"] == "promote"


def test_autobuild_stops_when_production_readiness_is_false():
    fake = {
        "ready": True,
        "production_ready": False,
        "staging": {"status": "passed"},
    }
    with patch("backend.api.build.build", return_value=fake) as build_call:
        result = autobuild(
            "autobuild-readiness-test",
            AutoBuildRequest(
                goal="Build a generated service.",
                target="production",
                approved=True,
            ),
        )

    assert result["status"] == "production_blocked"


def test_autobuild_production_calls_deployer_only_after_gates():
    fake = {
        "ready": True,
        "production_ready": True,
        "staging": {"status": "passed"},
    }
    deployment = {"project_id": "deploy-test", "production": {"status": "deployed"}}

    with patch("backend.api.build.build", return_value=fake), patch(
        "backend.api.deploy.deploy_generated",
        return_value=deployment,
    ) as deploy:
        result = autobuild(
            "deploy-test",
            AutoBuildRequest(
                goal="Build a generated production service.",
                target="production",
                approved=True,
            ),
        )

    assert result["status"] == "deployed"
    deploy.assert_called_once()


def test_autobuild_keeps_unreached_stages_pending_or_skipped_until_build_produces_evidence():
    fake = {
        "ready": True,
        "production_ready": True,
        "research_execution": {"status": "completed"},
        "research_plan": {"tasks": [{"id": "r1"}]},
        "assumptions": [],
        "workflow": {"id": "w1"},
        "artifact_status": {"count": 10},
        "software_verification": {"status": "passed"},
        "software_repair_count": 0,
        "staging": {"status": "skipped"},
        "provisioning": {"ready": False},
        "artifacts": [],
    }
    with patch("backend.api.build.build", return_value=fake):
        result = autobuild(
            "truthful-state-test",
            AutoBuildRequest(goal="Build a generated service.", target="artifact"),
        )

    stages = result["state"]["stages"]
    assert stages["discover"]["status"] == "completed"
    assert stages["research"]["status"] == "completed"
    assert stages["architect"]["status"] == "completed"
    assert stages["compile"]["status"] == "completed"
    assert stages["verify"]["status"] == "completed"
    assert stages["repair"]["status"] == "skipped"
    assert stages["promote"]["status"] == "skipped"
    assert stages["observe"]["status"] == "completed"
    assert "completed_at" in stages["compile"]


def test_autobuild_resume_requires_approval_and_uses_same_run():
    from backend.api.build import AutoBuildResumeRequest, resume_autobuild
    from backend.context.store import store

    project_id = "resume-state-test"
    project = store.get(project_id)
    project.artifacts = {"app.py": "stable"}
    run_id = "run-resume"
    store.record_run(project_id, {
        "kind": "autobuild",
        "run_id": run_id,
        "project_id": project_id,
        "target": "production",
        "status": "awaiting_approval",
        "goal": "Build a generated production service.",
        "stages": {"promote": {"status": "awaiting_approval"}, "observe": {"status": "pending"}},
        "build_proof": {
            "production_ready": True,
            "artifact_hashes": {"app.py": __import__("hashlib").sha256(b"stable").hexdigest()},
        },
    })

    try:
        resume_autobuild(project_id, run_id, AutoBuildResumeRequest(approved=False))
    except Exception as exc:
        assert getattr(exc, "status_code", None) == 403
    else:
        raise AssertionError("resume was not approval-gated")

    project.artifacts = {}
    try:
        resume_autobuild(project_id, run_id, AutoBuildResumeRequest(approved=True))
    except Exception as exc:
        assert getattr(exc, "status_code", None) == 409
    else:
        raise AssertionError("resume accepted changed artifacts")
