from __future__ import annotations

import os
import re
import shutil
import subprocess
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
        image = os.getenv("SPECL00M_CONTAINER_IMAGE", "").strip()

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
                    "PATH": os.environ.get("PATH", ""),
                    "AWS_PROFILE": os.environ.get("AWS_PROFILE", ""),
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


class _TemporaryImportGuard:
    pass
