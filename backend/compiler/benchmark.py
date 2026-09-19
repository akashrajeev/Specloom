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


@dataclass(frozen=True)
class BenchmarkResult:
    case_id: str
    compiled: bool
    artifact_count: int
    architecture: str
    synthesized_families: tuple[str, ...]
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
            results.append(
                BenchmarkResult(
                    case_id=case.id,
                    compiled=True,
                    artifact_count=len(bundle.artifacts),
                    architecture=bundle.spec.architecture_style,
                    synthesized_families=synth_families,
                    diagnostics=tuple(
                        item.code for item in bundle.diagnostics
                    ),
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
    }
