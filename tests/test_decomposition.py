import pytest

from backend.compiler.decomposition import (
    ConfiguredProblemDecomposer,
    DeterministicProblemDecomposer,
    ProblemDecomposition,
)
from backend.context.models import ContextGraph, Requirement
from backend.compiler.deployment import DeploymentCompiler
from backend.compiler.models import SoftwareSpec


def test_deterministic_decomposer_produces_bounded_dependency_graph():
    context = ContextGraph(
        requirements=[
            Requirement(id="r1", statement="The system must persist invoices.", priority="high"),
            Requirement(id="r2", statement="The system must send email alerts.", priority="high"),
        ]
    )
    result = DeterministicProblemDecomposer().compile(
        goal="Build an invoice monitoring service.",
        context=context,
    )

    assert isinstance(result, ProblemDecomposition)
    assert result.normalized_goal == "Build an invoice monitoring service."
    assert 1 <= len(result.steps) <= 24
    assert result.steps[0].id == "step-1"
    assert result.steps[1].dependencies == ["step-1"]
    assert any(step.implementation_kind == "data" for step in result.steps)
    assert any(step.implementation_kind == "adapter" for step in result.steps)


def test_decomposition_enrichment_turns_subproblems_into_traceable_requirements():
    context = ContextGraph()
    decomposition = ProblemDecomposition(
        normalized_goal="Create a ticketing system.",
        outcome="Create a ticketing system.",
        steps=[
            {
                "id": "step-1",
                "objective": "Persist incoming tickets.",
                "responsibilities": ["persist tickets"],
                "outputs": ["ticket-record"],
                "implementation_kind": "data",
            },
            {
                "id": "step-2",
                "objective": "Notify the support team.",
                "responsibilities": ["send notification"],
                "inputs": ["ticket-record"],
                "outputs": ["notification-result"],
                "dependencies": ["step-1"],
                "implementation_kind": "adapter",
            },
        ],
    )

    enriched = DeterministicProblemDecomposer.enrich_context(context, decomposition)

    assert len(enriched.requirements) == 2
    assert all(item.provenance for item in enriched.requirements)
    assert {item.name for item in enriched.entities} == {
        "ticket-record",
        "notification-result",
    }
    assert any(source.name == "Problem Decomposer" for source in enriched.sources)


def test_autonomous_mode_promotes_deterministic_configuration():
    configured = ConfiguredProblemDecomposer()
    configured.mode = "deterministic"

    selected = configured._mode_for_request(configured.mode, autonomous=True)

    assert selected == "bedrock"


def test_explicit_off_remains_off_for_autonomous_requests():
    configured = ConfiguredProblemDecomposer()
    configured.mode = "off"

    assert configured._mode_for_request(configured.mode, autonomous=True) == "off"



def test_decomposition_rejects_cycles():
    with pytest.raises(ValueError, match="cycle"):
        ProblemDecomposition(
            normalized_goal="Cycle test.",
            outcome="Cycle test.",
            steps=[
                {"id": "step-a", "objective": "A", "dependencies": ["step-b"]},
                {"id": "step-b", "objective": "B", "dependencies": ["step-a"]},
            ],
        )


def test_production_is_blocked_when_decomposition_steps_are_uncovered():
    spec = SoftwareSpec(
        id="coverage-test",
        name="Coverage Test",
        goal="Compile a covered system.",
        implementation_materialized=True,
        implementation_uncovered_steps=["step-2"],
        acceptance_proven=True,
        contract_proven=True,
    )
    plan = DeploymentCompiler().compile(spec, [], provisioning_ready=True)

    assert not plan.production_allowed
    assert any("step-2" in reason for reason in plan.blocking_reasons)
