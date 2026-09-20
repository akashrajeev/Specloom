from __future__ import annotations

from dataclasses import dataclass, field

from backend.storage.factory import get_project_repository
from backend.storage.repository import StoredProject
from backend.tools.api import api_context_tools
from backend.tools.registry import registry
from backend.tools.mcp import configured_mcp_capabilities, readonly_mcp_server_names
from backend.workflow.models import WorkflowIR
from backend.security.auth import current_workspace_id

from .ingestion import IngestedSource
from .models import ContextGraph, Provenance, Requirement, Constraint, Source, ContextTool


@dataclass
class ProjectContext:
    project_id: str
    workspace_id: str | None = None
    graph: ContextGraph = field(default_factory=ContextGraph)
    documents: dict[str, str] = field(default_factory=dict)
    workflow: WorkflowIR | None = None
    workflow_versions: list[WorkflowIR] = field(default_factory=list)
    runs: list[dict] = field(default_factory=list)
    artifacts: dict[str, str] = field(default_factory=dict)


class ContextStore:
    def __init__(self) -> None:
        self._projects: dict[tuple[str | None, str], ProjectContext] = {}
        self._repository = get_project_repository()

    def get(self, project_id: str) -> ProjectContext:
        workspace_id = current_workspace_id()
        cache_key = (workspace_id, project_id)
        if cache_key in self._projects:
            return self._projects[cache_key]

        stored = self._repository.get(project_id)
        owner = stored.workspace_id
        claimed_workspace = False
        if workspace_id and owner and workspace_id != owner:
            raise PermissionError("project does not belong to the current workspace")
        if workspace_id and not owner:
            owner = workspace_id
            stored.workspace_id = owner
            claimed_workspace = True

        if stored.graph:
            graph = ContextGraph.model_validate(stored.graph)
        else:
            tool_defs = [item.to_context() for item in registry.list()]
            tool_defs.extend(api_context_tools())
            graph = self._default_graph(
                project_id,
                [ContextTool.model_validate(item) for item in tool_defs],
            )

        self._hydrate_capability_tools(graph)

        configured_capabilities = configured_mcp_capabilities()
        readonly_servers = readonly_mcp_server_names()
        existing_tool_ids = {tool.id for tool in graph.tools}
        for server_name in sorted(readonly_servers):
            tool_id = f"mcp:{server_name}"
            if tool_id not in existing_tool_ids:
                graph.tools.append(
                    ContextTool(
                        id=tool_id,
                        name=f"MCP · {server_name}",
                        description="Configured read-only MCP capability",
                        capabilities=["mcp", *configured_capabilities.get(server_name, [])],
                        permissions=["READ"],
                        side_effecting=False,
                        requires_human_approval=False,
                        execution_modes=["live"],
                    )
                )

        documents = dict(stored.documents)
        if project_id == "researchhunter" and not documents:
            documents["src_researchhunter_brief"] = (
                "The system must select research directly related to configured project domains.\n"
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
            workspace_id=owner,
            graph=graph,
            documents=documents,
            workflow=workflow,
            workflow_versions=workflow_versions,
            runs=stored.runs,
            artifacts=dict(stored.artifacts),
        )
        if claimed_workspace:
            self._persist(project)
        self._projects[cache_key] = project
        return project

    @staticmethod
    def _default_graph(project_id: str, tools: list[ContextTool]) -> ContextGraph:
        if project_id != "researchhunter":
            return ContextGraph(tools=tools)

        demo_source = Source(
            id="src_researchhunter_brief",
            kind="text",
            name="ResearchHunter brief",
            uri="specloom://demo/researchhunter",
            content_hash="demo",
        )
        return ContextGraph(
            sources=[demo_source],
            requirements=[
                Requirement(
                    id="req_research_relevance",
                    statement="The system must select research directly related to configured project domains.",
                    priority="high",
                    provenance=[Provenance(source_id=demo_source.id, locator="line:1", quote="The system must return research relevant to the project.", confidence=1.0)],
                ),
                Requirement(
                    id="req_primary_verification",
                    statement="The system must verify primary-source metadata.",
                    priority="high",
                    provenance=[Provenance(source_id=demo_source.id, locator="line:2", quote="The system must verify primary-source metadata.", confidence=1.0)],
                ),
                Requirement(
                    id="req_prepare_issues",
                    statement="The system should prepare GitHub issues for human approval.",
                    priority="high",
                    provenance=[Provenance(source_id=demo_source.id, locator="line:3", quote="The system should prepare GitHub issues for human approval.", confidence=1.0)],
                ),
            ],
            constraints=[
                Constraint(
                    id="con_no_unapproved_writes",
                    statement="The system must not create GitHub issues without human approval.",
                    severity="blocking",
                    provenance=[Provenance(source_id=demo_source.id, locator="line:4", quote="The system must not create GitHub issues without human approval.", confidence=1.0)],
                )
            ],
            tools=tools,
        )

    @staticmethod
    def _hydrate_capability_tools(graph: ContextGraph) -> None:
        existing = {tool.id for tool in graph.tools}
        for capability in graph.capabilities:
            if capability.id not in existing:
                graph.tools.append(ContextTool.model_validate(capability.to_context_tool()))
                existing.add(capability.id)

    def _persist(self, project: ProjectContext) -> None:
        self._repository.save(
            StoredProject(
                project_id=project.project_id,
                workspace_id=project.workspace_id,
                workflow=project.workflow,
                workflow_versions=project.workflow_versions,
                documents=project.documents,
                graph=project.graph.model_dump(mode="json"),
                runs=project.runs,
                artifacts=project.artifacts,
            )
        )

    def persist(self, project_id: str) -> ProjectContext:
        project = self.get(project_id)
        self._persist(project)
        return project

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

    def update_run(self, project_id: str, run_id: str, updates: dict) -> ProjectContext:
        project = self.get(project_id)
        for run in project.runs:
            if run.get("run_id") == run_id:
                run.update(updates)
                self._persist(project)
                break
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

    def save_artifacts(self, project_id: str, artifacts: dict[str, str]) -> ProjectContext:
        project = self.get(project_id)
        project.artifacts = dict(artifacts)
        self._persist(project)
        return project

    def save_artifact_snapshot(
        self,
        project_id: str,
        snapshot_id: str,
        artifacts: dict[str, str],
    ) -> None:
        self._repository.save_artifact_snapshot(
            project_id,
            snapshot_id,
            dict(artifacts),
        )

    def get_artifact_snapshot(
        self,
        project_id: str,
        snapshot_id: str,
    ) -> dict[str, str]:
        return self._repository.get_artifact_snapshot(project_id, snapshot_id)


store = ContextStore()
