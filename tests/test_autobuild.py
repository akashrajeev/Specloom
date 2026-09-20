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
