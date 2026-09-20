from __future__ import annotations

from unittest.mock import patch

from backend.compiler.infrastructure import DeploymentExecutionError


def test_generated_production_endpoint_is_approval_gated():
    from backend.api.deploy import GeneratedProductionDeployRequest, deploy_generated

    request = GeneratedProductionDeployRequest(approved=False)
    try:
        deploy_generated("missing-project", request)
    except Exception as exc:
        assert getattr(exc, "status_code", None) == 403
    else:
        raise AssertionError("unapproved production deployment did not fail closed")


def test_deployment_endpoint_does_not_call_executor_when_plan_blocks():
    from backend.api import deploy as deploy_api
    from backend.context.store import store

    project_id = "blocked-deploy-test"
    project = store.get(project_id)
    project.artifacts = {
        "generated/deploy/deployment-plan.json": '{"production_allowed": false, "blocking_reasons": ["not provisioned"]}'
    }

    with patch.object(
        deploy_api,
        "AWSProductionDeployer",
        side_effect=AssertionError("executor must not be constructed"),
    ):
        try:
            deploy_api.deploy_generated(
                project_id,
                deploy_api.GeneratedProductionDeployRequest(approved=True),
            )
        except Exception as exc:
            assert getattr(exc, "status_code", None) == 422
        else:
            raise AssertionError("blocked deployment did not fail closed")
