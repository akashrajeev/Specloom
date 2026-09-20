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


def test_successful_generated_deploy_records_immutable_lineage():
    from backend.api import deploy as deploy_api
    from backend.context.store import store

    project_id = "lineage-deploy-test"
    store.get(project_id).artifacts = {
        "generated/deploy/cloudformation.yaml": "template",
        "generated/deploy/deployment-plan.json": '{"production_allowed": true, "artifact_digest": "sha-test"}',
        "generated/repository/app/main.py": "print('ok')",
    }

    fake_result = {
        "status": "deployed",
        "stack_name": "stack-test",
        "region": "ap-south-1",
        "container_image": "123.dkr.ecr.ap-south-1.amazonaws.com/app:abc123",
    }
    with patch.object(deploy_api.AWSProductionDeployer, "deploy", return_value=fake_result):
        result = deploy_api.deploy_generated(
            project_id,
            deploy_api.GeneratedProductionDeployRequest(approved=True),
        )

    assert result["deployment_id"]
    history = deploy_api.deployment_history(project_id)["deployments"]
    assert history[0]["deployment_id"] == result["deployment_id"]
    assert history[0]["artifact_digest"] == "sha-test"
    assert history[0]["container_image"] == fake_result["container_image"]
    assert history[0]["artifact_hashes"]["generated/deploy/cloudformation.yaml"]


def test_rollback_requires_matching_immutable_artifacts():
    from backend.api import deploy as deploy_api
    from backend.context.store import store

    project_id = "rollback-lineage-test"
    store.get(project_id).artifacts = {
        "generated/deploy/cloudformation.yaml": "current-template",
    }
    store.record_run(project_id, {
        "kind": "deployment",
        "deployment_id": "dep-old",
        "status": "deployed",
        "artifact_digest": "old",
        "container_image": "registry/app:old",
        "stack_name": "stack-old",
        "region": "ap-south-1",
        "artifact_hashes": {"generated/deploy/cloudformation.yaml": "not-current"},
    })

    try:
        deploy_api.rollback_generated(
            project_id,
            deploy_api.DeploymentRollbackRequest(
                approved=True,
                deployment_id="dep-old",
            ),
        )
    except Exception as exc:
        assert getattr(exc, "status_code", None) == 409
    else:
        raise AssertionError("rollback accepted an artifact-mismatched target")
