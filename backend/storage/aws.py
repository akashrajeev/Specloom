from __future__ import annotations

import json
import os

import boto3

from .repository import ProjectRepository, StoredProject
from backend.workflow.models import WorkflowIR


class AwsProjectRepository(ProjectRepository):
    """DynamoDB metadata + S3 source/artifact storage adapter."""

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

        documents: dict[str, str] = {}
        response = self.s3.list_objects_v2(
            Bucket=self.bucket,
            Prefix=f"projects/{project_id}/sources/",
        )
        for obj in response.get("Contents", []):
            key = str(obj.get("Key", ""))
            source_id = key.rsplit("/", 1)[-1].removesuffix(".txt")
            if not source_id:
                continue
            try:
                body = self.s3.get_object(Bucket=self.bucket, Key=key)["Body"]
                documents[source_id] = body.read().decode("utf-8")
            except Exception:
                continue

        artifacts: dict[str, str] = {}
        response = self.s3.list_objects_v2(
            Bucket=self.bucket,
            Prefix=f"projects/{project_id}/artifacts/",
        )
        for obj in response.get("Contents", []):
            key = str(obj.get("Key", ""))
            relative = key.split(f"projects/{project_id}/artifacts/", 1)[-1]
            if not relative:
                continue
            try:
                body = self.s3.get_object(Bucket=self.bucket, Key=key)["Body"]
                artifacts[relative] = body.read().decode("utf-8")
            except Exception:
                continue

        return StoredProject(
            project_id=project_id,
            workflow=workflow,
            workflow_versions=versions,
            documents=documents,
            graph=item.get("graph", {}),
            runs=item.get("runs", []),
            workspace_id=str(item.get("workspace_id")) if item.get("workspace_id") else None,
            artifacts=artifacts,
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
                "workspace_id": project.workspace_id,
                "artifact_paths": sorted(project.artifacts),
            }
        )

        for path, content in project.artifacts.items():
            self.s3.put_object(
                Bucket=self.bucket,
                Key=f"projects/{project.project_id}/artifacts/{path}",
                Body=content.encode("utf-8"),
                ContentType="text/plain",
            )

    def save_artifact_snapshot(
        self,
        project_id: str,
        snapshot_id: str,
        artifacts: dict[str, str],
    ) -> None:
        key = f"projects/{project_id}/snapshots/{snapshot_id}/manifest.json"
        body = json.dumps(
            {"snapshot_id": snapshot_id, "artifacts": artifacts},
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        try:
            existing = self.s3.get_object(Bucket=self.bucket, Key=key)["Body"].read()
        except self.s3.exceptions.NoSuchKey:
            existing = None
        if existing is not None and existing != body:
            raise ValueError("artifact snapshot is immutable and already exists")
        if existing is None:
            self.s3.put_object(
                Bucket=self.bucket,
                Key=key,
                Body=body,
                ContentType="application/json",
            )

    def get_artifact_snapshot(
        self,
        project_id: str,
        snapshot_id: str,
    ) -> dict[str, str]:
        key = f"projects/{project_id}/snapshots/{snapshot_id}/manifest.json"
        try:
            body = self.s3.get_object(Bucket=self.bucket, Key=key)["Body"].read()
        except self.s3.exceptions.NoSuchKey as exc:
            raise KeyError(f"artifact snapshot not found: {snapshot_id}") from exc
        payload = json.loads(body.decode("utf-8"))
        artifacts = payload.get("artifacts")
        if not isinstance(artifacts, dict):
            raise ValueError("stored artifact snapshot is malformed")
        return {str(path): str(content) for path, content in artifacts.items()}

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
