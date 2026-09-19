from __future__ import annotations

from dataclasses import dataclass, field

from backend.storage.factory import get_project_repository
from backend.storage.repository import StoredProject
from backend.tools.registry import registry
from backend.workflow.models import WorkflowIR

from .ingestion import IngestedSource
from .models import ContextGraph, Provenance, Requirement, Constraint, Source


@dataclass
class ProjectContext:
    project_id: str
    graph: ContextGraph = field(default_factory=ContextGraph)
    documents: dict[str, str] = field(default_factory=dict)
    workflow: WorkflowIR | None = None
    workflow_versions: list[WorkflowIR] = field(default_factory=list)
    runs: list[dict] = field(default_factory=list)


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
            tools = [
                ContextTool.model_validate(item.to_context())
                for item in registry.list()
            ]

            if project_id == "researchhunter":
                demo_source = Source(
                    id="src_researchhunter_brief",
                    kind="text",
                    name="ResearchHunter brief",
                    uri="specloom://demo/researchhunter",
                    content_hash="demo",
                )
                graph = ContextGraph(
                    sources=[demo_source],
                    requirements=[
                        Requirement(
                            id="req_research_relevance",
                            statement="The system must return research relevant to the project.",
                            priority="high",
                            provenance=[Provenance(
                                source_id=demo_source.id,
                                locator="line:1",
                                quote="The system must return research relevant to the project.",
                                confidence=1.0,
                            )],
                        ),
                        Requirement(
                            id="req_primary_verification",
                            statement="The system must verify primary-source metadata.",
                            priority="high",
                            provenance=[Provenance(
                                source_id=demo_source.id,
                                locator="line:2",
                                quote="The system must verify primary-source metadata.",
                                confidence=1.0,
                            )],
                        ),
                        Requirement(
                            id="req_prepare_issues",
                            statement="The system should prepare GitHub issues for human approval.",
                            priority="high",
                            provenance=[Provenance(
                                source_id=demo_source.id,
                                locator="line:3",
                                quote="The system should prepare GitHub issues for human approval.",
                                confidence=1.0,
                            )],
                        ),
                    ],
                    constraints=[
                        Constraint(
                            id="con_no_unapproved_writes",
                            statement="The system must not create GitHub issues without human approval.",
                            severity="blocking",
                            provenance=[Provenance(
                                source_id=demo_source.id,
                                locator="line:4",
                                quote="The system must not create GitHub issues without human approval.",
                                confidence=1.0,
                            )],
                        ),
                    ],
                    tools=tools,
                    examples=[],
                    entities=[],
                )
            else:
                graph = ContextGraph(
                    sources=[],
                    requirements=[],
                    constraints=[],
                    tools=tools,
                    examples=[],
                    entities=[],
                )

        documents = dict(stored.documents)
        if project_id == "researchhunter" and not documents:
            documents["src_researchhunter_brief"] = (
                "The system must return research relevant to the project.\n"
                "The system must verify primary-source metadata.\n"
                "The system should prepare GitHub issues for human approval.\n"
                "The system must not create GitHub issues without human approval."
            )

        workflow = stored.workflow
        workflow_versions = list(stored.workflow_versions)
        if project_id == "researchhunter" and workflow is None:
            from backend.workflow.templates import research_hunter_template

            workflow = research_hunter_template(
                goal="Research new AI developments and prepare relevant GitHub issues.",
                has_github_tool=any("github" in tool.name.lower() for tool in registry.list()),
            )
            if not workflow_versions:
                workflow_versions = [workflow]

        project = ProjectContext(
            project_id=project_id,
            graph=graph,
            documents=documents,
            workflow=workflow,
            workflow_versions=workflow_versions,
            runs=stored.runs,
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
                runs=project.runs,
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

    def record_run(self, project_id: str, run: dict) -> ProjectContext:
        project = self.get(project_id)
        project.runs.insert(0, run)
        del project.runs[50:]
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
