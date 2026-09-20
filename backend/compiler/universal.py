from __future__ import annotations

import hashlib
import json
import os
import re

from backend.capabilities.models import CapabilitySpec
from backend.context.models import ContextGraph, ContextTool
from backend.workflow.models import WorkflowIR

from .broker import CapabilityBroker
from .codegen import ArtifactCompiler
from .dependency import DependencyCompiler
from .deployment import DeploymentCompiler
from .decomposition import ProblemDecomposition
from .implementation import ConfiguredImplementationCompiler
from .models import (
    Artifact,
    CompilationBundle,
    CompilerDiagnostic,
    DataModelSpec,
    ServiceSpec,
    SoftwareSpec,
)
from .repository import PlannedFile, RepositoryCompiler
from .capability_discovery import BedrockCapabilityDiscovery, DiscoveredCapability
from .semantic_acceptance import (
    AcceptanceReview,
    BedrockSemanticAcceptanceReviewer,
    BedrockSemanticAcceptanceSynthesizer,
    GeneratedAcceptanceSet,
    SemanticAcceptanceEngine,
    render_synthesized_acceptance,
    validate_generated_cases,
)
from .synthesizer import infer_capability_requirements, synthesize_missing_capabilities
from .system_ir import SystemCompiler


class UniversalCompiler:
    """Bridge from arbitrary user intent to system, workflow, and artifacts."""

    def __init__(self) -> None:
        self.capability_mode = os.getenv(
            "SPECL00M_CAPABILITY_MODE",
            os.getenv("SPECL00M_IMPLEMENTATION_MODE", "deterministic"),
        ).lower()
        self._capability_discovery_cache: dict[str, tuple[DiscoveredCapability, ...]] = {}
        self.acceptance_mode = os.getenv(
            "SPECL00M_ACCEPTANCE_MODE",
            os.getenv("SPECL00M_IMPLEMENTATION_MODE", "deterministic"),
        ).lower()

    @staticmethod
    def _autonomous_mode(configured: str, autonomous: bool) -> str:
        if configured in {"bedrock", "deterministic", "off"}:
            return "bedrock" if autonomous and configured == "deterministic" else configured
        if autonomous:
            return "bedrock"
        return configured

    def prepare(
        self,
        goal: str,
        context: ContextGraph,
        *,
        autonomous: bool = False,
    ) -> ContextGraph:
        base_context = context.model_copy(
            update={
                "capabilities": [
                    item
                    for item in context.capabilities
                    if item.kind != "synthesized"
                ]
            }
        )
        discovered = self._discover_open_world(
            goal,
            base_context,
            autonomous=autonomous,
        )
        synthesized, _, _ = synthesize_missing_capabilities(
            goal,
            base_context,
            discovered=discovered,
        )
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
        *,
        autonomous: bool = False,
        problem_decomposition: ProblemDecomposition | None = None,
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
        merged_context = self.prepare(
            goal,
            context,
            autonomous=autonomous,
        )
        discovered = self._discover_open_world(
            goal,
            base_context,
            autonomous=autonomous,
        )
        synthesized, _, plans = synthesize_missing_capabilities(
            goal,
            base_context,
            discovered=discovered,
        )
        requirements = infer_capability_requirements(goal, merged_context)

        service_specs = self._services(goal, synthesized)
        data_models = [
            DataModelSpec(
                name=re.sub(
                    r"[^A-Za-z0-9_]+",
                    "_",
                    entity.name,
                ).strip("_") or "Entity",
                fields=(
                    entity.fields
                    if entity.fields
                    else [{"name": "id", "type": "string"}]
                ),
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
            problem_decomposition=(
                problem_decomposition.model_dump(mode="json")
                if problem_decomposition is not None
                else {}
            ),
        )

        system_ir = SystemCompiler().compile(
            goal=goal,
            context=merged_context,
            workflow=workflow,
            services=service_specs,
            data_models=data_models,
            problem_decomposition=(
                problem_decomposition.model_dump(mode="json")
                if problem_decomposition is not None
                else {}
            ),
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
        acceptance_manifest_artifact = next(
            (
                item
                for item in repo_files
                if item.path == "generated/repository/tests/independent-acceptance.json"
            ),
            None,
        )
        acceptance_unverified: list[str] = []
        user_acceptance_case_count = 0
        if acceptance_manifest_artifact is not None:
            try:
                acceptance_manifest = json.loads(acceptance_manifest_artifact.content)
                acceptance_unverified = [
                    str(item)
                    for item in acceptance_manifest.get("unverified_criteria", [])
                ]
                user_acceptance_case_count = len(
                    acceptance_manifest.get("cases", [])
                )
            except json.JSONDecodeError:
                acceptance_unverified = ["independent acceptance manifest is invalid"]

        acceptance_review: AcceptanceReview | None = None
        generated_acceptance: GeneratedAcceptanceSet | None = None
        model_acceptance_errors: list[str] = []

        if (
            self._autonomous_mode(self.acceptance_mode, autonomous) == "bedrock"
            and (user_acceptance_case_count == 0 or acceptance_unverified)
        ):
            try:
                missing_criterion_ids = {
                    criterion.id
                    for criterion in system_ir.acceptance_criteria
                    if (
                        criterion.required
                        and criterion.source in {"requirement", "constraint"}
                        and (
                            not acceptance_unverified
                            or criterion.statement in set(acceptance_unverified)
                        )
                    )
                }
                (
                    generated_acceptance,
                    acceptance_review,
                    model_acceptance_errors,
                ) = SemanticAcceptanceEngine(
                    synthesizer=BedrockSemanticAcceptanceSynthesizer(),
                    reviewer=BedrockSemanticAcceptanceReviewer(),
                    max_attempts=2,
                ).compile(
                    goal=goal,
                    context=merged_context,
                    system_ir=system_ir,
                    criterion_ids=missing_criterion_ids or None,
                )
                if not model_acceptance_errors and generated_acceptance and generated_acceptance.cases:
                        repo_files.extend(
                            [
                                PlannedFile(
                                    path="generated/repository/tests/synthesized_acceptance.py",
                                    kind="test",
                                    content=render_synthesized_acceptance(
                                        generated_acceptance
                                    ),
                                    generated_from=[
                                        case.criterion_id
                                        for case in generated_acceptance.cases
                                    ],
                                ),
                                PlannedFile(
                                    path="generated/repository/tests/synthesized-acceptance.json",
                                    kind="test",
                                    content=(
                                        json.dumps(
                                            {
                                                "cases": [
                                                    case.model_dump(mode="json")
                                                    for case in generated_acceptance.cases
                                                ],
                                                "uncovered_criteria": generated_acceptance.uncovered_criteria,
                                                "review": acceptance_review.model_dump(mode="json"),
                                            },
                                            indent=2,
                                            sort_keys=True,
                                        )
                                        + "\n"
                                    ),
                                    generated_from=[
                                        case.criterion_id
                                        for case in generated_acceptance.cases
                                    ],
                                ),
                            ]
                        )
                else:
                    model_acceptance_errors.append(
                        "semantic acceptance compiler produced no complete case set"
                    )
            except (RuntimeError, ValueError, TypeError, json.JSONDecodeError) as exc:
                model_acceptance_errors = [
                    f"autonomous acceptance synthesis failed: {exc}"
                ]

        model_acceptance_proven = bool(
            generated_acceptance
            and generated_acceptance.cases
            and not model_acceptance_errors
            and acceptance_review is not None
            and acceptance_review.approved
        )
        acceptance_case_count = (
            user_acceptance_case_count
            + len(generated_acceptance.cases)
            if generated_acceptance is not None
            else user_acceptance_case_count
        )
        acceptance_origin = (
            "mixed"
            if user_acceptance_case_count and generated_acceptance is not None
            else "user"
            if user_acceptance_case_count
            else "model"
            if generated_acceptance is not None
            else "none"
        )
        acceptance_reviewed = (
            bool(user_acceptance_case_count and not acceptance_unverified)
            if user_acceptance_case_count
            else bool(acceptance_review and acceptance_review.approved)
        )
        acceptance_proven = (
            bool(user_acceptance_case_count > 0 and not acceptance_unverified)
            if generated_acceptance is None
            else model_acceptance_proven
        )

        if model_acceptance_proven:
            acceptance_unverified = []
            acceptance_reviewed = True
            acceptance_proven = True
        elif model_acceptance_errors:
            acceptance_unverified.extend(model_acceptance_errors)
            acceptance_proven = False

        spec = spec.model_copy(
            update={
                "acceptance_proven": acceptance_proven,
                "acceptance_reviewed": acceptance_reviewed,
                "acceptance_origin": acceptance_origin,
                "acceptance_case_count": acceptance_case_count,
                "acceptance_unverified_criteria": acceptance_unverified,
            }
        )
        bundle.acceptance_review = (
            acceptance_review.model_dump(mode="json")
            if acceptance_review
            else {}
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
        spec = spec.model_copy(
            update={
                "implementation_mode": implementation_compiler.mode,
                "implementation_materialized": implementation_compiler.materialized,
                "implementation_uncovered_steps": list(implementation_compiler.uncovered_steps),
                "acceptance_proven": acceptance_proven,
                "acceptance_reviewed": acceptance_reviewed,
                "acceptance_origin": acceptance_origin,
                "acceptance_case_count": acceptance_case_count,
                "acceptance_unverified_criteria": acceptance_unverified,
            }
        )
        bundle.spec = spec

        by_path = {item.path: item for item in bundle.artifacts}
        system_spec = by_path.get("generated/spec/system-spec.json")
        if system_spec is not None:
            by_path[system_spec.path] = system_spec.model_copy(
                update={
                    "content": json.dumps(
                        spec.model_dump(mode="json"),
                        indent=2,
                        sort_keys=True,
                    )
                    + "\n",
                    "sha256": "",
                }
            ).with_hash()
        bundle.artifacts = list(by_path.values())

        bundle.diagnostics.extend(implementation_diagnostics)
        if acceptance_unverified:
            bundle.diagnostics.append(
                CompilerDiagnostic(
                    severity="warning",
                    code="acceptance-criteria-unverified",
                    message=(
                        "Required acceptance criteria are not backed by verifier-owned "
                        "user examples: " + "; ".join(acceptance_unverified)
                    ),
                )
            )
        dependency_compiler = DependencyCompiler()
        dependency_plan, dependency_diagnostics = dependency_compiler.compile(bundle.artifacts)
        bundle.artifacts, dependency_materialization_diagnostics = dependency_compiler.materialize_allowed(
            bundle.artifacts,
            dependency_plan,
        )
        dependency_plan, dependency_recheck_diagnostics = dependency_compiler.compile(bundle.artifacts)
        bundle.dependencies = {
            "declared": list(dependency_plan.declared),
            "required": list(dependency_plan.required),
            "unresolved": list(dependency_plan.unresolved),
        }
        bundle.diagnostics.extend(
            [*dependency_diagnostics, *dependency_materialization_diagnostics, *dependency_recheck_diagnostics]
        )

        capability_binding_plans = CapabilityBroker().plan(
            requirements,
            merged_context,
        )
        required_by_id = {
            item.id: item
            for item in requirements
            if item.required
        }
        capability_by_id = {
            item.id: item
            for item in merged_context.capabilities
        }
        contract_unverified_families = sorted(
            {
                requirement.family
                for binding in capability_binding_plans
                if (
                    (requirement := required_by_id.get(binding.requirement_id))
                    and requirement.external
                    and (
                        binding.selected is None
                        or capability_by_id.get(
                            binding.selected.capability_id,
                        ) is None
                        or capability_by_id[
                            binding.selected.capability_id
                        ].kind
                        not in {"configured_api", "openapi"}
                    )
                )
            }
        )
        spec = spec.model_copy(
            update={
                "contract_proven": not contract_unverified_families,
                "contract_unverified_families": contract_unverified_families,
            }
        )
        bundle.spec = spec

        by_path = {item.path: item for item in bundle.artifacts}
        system_spec = by_path.get("generated/spec/system-spec.json")
        if system_spec is not None:
            by_path[system_spec.path] = system_spec.model_copy(
                update={
                    "content": json.dumps(
                        spec.model_dump(mode="json"),
                        indent=2,
                        sort_keys=True,
                    )
                    + "\n",
                    "sha256": "",
                }
            ).with_hash()
        bundle.artifacts = list(by_path.values())

        # Finalize deployment metadata only after every source/config mutation
        # has finished, so the digest covers the complete generated artifact set.
        deployable_artifacts = [
            item
            for item in bundle.artifacts
            if item.path != "generated/deploy/deployment-plan.json"
        ]
        deployment_plan = DeploymentCompiler().compile(
            spec,
            deployable_artifacts,
            provisioning_ready=bool(bundle.provisioning.get("ready", False)),
        )
        deployment_artifact = Artifact(
            path="generated/deploy/deployment-plan.json",
            kind="infrastructure",
            content=json.dumps(
                deployment_plan.model_dump(mode="json"),
                indent=2,
                sort_keys=True,
            )
            + "\n",
            generated_from=[spec.id],
        ).with_hash()
        bundle.artifacts = [*deployable_artifacts, deployment_artifact]
        bundle.deployment = deployment_plan.model_dump(mode="json")
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
            for plan in capability_binding_plans
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

    def _discover_open_world(
        self,
        goal: str,
        context: ContextGraph,
        *,
        autonomous: bool = False,
    ) -> tuple[DiscoveredCapability, ...]:
        if self._autonomous_mode(self.capability_mode, autonomous) != "bedrock":
            return ()
        cache_key = hashlib.sha256(
            (
                goal.strip().lower()
                + "|"
                + "|".join(
                    sorted(
                        capability.id
                        for capability in context.capabilities
                        if capability.kind != "synthesized"
                    )
                )
            ).encode("utf-8")
        ).hexdigest()
        cached = self._capability_discovery_cache.get(cache_key)
        if cached is not None:
            return cached

        discovered = tuple(
            BedrockCapabilityDiscovery().discover(
                goal=goal,
                context=context,
            ).capabilities
        )
        self._capability_discovery_cache[cache_key] = discovered
        return discovered

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

        if (
            not UniversalCompiler._is_browser_automation_goal(goal)
            and re.search(
                r"\b(ui|dashboard|frontend|website|web app|application)\b",
                goal,
                re.I,
            )
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
        # Execution intent must outrank nouns such as "website". A goal that
        # operates on an existing site is an agent/browser workload, while a
        # goal that builds a web product is an application workload.
        if UniversalCompiler._is_browser_automation_goal(goal):
            return "agent_service"
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
    def _is_browser_automation_goal(goal: str) -> bool:
        return bool(
            re.search(
                r"\b(open|navigate|visit|browse|click|scrape|extract|collect|monitor)\b",
                goal,
                re.I,
            )
            and re.search(
                r"\b(website|web\s+page|webpage|site|browser)\b",
                goal,
                re.I,
            )
        )

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
