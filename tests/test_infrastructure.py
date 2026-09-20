from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from backend.compiler.infrastructure import (
    AWSDeploymentExecutor,
    ContainerImagePublisher,
    DeploymentExecutionError,
    InfrastructureCompiler,
)
from backend.compiler.models import Artifact, SoftwareSpec


def test_infrastructure_compiler_generates_real_ecs_service_contract():
    spec = SoftwareSpec(
        id="system-infra",
        name="Generated CRM",
        goal="Run a production service",
    )
    artifact = InfrastructureCompiler().compile(spec)

    assert "AWS::ECS::Cluster" in artifact.content
    assert "AWS::ECS::TaskDefinition" in artifact.content
    assert "AWS::ECS::Service" in artifact.content
    assert "ContainerImage" in artifact.content
    assert "CAPABILITY_NAMED_IAM" not in artifact.content


def test_production_deployer_requires_explicit_approval():
    class FakePublisher:
        def publish(self, **kwargs):
            raise AssertionError("must not publish")

    class FakeDeployer:
        def deploy(self, **kwargs):
            raise AssertionError("must not deploy")

    from backend.compiler.infrastructure import AWSProductionDeployer

    with pytest.raises(DeploymentExecutionError):
        AWSProductionDeployer(
            publisher=FakePublisher(),
            deployer=FakeDeployer(),
        ).deploy(artifacts=[], approved=False)


def test_aws_deployer_accepts_explicit_container_image(monkeypatch):
    monkeypatch.setenv("SPECL00M_AWS_REGION", "ap-south-1")
    monkeypatch.setenv("SPECL00M_AWS_VPC_ID", "vpc-123")
    monkeypatch.setenv("SPECL00M_AWS_SUBNET_IDS", "subnet-a,subnet-b")

    artifact = Artifact(
        path="generated/deploy/cloudformation.yaml",
        kind="infrastructure",
        content="Resources: {}",
    )

    fake = type("Completed", (), {"returncode": 0, "stdout": "", "stderr": ""})()

    with patch(
        "backend.compiler.infrastructure.shutil.which",
        return_value="/usr/bin/aws",
    ), patch(
        "backend.compiler.infrastructure.subprocess.run",
        return_value=fake,
    ) as run:
        result = AWSDeploymentExecutor().deploy(
            artifacts=[artifact],
            approved=True,
            container_image="123456789012.dkr.ecr.ap-south-1.amazonaws.com/app:abcd",
        )

    assert result["status"] == "deployed"
    commands = [call.args[0] for call in run.call_args_list]
    assert any("cloudformation" in command for command in commands)
