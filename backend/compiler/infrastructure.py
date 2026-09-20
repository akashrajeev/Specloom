from __future__ import annotations

import os
import re
import shutil
import subprocess
import tempfile
import hashlib
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from .models import Artifact, SoftwareSpec


class InfrastructureParameters(BaseModel):
    region_env: str = "SPECL00M_AWS_REGION"
    vpc_env: str = "SPECL00M_AWS_VPC_ID"
    subnet_env: str = "SPECL00M_AWS_SUBNET_IDS"
    stack_env: str = "SPECL00M_AWS_STACK_NAME"
    container_image_env: str = "SPECL00M_CONTAINER_IMAGE"


class InfrastructureCompiler:
    """Generate deployable AWS ECS/Fargate infrastructure without embedding credentials."""

    def compile(
        self,
        spec: SoftwareSpec,
        parameters: InfrastructureParameters | None = None,
    ) -> Artifact:
        parameters = parameters or InfrastructureParameters()
        logical_name = self._logical_name(spec.name)

        template = f"""AWSTemplateFormatVersion: '2010-09-09'
Description: Generated production infrastructure for {spec.name}

Parameters:
  VpcId:
    Type: AWS::EC2::VPC::Id
    Description: Existing VPC for the generated service.
  SubnetIds:
    Type: List<AWS::EC2::Subnet::Id>
    Description: Existing subnets for ECS tasks.
  ContainerImage:
    Type: String
    Description: Immutable container image URI.
  DesiredCount:
    Type: Number
    Default: 1
    MinValue: 1
  ContainerPort:
    Type: Number
    Default: 8080

Resources:
  Cluster:
    Type: AWS::ECS::Cluster
    Properties:
      ClusterName: {logical_name}-cluster
      Tags:
        - Key: specloom-generated
          Value: "true"

  LogGroup:
    Type: AWS::Logs::LogGroup
    Properties:
      LogGroupName: /specloom/{logical_name}
      RetentionInDays: 30

  TaskExecutionRole:
    Type: AWS::IAM::Role
    Properties:
      RoleName: {logical_name}-execution
      AssumeRolePolicyDocument:
        Version: "2012-10-17"
        Statement:
          - Effect: Allow
            Principal:
              Service:
                - ecs-tasks.amazonaws.com
            Action:
              - sts:AssumeRole
      ManagedPolicyArns:
        - arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy
      Tags:
        - Key: specloom-generated
          Value: "true"

  TaskRole:
    Type: AWS::IAM::Role
    Properties:
      RoleName: {logical_name}-task
      AssumeRolePolicyDocument:
        Version: "2012-10-17"
        Statement:
          - Effect: Allow
            Principal:
              Service:
                - ecs-tasks.amazonaws.com
            Action:
              - sts:AssumeRole
      Policies: []
      Tags:
        - Key: specloom-generated
          Value: "true"

  TaskDefinition:
    Type: AWS::ECS::TaskDefinition
    Properties:
      Family: {logical_name}
      Cpu: "512"
      Memory: "1024"
      NetworkMode: awsvpc
      RequiresCompatibilities:
        - FARGATE
      ExecutionRoleArn: !GetAtt TaskExecutionRole.Arn
      TaskRoleArn: !GetAtt TaskRole.Arn
      ContainerDefinitions:
        - Name: app
          Image: !Ref ContainerImage
          Essential: true
          PortMappings:
            - ContainerPort: !Ref ContainerPort
              Protocol: tcp
          HealthCheck:
            Command:
              - CMD-SHELL
              - python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/health', timeout=3)"
            Interval: 30
            Timeout: 5
            Retries: 3
            StartPeriod: 20
          LogConfiguration:
            LogDriver: awslogs
            Options:
              awslogs-group: !Ref LogGroup
              awslogs-region: !Ref AWS::Region
              awslogs-stream-prefix: app

  ServiceSecurityGroup:
    Type: AWS::EC2::SecurityGroup
    Properties:
      GroupDescription: Generated service security group
      VpcId: !Ref VpcId
      SecurityGroupEgress:
        - IpProtocol: -1
          CidrIp: 0.0.0.0/0
      Tags:
        - Key: specloom-generated
          Value: "true"

  Service:
    Type: AWS::ECS::Service
    DependsOn:
      - TaskDefinition
    Properties:
      Cluster: !Ref Cluster
      DesiredCount: !Ref DesiredCount
      LaunchType: FARGATE
      TaskDefinition: !Ref TaskDefinition
      NetworkConfiguration:
        AwsvpcConfiguration:
          AssignPublicIp: ENABLED
          SecurityGroups:
            - !Ref ServiceSecurityGroup
          Subnets: !Ref SubnetIds
      EnableExecuteCommand: false
      DeploymentConfiguration:
        MaximumPercent: 200
        MinimumHealthyPercent: 50
        DeploymentCircuitBreaker:
          Enable: true
          Rollback: true

Outputs:
  ClusterName:
    Value: !Ref Cluster
  ServiceName:
    Value: !Ref Service
  LogGroupName:
    Value: !Ref LogGroup
"""
        return Artifact(
            path="generated/deploy/cloudformation.yaml",
            kind="infrastructure",
            content=template,
            generated_from=[spec.id],
        )

    @staticmethod
    def _logical_name(value: str) -> str:
        value = re.sub(r"[^A-Za-z0-9-]+", "-", value).strip("-").lower()
        return (value or "specloom-generated")[:40]


class DeploymentExecutionError(RuntimeError):
    pass




class ContainerImagePublisher:
    """Build and publish an immutable generated image to Amazon ECR."""

    def publish(
        self,
        *,
        artifacts: list[Artifact],
        approved: bool = False,
    ) -> str:
        if not approved:
            raise DeploymentExecutionError(
                "publishing a production container requires explicit approval"
            )

        docker = shutil.which("docker")
        aws = shutil.which("aws")
        if docker is None or aws is None:
            raise DeploymentExecutionError(
                "Docker and AWS CLI are required for image publication"
            )

        region = os.getenv("SPECL00M_AWS_REGION", "").strip()
        repository_name = os.getenv(
            "SPECL00M_ECR_REPOSITORY",
            "specloom-generated",
        ).strip()
        if not region or not repository_name:
            raise DeploymentExecutionError(
                "SPECL00M_AWS_REGION and SPECL00M_ECR_REPOSITORY are required"
            )

        digest = hashlib.sha256(
            "|".join(
                f"{item.path}:{item.sha256}"
                for item in sorted(artifacts, key=lambda item: item.path)
            ).encode("utf-8")
        ).hexdigest()
        tag = digest[:16]

        with tempfile.TemporaryDirectory(prefix="specloom-image-") as tmp:
            root = Path(tmp)
            for artifact in artifacts:
                relative = Path(artifact.path)
                if relative.is_absolute() or ".." in relative.parts:
                    raise DeploymentExecutionError(
                        f"unsafe artifact path: {artifact.path}"
                    )
                target = root / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(artifact.content, encoding="utf-8")

            local_tag = f"{repository_name}:{tag}"
            self._run(
                [
                    docker,
                    "build",
                    "--pull",
                    "-f",
                    "generated/repository/Dockerfile",
                    "-t",
                    local_tag,
                    ".",
                ],
                cwd=root,
                env=os.environ.copy(),
                timeout=300,
            )

            identity = self._run(
                [
                    aws,
                    "sts",
                    "get-caller-identity",
                    "--query",
                    "Account",
                    "--output",
                    "text",
                    "--region",
                    region,
                ],
                cwd=root,
                env=os.environ.copy(),
                timeout=30,
            )
            account = identity.stdout.strip()
            if not account.isdigit():
                raise DeploymentExecutionError(
                    "AWS caller identity did not return a numeric account id"
                )

            self._run(
                [
                    aws,
                    "ecr",
                    "describe-repositories",
                    "--repository-names",
                    repository_name,
                    "--region",
                    region,
                ],
                cwd=root,
                env=os.environ.copy(),
                timeout=30,
                allow_failure=True,
            )

            ensure = self._run(
                [
                    aws,
                    "ecr",
                    "create-repository",
                    "--repository-name",
                    repository_name,
                    "--region",
                    region,
                ],
                cwd=root,
                env=os.environ.copy(),
                timeout=60,
                allow_failure=True,
            )
            _ = ensure

            registry = f"{account}.dkr.ecr.{region}.amazonaws.com"
            password = self._run(
                [
                    aws,
                    "ecr",
                    "get-login-password",
                    "--region",
                    region,
                ],
                cwd=root,
                env=os.environ.copy(),
                timeout=30,
            )
            login = subprocess.run(
                [docker, "login", "--username", "AWS", "--password-stdin", registry],
                cwd=root,
                input=password.stdout,
                capture_output=True,
                text=True,
                timeout=30,
                check=False,
                env=os.environ.copy(),
            )
            if login.returncode != 0:
                raise DeploymentExecutionError(
                    login.stderr.strip() or "docker login failed"
                )

            remote_image = f"{registry}/{repository_name}:{tag}"
            self._run(
                [docker, "tag", local_tag, remote_image],
                cwd=root,
                env=os.environ.copy(),
                timeout=30,
            )
            self._run(
                [docker, "push", remote_image],
                cwd=root,
                env=os.environ.copy(),
                timeout=300,
            )
            return remote_image

    @staticmethod
    def _run(
        command: list[str],
        *,
        cwd: Path,
        env: dict[str, str],
        timeout: int,
        allow_failure: bool = False,
    ) -> subprocess.CompletedProcess[str]:
        result = subprocess.run(
            command,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
            env=env,
        )
        if not allow_failure and result.returncode != 0:
            raise DeploymentExecutionError(
                result.stderr.strip() or result.stdout.strip()
            )
        return result


class AWSProductionDeployer:
    """Build/publish/deploy the current immutable generated bundle."""

    def __init__(
        self,
        publisher: ContainerImagePublisher | None = None,
        deployer: AWSDeploymentExecutor | None = None,
    ) -> None:
        self.publisher = publisher or ContainerImagePublisher()
        self.deployer = deployer or AWSDeploymentExecutor()

    def deploy(
        self,
        *,
        artifacts: list[Artifact],
        approved: bool = False,
        container_image: str | None = None,
    ) -> dict[str, Any]:
        if not approved:
            raise DeploymentExecutionError(
                "production deployment requires explicit approval"
            )
        image = self.publisher.publish(
            artifacts=artifacts,
            approved=True,
        )
        previous = os.getenv(
            "SPECL00M_PREVIOUS_CONTAINER_IMAGE",
            "",
        ).strip()
        result = self.deployer.deploy(
            artifacts=artifacts,
            approved=True,
            container_image=image,
        )
        result["container_image"] = image
        result["previous_container_image"] = previous or None
        return result

class AWSDeploymentExecutor:
    """Explicitly gated AWS deployment through the AWS CLI."""

    def deploy(
        self,
        *,
        artifacts: list[Artifact],
        approved: bool = False,
    ) -> dict[str, Any]:
        if not approved:
            raise DeploymentExecutionError(
                "production deployment requires explicit approval"
            )

        aws = shutil.which("aws")
        if aws is None:
            raise DeploymentExecutionError("AWS CLI is required for production deployment")

        template = next(
            (
                item
                for item in artifacts
                if item.path == "generated/deploy/cloudformation.yaml"
            ),
            None,
        )
        if template is None:
            raise DeploymentExecutionError(
                "generated CloudFormation template is missing"
            )

        region = os.getenv("SPECL00M_AWS_REGION", "").strip()
        stack_name = os.getenv(
            "SPECL00M_AWS_STACK_NAME",
            "specloom-generated-system",
        ).strip()
        vpc_id = os.getenv("SPECL00M_AWS_VPC_ID", "").strip()
        subnet_ids = os.getenv("SPECL00M_AWS_SUBNET_IDS", "").strip()
        image = (
            container_image
            or os.getenv("SPECL00M_CONTAINER_IMAGE", "")
        ).strip()

        missing = [
            name
            for name, value in (
                ("SPECL00M_AWS_REGION", region),
                ("SPECL00M_AWS_VPC_ID", vpc_id),
                ("SPECL00M_AWS_SUBNET_IDS", subnet_ids),
                ("SPECL00M_CONTAINER_IMAGE", image),
            )
            if not value
        ]
        if missing:
            raise DeploymentExecutionError(
                "missing deployment configuration: " + ", ".join(missing)
            )

        with tempfile.TemporaryDirectory(prefix="specloom-deploy-") as tmp:
            template_path = Path(tmp) / "cloudformation.yaml"
            template_path.write_text(template.content, encoding="utf-8")
            parameters = [
                f"VpcId={vpc_id}",
                f"SubnetIds={subnet_ids}",
                f"ContainerImage={image}",
            ]
            command = [
                aws,
                "cloudformation",
                "deploy",
                "--template-file",
                str(template_path),
                "--stack-name",
                stack_name,
                "--region",
                region,
                "--capabilities",
                "CAPABILITY_NAMED_IAM",
                "--parameter-overrides",
                *parameters,
            ]
            result = subprocess.run(
                command,
                capture_output=True,
                text=True,
                timeout=300,
                check=False,
                env={
                    **os.environ,
                    "AWS_DEFAULT_REGION": region,
                },
            )
            if result.returncode != 0:
                raise DeploymentExecutionError(
                    result.stderr.strip() or result.stdout.strip()
                )

        return {
            "status": "deployed",
            "stack_name": stack_name,
            "region": region,
        }

