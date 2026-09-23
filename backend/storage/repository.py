from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

from backend.workflow.models import WorkflowIR


@dataclass
class StoredProject:
    project_id: str
    workflow: WorkflowIR | None
    workflow_versions: list[WorkflowIR]
    documents: dict[str, str]
    graph: dict[str, Any]
    runs: list[dict[str, Any]] = field(default_factory=list)
    workspace_id: str | None = None
    artifacts: dict[str, str] = field(default_factory=dict)


class ProjectRepository(ABC):
    @abstractmethod
    def get(self, project_id: str) -> StoredProject:
        raise NotImplementedError

    @abstractmethod
    def save(self, project: StoredProject) -> None:
        raise NotImplementedError

    def list_project_ids(self, limit: int = 100) -> list[str]:
        """Project IDs known to this repository. Adapters override when they can list."""
        return []

    @abstractmethod
    def save_artifact_snapshot(
        self,
        project_id: str,
        snapshot_id: str,
        artifacts: dict[str, str],
    ) -> None:
        raise NotImplementedError

    @abstractmethod
    def get_artifact_snapshot(
        self,
        project_id: str,
        snapshot_id: str,
    ) -> dict[str, str]:
        raise NotImplementedError


class MemoryProjectRepository(ProjectRepository):
    def __init__(self) -> None:
        self._items: dict[str, StoredProject] = {}

    def get(self, project_id: str) -> StoredProject:
        if project_id not in self._items:
            self._items[project_id] = StoredProject(
                project_id=project_id,
                workflow=None,
                workflow_versions=[],
                documents={},
                graph={},
            )
        return self._items[project_id]

    def save(self, project: StoredProject) -> None:
        self._items[project.project_id] = project

    def list_project_ids(self, limit: int = 100) -> list[str]:
        return [
            project_id
            for project_id, item in self._items.items()
            if item.workflow is not None
        ][:limit]

    def save_artifact_snapshot(
        self,
        project_id: str,
        snapshot_id: str,
        artifacts: dict[str, str],
    ) -> None:
        key = (project_id, snapshot_id)
        existing = getattr(self, "_snapshots", {}).get(key)
        if existing is not None and existing != artifacts:
            raise ValueError("artifact snapshot is immutable and already exists")
        if not hasattr(self, "_snapshots"):
            self._snapshots = {}
        self._snapshots[key] = dict(artifacts)

    def get_artifact_snapshot(
        self,
        project_id: str,
        snapshot_id: str,
    ) -> dict[str, str]:
        try:
            return dict(self._snapshots[(project_id, snapshot_id)])
        except KeyError as exc:
            raise KeyError(f"artifact snapshot not found: {snapshot_id}") from exc
