from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any


class BuildJobRepository:
    """Durable build-job status store.

    Production uses DynamoDB so API requests and asynchronous Lambda workers never
    depend on sharing a warm Lambda process. Local development falls back to memory.
    """

    def __init__(self) -> None:
        self.table_name = os.getenv("SPECL00M_BUILD_JOBS_TABLE", "").strip()
        self._memory: dict[tuple[str, str], dict[str, Any]] = {}
        self._table = None
        if self.table_name:
            import boto3
            self._table = boto3.resource("dynamodb").Table(self.table_name)

    def put(self, job: dict[str, Any]) -> None:
        if self._table is not None:
            item = {
                "project_id": str(job["project_id"]),
                "run_id": str(job["run_id"]),
                **job,
            }
            self._table.put_item(Item=item)
            return
        self._memory[(str(job["project_id"]), str(job["run_id"]))] = dict(job)

    def get(self, project_id: str, run_id: str) -> dict[str, Any] | None:
        if self._table is not None:
            item = self._table.get_item(
                Key={"project_id": project_id, "run_id": run_id}
            ).get("Item")
            return dict(item) if item else None
        item = self._memory.get((project_id, run_id))
        return dict(item) if item else None

    def update(self, project_id: str, run_id: str, **changes: Any) -> dict[str, Any] | None:
        current = self.get(project_id, run_id)
        if current is None:
            return None
        current.update(changes)
        current["updated_at"] = datetime.now(timezone.utc).isoformat()
        self.put(current)
        return current


build_jobs = BuildJobRepository()
