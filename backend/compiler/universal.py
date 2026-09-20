from __future__ import annotations

import hashlib
import re

from backend.capabilities.models import CapabilitySpec
from backend.context.models import ContextGraph, ContextTool
from backend.workflow.models import WorkflowIR

from .broker import CapabilityBroker
from .dependency import DependencyCompiler
from .codegen import ArtifactCompiler
from .implementation import ConfiguredImplementationCompiler
from .models import (
    Artifact,
    CompilationBundle,
    CompilerDiagnostic,
    DataModelSpec,
    ServiceSpec,
    SoftwareSpec,
)
from .repository import RepositoryCompiler
from .synthesizer import synthesize_missing_capabilities
from .system_ir import SystemCompiler


class UniversalCompiler:
    """Bridge from arbitrary user intent to system, workflow, and artifacts."""

    def prepare(self, goal: str, context: ContextGraph) -> ContextGraph:
        base_context = context.model_copy(
            update={
                "capabilities": [
                    item
                    for item in context.capabilities
                    if item.kind != "synthesized"
                ]
            }
        )
        synthesized, _, _ = synthesize_missing_capabilities(goal, base_context)
        if not synthesized:
            return context

        existing = {item.id for item in context.capabilities}
        capabilities = [*context.capabilities]
        for capability in synthesized:
            if capability.id not in existing:
                capabilities.append(capability)

        tools = [*context.tools]
        existing_tools = {tool.id for tool in tools}
        for capability in synthesized:
            if capability.id not in existing_tools:
                tools.append(
                    ContextTool.model_validate(capability.to_context_tool())
                )

        return context.model_copy(
            update={
                "capabilities": capabilities,
                "tools": tools,
            }
        )

    def compile(
        self,
        goal: str,
        context: ContextGraph,
        workflow: WorkflowIR,
    ) -> CompilationBundle:
        base_context = context.model_copy(
            update={
                "capabilities": [
                    item
                    for item in context.capabilities
                    if item.kind != "synthesized"
                ]
            }
        )
        synthesized, requirements, plans = synthesize_missing_capabilities(
            goal,
            base_context,
        )
        merged_context = self.prepare(goal, context)

        service_specs = self._services(goal, synthesized)
        data_models = [
            DataModelSpec(
                name=re.sub(
                    r"[^A-Za-z0-9_]+",
                    "_",
                    entity.name,
                ).strip("_") or "Entity",
                fields=[{"name": "id", "type": "string"}],
            )
            for entity in context.entities[:20]
        ]

        style = self._architecture_style(goal)
        spec = SoftwareSpec(
            id=self._stable_id(goal),
            name=self._project_name(goal),
            goal=goal,
            architecture_style=style,
            services=service_specs,
            capability_requirements=requirements,
            synthesized_capabilities=plans,
            data_models=data_models,
            environment=sorted(
                {
                    env
                    for plan in plans
                    for env in plan.provisioning_env
                }
            ),
            deployment_targets=["container", "aws"],
            workflow_id=workflow.id,
            source_refs=[source.id for source in merged_context.sources],
        )

        system_ir = SystemCompiler().compile(
            goal=goal,
            context=merged_context,
            workflow=workflow,
            services=service_specs,
            data_models=data_models,
        )

        bundle = ArtifactCompiler().compile(
            spec,
            workflow,
            context=merged_context,
        )
        repo_files = RepositoryCompiler().compile(
            system_ir,
            workflow,
            context=merged_context,
        )
        bundle.artifacts.extend(
            Artifact(
                path=item.path,
                kind=item.kind,
                content=item.content,
                executable=item.executable,
                generated_from=list(item.generated_from),
            ).with_hash()
            for item in repo_files
        )

        implementation_compiler = ConfiguredImplementationCompiler()
        bundle.artifacts, implementation_diagnostics = implementation_compiler.compile(
            goal=goal,
            context=merged_context,
            system_ir=system_ir,
            workflow=workflow,
            artifacts=bundle.artifacts,
        )
        bundle.diagnostics.extend(implementation_diagnostics)

        dependency_plan, dependency_diagnostics = DependencyCompiler().compile(
            bundle.artifacts,
        )
        bundle.dependencies = {
            "declared": list(dependency_plan.declared),
            "required": list(dependency_plan.required),
            "unresolved": list(dependency_plan.unresolved),
        }
        bundle.diagnostics.extend(dependency_diagnostics)

        bundle.capability_bindings = [
            {
                "requirement_id": plan.requirement_id,
                "selected": (
                    plan.selected.__dict__
                    if plan.selected is not None
                    else None
                ),
                "candidates": [
                    candidate.__dict__
                    for candidate in plan.candidates
                ],
                "needs_synthesis": plan.needs_synthesis,
            }
            for plan in CapabilityBroker().plan(
                requirements,
                merged_context,
            )
        ]
        bundle.system_ir = system_ir.model_dump(mode="json")

        for capability in synthesized:
            used = any(
                str(value) == capability.id
                for node in workflow.nodes
                for value in (
                    node.config.get("tools", [])
                    if node.type == "agent"
                    else [node.config.get("tool_ref")]
                    if node.type == "tool"
                    else []
                )
            )
            if not used:
                bundle.diagnostics.append(
                    CompilerDiagnostic(
                        severity="warning",
                        code="capability-not-wired",
                        message=(
                            f"Synthesized capability {capability.id} was generated "
                            "but the current Workflow IR did not select it."
                        ),
                        capability_id=capability.id,
                    )
                )

        return bundle

    @staticmethod
    def _services(
        goal: str,
        synthesized: list[CapabilitySpec],
    ) -> list[ServiceSpec]:
        services = [
            ServiceSpec(
                id="agent-runtime",
                name="Specloom Agent Runtime",
                runtime="python",
                responsibilities=[
                    "execute the canonical Workflow IR",
                    "enforce policy and approvals",
                ],
                interfaces=["Workflow IR", "runtime API"],
            )
        ]

        if synthesized:
            services.append(
                ServiceSpec(
                    id="capability-adapters",
                    name="Generated Capability Adapter Layer",
                    runtime="python/http",
                    responsibilities=[
                        "provide explicit contracts for missing external capabilities",
                        "keep credentials outside generated source",
                    ],
                    interfaces=[item.id for item in synthesized],
                )
            )

        if re.search(r"\b(api|service|backend|webhook)\b", goal, re.I):
            services.append(
                ServiceSpec(
                    id="api-service",
                    name="Generated API Service",
                    runtime="fastapi",
                    responsibilities=[
                        "expose the generated system as an HTTP service",
                    ],
                    interfaces=["REST/JSON"],
                )
            )

        if re.search(
            r"\b(ui|dashboard|frontend|website|web app|application)\b",
            goal,
            re.I,
        ):
            services.append(
                ServiceSpec(
                    id="web-interface",
                    name="Generated Web Interface",
                    runtime="react",
                    responsibilities=[
                        "present system state and invoke the generated API",
                    ],
                    interfaces=["browser"],
                )
            )

        return services

    @staticmethod
    def _architecture_style(goal: str) -> str:
        if re.search(
            r"\b(ui|dashboard|frontend|website|web app|application)\b",
            goal,
            re.I,
        ):
            return "application"
        if re.search(
            r"\b(api|service|backend|webhook)\b",
            goal,
            re.I,
        ):
            return "api_service"
        return "agent_service"

    @staticmethod
    def _stable_id(goal: str) -> str:
        digest = hashlib.sha1(
            goal.strip().lower().encode("utf-8")
        ).hexdigest()[:10]
        return f"system-{digest}"

    @staticmethod
    def _project_name(goal: str) -> str:
        words = [
            word
            for word in re.findall(r"[A-Za-z0-9]+", goal)
            if len(word) > 2
        ][:5]
        return "Specloom " + (
            " ".join(word.title() for word in words)
            or "Generated System"
        )
