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



def test_successful_deploy_persists_immutable_artifact_snapshot():
    from backend.api import deploy as deploy_api
    from backend.context.store import store

    project_id = "snapshot-deploy-test"
    project = store.get(project_id)
    project.artifacts = {
        "generated/deploy/cloudformation.yaml": "template-v1",
        "generated/deploy/deployment-plan.json": '{"production_allowed": true, "artifact_digest": "sha-v1"}',
    }

    fake_result = {
        "status": "deployed",
        "stack_name": "stack-test",
        "region": "ap-south-1",
        "container_image": "registry/app:v1",
    }
    with patch.object(deploy_api.AWSProductionDeployer, "deploy", return_value=fake_result):
        result = deploy_api.deploy_generated(
            project_id,
            deploy_api.GeneratedProductionDeployRequest(approved=True),
        )

    snapshot_id = deploy_api.deployment_history(project_id)["deployments"][0]["artifact_snapshot_id"]
    assert snapshot_id
    assert snapshot_id.startswith("snap_")
    assert store.get_artifact_snapshot(project_id, snapshot_id)["generated/deploy/cloudformation.yaml"] == "template-v1"


def test_rollback_uses_historical_snapshot_after_current_artifacts_change():
    from backend.api import deploy as deploy_api
    from backend.context.store import store

    project_id = "historical-rollback-test"
    project = store.get(project_id)
    project.artifacts = {
        "generated/deploy/cloudformation.yaml": "template-v1",
        "generated/deploy/deployment-plan.json": '{"production_allowed": true, "artifact_digest": "sha-v1"}',
    }

    fake_deploy = {
        "status": "deployed",
        "stack_name": "stack-test",
        "region": "ap-south-1",
        "container_image": "registry/app:v1",
    }
    with patch.object(deploy_api.AWSProductionDeployer, "deploy", return_value=fake_deploy):
        deployed = deploy_api.deploy_generated(
            project_id,
            deploy_api.GeneratedProductionDeployRequest(approved=True),
        )

    snapshot_id = deploy_api.deployment_history(project_id)["deployments"][0]["artifact_snapshot_id"]
    project.artifacts = {"generated/deploy/cloudformation.yaml": "template-v2"}

    captured = {}

    def fake_executor(*, artifacts, approved, container_image):
        captured["artifacts"] = {item.path: item.content for item in artifacts}
        captured["approved"] = approved
        captured["container_image"] = container_image
        return {"status": "rolled_back", "stack_name": "stack-test", "region": "ap-south-1"}

    with patch.object(deploy_api.AWSDeploymentExecutor, "deploy", side_effect=fake_executor):
        result = deploy_api.rollback_generated(
            project_id,
            deploy_api.DeploymentRollbackRequest(
                approved=True,
                deployment_id=deployed["deployment_id"],
            ),
        )

    assert result["status"] == "rolled_back"
    assert captured["artifacts"]["generated/deploy/cloudformation.yaml"] == "template-v1"
    assert captured["approved"] is True
    assert captured["container_image"] == "registry/app:v1"


def test_repaired_redeployment_records_recovery_run_lineage():
    from backend.api import deploy as deploy_api
    from backend.context.store import store

    project_id = "repair-redeploy-lineage-test"
    store.get(project_id).artifacts = {
        "generated/deploy/cloudformation.yaml": "template-repaired",
        "generated/deploy/deployment-plan.json": '{"production_allowed": true, "artifact_digest": "sha-repaired"}',
        "generated/repository/app/main.py": "print('repaired')",
    }

    fake_result = {
        "status": "deployed",
        "stack_name": "stack-repaired",
        "region": "ap-south-1",
        "container_image": "registry/app:repaired",
    }
    with patch.object(
        deploy_api.AWSProductionDeployer,
        "deploy",
        return_value=fake_result,
    ):
        result = deploy_api.deploy_generated(
            project_id,
            deploy_api.GeneratedProductionDeployRequest(
                approved=True,
                recovery_run_id="run-repair",
            ),
        )

    deployment = deploy_api.deployment_history(project_id)["deployments"][0]
    assert result["deployment_id"] == deployment["deployment_id"]
    assert deployment["recovery_run_id"] == "run-repair"
    assert deployment["artifact_snapshot_id"]


def test_redeployment_uses_exact_verified_snapshot_not_mutable_project_artifacts():
    from backend.api import deploy as deploy_api
    from backend.compiler.models import artifact_snapshot_id
    from backend.context.store import store

    project_id = "exact-repair-snapshot-test"
    verified = {
        "generated/deploy/cloudformation.yaml": "verified-template",
        "generated/deploy/deployment-plan.json": '{"production_allowed": true, "artifact_digest": "sha-verified"}',
    }
    project = store.get(project_id)
    project.artifacts = dict(verified)

    # Persist the verified repair snapshot, then mutate the live project state.
    verified_artifacts = [
        deploy_api.Artifact(
            path=path,
            kind="infrastructure" if path.endswith("yaml") else "source",
            content=content,
        ).with_hash()
        for path, content in verified.items()
    ]
    snapshot_id = artifact_snapshot_id(verified_artifacts)
    store.save_artifact_snapshot(project_id, snapshot_id, verified)
    project.artifacts["generated/deploy/cloudformation.yaml"] = "unverified-current-state"

    captured = {}

    def fake_deploy(*, artifacts, approved):
        captured["artifacts"] = {item.path: item.content for item in artifacts}
        captured["approved"] = approved
        return {
            "status": "deployed",
            "stack_name": "stack-repaired",
            "region": "ap-south-1",
            "container_image": "registry/app:repaired",
        }

    with patch.object(deploy_api.AWSProductionDeployer, "deploy", side_effect=fake_deploy):
        result = deploy_api.deploy_generated(
            project_id,
            deploy_api.GeneratedProductionDeployRequest(
                approved=True,
                recovery_run_id="run-repair",
                artifact_snapshot_id=snapshot_id,
            ),
        )

    assert result["deployment_id"]
    assert captured["approved"] is True
    assert captured["artifacts"]["generated/deploy/cloudformation.yaml"] == "verified-template"
