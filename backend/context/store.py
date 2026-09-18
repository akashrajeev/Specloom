from __future__ import annotations

from dataclasses import dataclass, field

from .ingestion import IngestedSource
from .models import ContextGraph

@dataclass
class ProjectContext:
    project_id: str
    graph: ContextGraph = field(default_factory=ContextGraph)
    documents: dict[str, str] = field(default_factory=dict)

class ContextStore:
    def __init__(self) -> None:
        self._projects: dict[str, ProjectContext] = {}

    def get(self, project_id: str) -> ProjectContext:
        return self._projects.setdefault(project_id, ProjectContext(project_id=project_id))

    def add_source(self, project_id: str, source: IngestedSource) -> ProjectContext:
        project = self.get(project_id)
        project.documents[source.source.id] = source.text
        existing = {item.id for item in project.graph.sources}
        if source.source.id not in existing:
            project.graph.sources.append(source.source)
        return project

store = ContextStore()
