from __future__ import annotations

from dataclasses import dataclass, field

from backend.storage.factory import get_project_repository
from backend.storage.repository import StoredProject
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
        self._repository = get_project_repository()

    def get(self, project_id: str) -> ProjectContext:
        if project_id in self._projects:
            return self._projects[project_id]

        from .models import ContextTool

        stored = self._repository.get(project_id)
        if stored.graph:
            graph = ContextGraph.model_validate(stored.graph)
        else:
            graph = ContextGraph(
                sources=[],
                requirements=[],
                constraints=[],
                tools=[
                    ContextTool.model_validate(item.to_context())
                    for item in registry.list()
                ],
                examples=[],
                entities=[],
            )

        project = ProjectContext(
            project_id=project_id,
            graph=graph,
            documents=stored.documents,
            workflow=stored.workflow,
            workflow_versions=stored.workflow_versions,
        )
        self._projects[project_id] = project
        return project

    def _persist(self, project: ProjectContext) -> None:
        self._repository.save(
            StoredProject(
                project_id=project.project_id,
                workflow=project.workflow,
                workflow_versions=project.workflow_versions,
                documents=project.documents,
                graph=project.graph.model_dump(mode="json"),
            )
        )

    def add_source(self, project_id: str, source: IngestedSource) -> ProjectContext:
        project = self.get(project_id)
        project.documents[source.source.id] = source.text
        if source.source.id not in {item.id for item in project.graph.sources}:
            project.graph.sources.append(source.source)

        put_document = getattr(self._repository, "put_document", None)
        if put_document is not None:
            put_document(project_id, source.source.id, source.text)

        self._persist(project)
        return project

    def set_workflow(self, project_id: str, workflow: WorkflowIR) -> ProjectContext:
        project = self.get(project_id)
        project.workflow = workflow
        self._persist(project)
        return project

    def save_workflow(self, project_id: str, workflow: WorkflowIR) -> ProjectContext:
        project = self.get(project_id)
        project.workflow = workflow
        project.workflow_versions.append(workflow)
        self._persist(project)
        return project


store = ContextStore()
