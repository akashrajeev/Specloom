from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from backend.context.models import ContextGraph, Requirement
from backend.workflow.models import Node, Trigger, WorkflowIR

from .universal import UniversalCompiler


@dataclass(frozen=True)
class BenchmarkCase:
    id: str
    goal: str
    expected_architecture: str
    expected_capability_family: str | None = None
    expected_access: str | None = None


@dataclass(frozen=True)
class BenchmarkResult:
    case_id: str
    compiled: bool
    artifact_count: int
    architecture: str
    synthesized_families: tuple[str, ...]
    required_families: tuple[str, ...]
    write_capabilities: tuple[str, ...]
    unresolved_dependencies: tuple[str, ...]
    artifact_hashes_complete: bool
    production_allowed: bool
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
)


def _workflow(case: BenchmarkCase) -> WorkflowIR:
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
                id="output",
                type="output",
                name="Output",
                config={},
            )
        ],
        edges=[{"from": "start", "to": "output"}],
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
        prepared = compiler.prepare(case.goal, context)

        try:
            bundle = compiler.compile(
                case.goal,
                prepared,
                _workflow(case),
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
                    architecture=bundle.spec.architecture_style,
                    synthesized_families=synth_families,
                    required_families=required_families,
                    write_capabilities=write_capabilities,
                    unresolved_dependencies=unresolved_dependencies,
                    artifact_hashes_complete=artifact_hashes_complete,
                    production_allowed=bool(bundle.deployment.get("production_allowed", False)),
                    diagnostics=tuple(item.code for item in bundle.diagnostics),
                )
            )
        except Exception as exc:
            results.append(
                BenchmarkResult(
                    case_id=case.id,
                    compiled=False,
                    artifact_count=0,
                    architecture="failed",
                    synthesized_families=(),
                    required_families=(),
                    write_capabilities=(),
                    unresolved_dependencies=(),
                    artifact_hashes_complete=False,
                    production_allowed=False,
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
    }
