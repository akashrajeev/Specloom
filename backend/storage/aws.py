from __future__ import annotations

import json
import os

import boto3

from .repository import ProjectRepository, StoredProject
from backend.workflow.models import WorkflowIR


class AwsProjectRepository(ProjectRepository):
    """DynamoDB metadata + S3 document storage adapter."""

    def __init__(self, table_name: str | None = None, bucket: str | None = None) -> None:
        self.table_name = table_name or os.environ["SPECL00M_DDB_TABLE"]
        self.bucket = bucket or os.environ["SPECL00M_S3_BUCKET"]
        self.table = boto3.resource("dynamodb").Table(self.table_name)
        self.s3 = boto3.client("s3")

    def get(self, project_id: str) -> StoredProject:
        item = self.table.get_item(Key={"project_id": project_id}).get("Item", {})
        workflow = WorkflowIR.model_validate(item["workflow"]) if item.get("workflow") else None
        versions = [
            WorkflowIR.model_validate(value)
            for value in item.get("workflow_versions", [])
        ]
        return StoredProject(
            project_id=project_id,
            workflow=workflow,
            workflow_versions=versions,
            documents={},
            graph=item.get("graph", {}),
            runs=item.get("runs", []),
        )

    def save(self, project: StoredProject) -> None:
        self.table.put_item(
            Item={
                "project_id": project.project_id,
                "workflow": project.workflow.model_dump(mode="json") if project.workflow else None,
                "workflow_versions": [
                    workflow.model_dump(mode="json")
                    for workflow in project.workflow_versions
                ],
                "graph": project.graph,
                "runs": project.runs,
            }
        )

    def put_document(self, project_id: str, source_id: str, content: str) -> None:
        self.s3.put_object(
            Bucket=self.bucket,
            Key=f"projects/{project_id}/sources/{source_id}.txt",
            Body=content.encode("utf-8"),
            ContentType="text/plain",
        )

    def get_document(self, project_id: str, source_id: str) -> str:
        response = self.s3.get_object(
            Bucket=self.bucket,
            Key=f"projects/{project_id}/sources/{source_id}.txt",
        )
        return response["Body"].read().decode("utf-8")
