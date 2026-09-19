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
