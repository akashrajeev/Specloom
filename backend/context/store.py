from __future__ import annotations

from dataclasses import dataclass, field

from .ingestion import IngestedSource
from .models import ContextGraph
from backend.tools.registry import registry


@dataclass
class ProjectContext:
    project_id: str
    graph: ContextGraph = field(default_factory=ContextGraph)
    documents: dict[str, str] = field(default_factory=dict)


class ContextStore:
    def __init__(self) -> None:
        self._projects: dict[str, ProjectContext] = {}

    def get(self, project_id: str) -> ProjectContext:
        if project_id not in self._projects:
            self._projects[project_id] = ProjectContext(
                project_id=project_id,
                graph=ContextGraph(
                    sources=[],
                    requirements=[],
                    constraints=[],
                    tools=[
                        # The catalog is descriptive. Runtime credentials are never
                        # stored in the context graph.
                        self._tool_model(item)
                        for item in registry.list()
                    ],
                    examples=[],
                    entities=[],
                ),
            )
        return self._projects[project_id]

    @staticmethod
    def _tool_model(item):
        from .models import ContextTool
        return ContextTool.model_validate(item.to_context())

    def add_source(self, project_id: str, source: IngestedSource) -> ProjectContext:
        project = self.get(project_id)
        project.documents[source.source.id] = source.text
        existing = {item.id for item in project.graph.sources}
        if source.source.id not in existing:
            project.graph.sources.append(source.source)
        return project


store = ContextStore()
