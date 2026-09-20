from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from backend.context.models import ContextGraph, Requirement
from backend.workflow.models import Node, Trigger, WorkflowIR

from .capability_autobind import auto_bind_required_capabilities
from .decomposition import ProblemDecomposition
from .universal import UniversalCompiler


@dataclass(frozen=True)
class BenchmarkCase:
    id: str
    goal: str
    expected_architecture: str
    expected_capability_family: str | None = None
    expected_access: str | None = None
    decomposition_steps: tuple[dict[str, Any], ...] = ()


@dataclass(frozen=True)
class BenchmarkResult:
    case_id: str
    compiled: bool
    artifact_count: int
    decomposition_step_count: int
    workflow_step_coverage_complete: bool
    implementation_plan_step_coverage_complete: bool
    implementation_plan_artifact_present: bool
    end_to_end_trace_complete: bool
    architecture: str
    synthesized_families: tuple[str, ...]
    required_families: tuple[str, ...]
    write_capabilities: tuple[str, ...]
    unresolved_dependencies: tuple[str, ...]
    artifact_hashes_complete: bool
    production_allowed: bool
    blocking_diagnostics: tuple[str, ...]
    diagnostics: tuple[str, ...]


DEFAULT_CASES: tuple[BenchmarkCase, ...] = (
    BenchmarkCase(
        "text-transform",
        "Turn incoming customer text into a concise structured summary.",
        "agent_service",
    ),
    BenchmarkCase(
        "api-service",
        "Build an API service that validates and transforms submitted records.",
        "api_service",
    ),
    BenchmarkCase(
        "email",
        "Every morning send a summary to my email inbox.",
        "agent_service",
        "email",
    ),
    BenchmarkCase(
        "slack",
        "Post a daily status update to Slack.",
        "agent_service",
        "slack",
    ),
    BenchmarkCase(
        "calendar",
        "Create a calendar event when a deadline is detected.",
        "agent_service",
        "calendar",
    ),
    BenchmarkCase(
        "database",
        "Build a service that stores and queries customer records in a database.",
        "api_service",
        "database",
    ),
    BenchmarkCase(
        "payments",
        "Create a checkout workflow and charge the customer.",
        "agent_service",
        "payments",
    ),
    BenchmarkCase(
        "browser",
        "Open a website, collect the specified information, and return a report.",
        "agent_service",
        "browser",
    ),
    BenchmarkCase(
        "dashboard",
        "Build a dashboard web application for monitoring system state.",
        "application",
    ),
    BenchmarkCase(
        "rag",
        "Answer questions from a supplied document corpus with cited evidence.",
        "agent_service",
    ),
    BenchmarkCase(
        "email-read",
        "Read incoming email messages and build a daily summary from them.",
        "agent_service",
        "email",
        "read",
    ),
    BenchmarkCase(
        "storage-write",
        "Upload generated reports to object storage.",
        "agent_service",
        "storage",
        "write",
    ),
    BenchmarkCase(
        "external-ticket",
        "Call an external ticket API to create a ticket.",
        "api_service",
        "external-service",
        "write",
    ),
    BenchmarkCase(
        "hidden-erp",
        "Create an approved purchase order and return the result.",
        "agent_service",
        "erp",
        "write",
        (
            {
                "id": "step-validate-order",
                "objective": "Validate the approved purchase order request.",
                "implementation_kind": "logic",
            },
            {
                "id": "step-create-order",
                "objective": "Create the purchase order in the enterprise system.",
                "implementation_kind": "adapter",
                "dependencies": ["step-validate-order"],
                "capability_families": ["erp"],
            },
        ),
    ),
    BenchmarkCase(
        "hidden-crm",
        "Route qualified customer leads and return the assigned result.",
        "agent_service",
        "crm",
        "write",
        (
            {
                "id": "step-score-lead",
                "objective": "Score the incoming customer lead.",
                "implementation_kind": "logic",
            },
            {
                "id": "step-route-lead",
                "objective": "Create the lead assignment in the customer system.",
                "implementation_kind": "adapter",
                "dependencies": ["step-score-lead"],
                "capability_families": ["crm"],
            },
        ),
    ),
    BenchmarkCase(
        "event-pipeline",
        "When a data event arrives, transform it and persist the resulting record.",
        "agent_service",
        "storage",
        "write",
        (
            {
                "id": "step-transform-event",
                "objective": "Transform the incoming event into the required record shape.",
                "implementation_kind": "logic",
            },
            {
                "id": "step-persist-record",
                "objective": "Persist the transformed record.",
                "implementation_kind": "data",
                "dependencies": ["step-transform-event"],
                "capability_families": ["storage"],
            },
        ),
    ),
    BenchmarkCase(
        "scheduled-research",
        "Every morning research the requested topic and send the findings.",
        "agent_service",
        "email",
        "write",
        (
            {
                "id": "step-research",
                "objective": "Research the requested topic.",
                "implementation_kind": "logic",
            },
            {
                "id": "step-send-report",
                "objective": "Send the completed findings by email.",
                "implementation_kind": "adapter",
                "dependencies": ["step-research"],
                "capability_families": ["email"],
            },
        ),
    ),
)


def _decomposition(case: BenchmarkCase) -> ProblemDecomposition:
    steps = case.decomposition_steps or (
        {
            "id": "step-main",
            "objective": case.goal,
            "implementation_kind": "logic",
        },
    )
    return ProblemDecomposition(
        normalized_goal=case.goal,
        outcome=case.goal,
        steps=list(steps),
    )


def _workflow(
    case: BenchmarkCase,
    decomposition: ProblemDecomposition,
) -> WorkflowIR:
    step_ids = [step.id for step in decomposition.steps]
    return WorkflowIR(
        ir_version="0.1",
        id=f"benchmark-{case.id}",
        name=case.id,
        description=case.goal,
        trigger=Trigger(
            id="start",
            type="trigger",
            name="Start",
            config={"mode": "manual"},
        ),
        nodes=[
            Node(
                id="worker",
                type="agent",
                name="Compiled Worker",
                config={"decomposition_step_refs": step_ids},
            ),
            Node(
                id="output",
                type="output",
                name="Output",
                config={},
            ),
        ],
        edges=[
            {"from": "start", "to": "worker"},
            {"from": "worker", "to": "output"},
        ],
        variables=[],
        policies=[],
        tests=[],
    )


def run_benchmark(
    cases: tuple[BenchmarkCase, ...] = DEFAULT_CASES,
) -> list[BenchmarkResult]:
    compiler = UniversalCompiler()
    results: list[BenchmarkResult] = []

    for case in cases:
        context = ContextGraph(
            requirements=[
                Requirement(
                    id=f"req-{case.id}",
                    statement=f"The system must satisfy: {case.goal}",
                    priority="high",
                )
            ]
        )
        decomposition = _decomposition(case)
        context.problem_decomposition = decomposition.model_dump(mode="json")
        prepared = compiler.prepare(
            case.goal,
            context,
            problem_decomposition=decomposition,
        )
        benchmark_workflow, _ = auto_bind_required_capabilities(
            _workflow(case, decomposition),
            prepared,
            goal=case.goal,
            problem_decomposition=decomposition,
        )

        try:
            bundle = compiler.compile(
                case.goal,
                prepared,
                benchmark_workflow,
                problem_decomposition=decomposition,
            )
            synth_families = tuple(
                sorted(
                    item.family
                    for item in bundle.spec.synthesized_capabilities
                )
            )
            required_families = tuple(
                sorted(item.family for item in bundle.spec.capability_requirements)
            )
            write_capabilities = tuple(
                sorted(
                    item.family
                    for item in bundle.spec.capability_requirements
                    if item.access == "write"
                )
            )
            unresolved_dependencies = tuple(bundle.dependencies.get("unresolved", []))
            artifact_hashes_complete = all(item.sha256 for item in bundle.artifacts)
            decomposition_ids = {step.id for step in decomposition.steps}
            workflow_refs = {
                str(ref)
                for node in benchmark_workflow.nodes
                for ref in node.config.get("decomposition_step_refs", [])
            }
            plan_targets = bundle.spec.implementation_plan.get("targets", [])
            plan_ids = {
                str(item.get("step_id"))
                for item in plan_targets
                if isinstance(item, dict)
            }
            implementation_plan_artifact_present = any(
                item.path == "generated/spec/implementation-plan.json"
                for item in bundle.artifacts
            )
            workflow_step_coverage_complete = decomposition_ids <= workflow_refs
            implementation_plan_step_coverage_complete = decomposition_ids <= plan_ids
            end_to_end_trace_complete = (
                workflow_step_coverage_complete
                and implementation_plan_step_coverage_complete
                and implementation_plan_artifact_present
            )
            expected_ok = (
                bundle.spec.architecture_style == case.expected_architecture
                and (
                    case.expected_capability_family is None
                    or case.expected_capability_family in required_families
                    or case.expected_capability_family in synth_families
                )
                and (
                    case.expected_access is None
                    or any(
                        item.family == case.expected_capability_family
                        and item.access == case.expected_access
                        for item in bundle.spec.capability_requirements
                    )
                )
                and not unresolved_dependencies
                and artifact_hashes_complete
                and not any(item.severity == "blocking" for item in bundle.diagnostics)
            )
            results.append(
                BenchmarkResult(
                    case_id=case.id,
                    compiled=expected_ok,
                    artifact_count=len(bundle.artifacts),
                    decomposition_step_count=len(decomposition.steps),
                    workflow_step_coverage_complete=workflow_step_coverage_complete,
                    implementation_plan_step_coverage_complete=implementation_plan_step_coverage_complete,
                    implementation_plan_artifact_present=implementation_plan_artifact_present,
                    end_to_end_trace_complete=end_to_end_trace_complete,
                    architecture=bundle.spec.architecture_style,
                    synthesized_families=synth_families,
                    required_families=required_families,
                    write_capabilities=write_capabilities,
                    unresolved_dependencies=unresolved_dependencies,
                    artifact_hashes_complete=artifact_hashes_complete,
                    production_allowed=bool(bundle.deployment.get("production_allowed", False)),
                    blocking_diagnostics=tuple(
                        item.code for item in bundle.diagnostics if item.severity == "blocking"
                    ),
                    diagnostics=tuple(item.code for item in bundle.diagnostics),
                )
            )
        except Exception as exc:
            results.append(
                BenchmarkResult(
                    case_id=case.id,
                    compiled=False,
                    artifact_count=0,
                    decomposition_step_count=len(decomposition.steps),
                    workflow_step_coverage_complete=False,
                    implementation_plan_step_coverage_complete=False,
                    implementation_plan_artifact_present=False,
                    end_to_end_trace_complete=False,
                    architecture="failed",
                    synthesized_families=(),
                    required_families=(),
                    write_capabilities=(),
                    unresolved_dependencies=(),
                    artifact_hashes_complete=False,
                    production_allowed=False,
                    blocking_diagnostics=(),
                    diagnostics=(str(exc),),
                )
            )

    return results


def summarize(results: list[BenchmarkResult]) -> dict[str, Any]:
    compiled = [item for item in results if item.compiled]
    return {
        "cases": len(results),
        "compiled": len(compiled),
        "compile_coverage": (
            len(compiled) / len(results) if results else 0.0
        ),
        "average_artifacts": (
            sum(item.artifact_count for item in compiled) / len(compiled)
            if compiled
            else 0.0
        ),
        "architectures": sorted({item.architecture for item in compiled}),
        "synthesized_families": sorted({
            family
            for item in compiled
            for family in item.synthesized_families
        }),
        "required_families": sorted({
            family
            for item in compiled
            for family in item.required_families
        }),
        "write_capabilities": sorted({
            family
            for item in compiled
            for family in item.write_capabilities
        }),
        "dependency_failures": sum(bool(item.unresolved_dependencies) for item in results),
        "artifact_integrity_coverage": (
            sum(item.artifact_hashes_complete for item in results) / len(results)
            if results else 0.0
        ),
        "production_allowed_cases": sum(item.production_allowed for item in compiled),
        "end_to_end_trace_coverage": (
            sum(item.end_to_end_trace_complete for item in results) / len(results)
            if results else 0.0
        ),
        "implementation_plan_coverage": (
            sum(item.implementation_plan_step_coverage_complete for item in results) / len(results)
            if results else 0.0
        ),
    }
