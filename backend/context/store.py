from __future__ import annotations

from dataclasses import dataclass, field

from backend.tools.registry import registry
from backend.workflow.models import WorkflowIR

from .ingestion import IngestedSource
from .models import ContextGraph


@dataclass
class ProjectContext:
    project_id: str
    graph: ContextGraph = field(default_factory=ContextGraph)
    documents: dict[str, str] = field(default_factory=dict)
    workflow: WorkflowIR | None = None
    workflow_versions: list[WorkflowIR] = field(default_factory=list)


class ContextStore:
    def __init__(self) -> None:
        self._projects: dict[str, ProjectContext] = {}

    def get(self, project_id: str) -> ProjectContext:
        if project_id not in self._projects:
            from .models import ContextTool

            tools = [ContextTool.model_validate(item.to_context()) for item in registry.list()]
            self._projects[project_id] = ProjectContext(
                project_id=project_id,
                graph=ContextGraph(
                    sources=[],
                    requirements=[],
                    constraints=[],
                    tools=tools,
                    examples=[],
                    entities=[],
                ),
            )
        return self._projects[project_id]

    def add_source(self, project_id: str, source: IngestedSource) -> ProjectContext:
        project = self.get(project_id)
        project.documents[source.source.id] = source.text
        if source.source.id not in {item.id for item in project.graph.sources}:
            project.graph.sources.append(source.source)
        return project

    def save_workflow(self, project_id: str, workflow: WorkflowIR) -> ProjectContext:
        project = self.get(project_id)
        project.workflow = workflow
        project.workflow_versions.append(workflow)
        return project


store = ContextStore()
