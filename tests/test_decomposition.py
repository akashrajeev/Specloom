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




def test_implementation_synthesis_retries_uncovered_steps(monkeypatch):
    from backend.compiler.implementation import (
        ConfiguredImplementationCompiler,
        ImplementationPatchSet,
    )
    from backend.compiler.models import Artifact
    from backend.compiler.system_ir import SystemIR
    from backend.workflow.models import Trigger, WorkflowIR

    class FakeImplementationCompiler:
        def __init__(self):
            self.calls = 0
            self.feedback = []

        def compile(self, **kwargs):
            self.calls += 1
            self.feedback.append(list(kwargs.get("feedback") or []))
            path = "generated/repository/app/implementation.py"
            if self.calls == 1:
                content = "def handle(payload, execution):\n    return {\"step\": 1}\n"
                step_ids = ["step-1"]
            else:
                content = "def handle(payload, execution):\n    return {\"step\": 2}\n"
                step_ids = ["step-2"]
            return ImplementationPatchSet(
                patches=[{
                    "path": path,
                    "content": content,
                    "step_ids": step_ids,
                }]
            )

    monkeypatch.setenv("SPECL00M_IMPLEMENTATION_ATTEMPTS", "2")
    compiler = ConfiguredImplementationCompiler()
    compiler.mode = "bedrock"
    fake = FakeImplementationCompiler()
    compiler._impl = fake

    system_ir = SystemIR(
        id="system",
        name="System",
        goal="Compile two responsibilities.",
        workflow_id="workflow",
        problem_decomposition={
            "version": "0.1",
            "normalized_goal": "Compile two responsibilities.",
            "outcome": "Compile two responsibilities.",
            "steps": [
                {"id": "step-1", "objective": "Implement one."},
                {"id": "step-2", "objective": "Implement two.", "dependencies": ["step-1"]},
            ],
        },
    )
    workflow = WorkflowIR(
        ir_version="0.1",
        id="workflow",
        name="Workflow",
        trigger=Trigger(
            id="trigger",
            type="trigger",
            name="Manual",
            config={"mode": "manual"},
        ),
        nodes=[],
        edges=[],
        variables=[],
        policies=[],
        tests=[],
    )
    artifacts = [
        Artifact(
            path="generated/repository/app/implementation.py",
            kind="source",
            content="def handle(payload, execution):\n    return {}\n",
        ).with_hash(),
    ]

    compiled, diagnostics = compiler.compile(
        goal="Compile two responsibilities.",
        context=ContextGraph(),
        system_ir=system_ir,
        workflow=workflow,
        artifacts=artifacts,
    )

    assert len(compiled) == 1
    assert fake.calls == 2
    assert fake.feedback[0]
    assert "step-2" in fake.feedback[0][0]
    assert compiler.uncovered_steps == []
    assert compiler.materialized is True
    assert not any(item.code == "implementation-steps-uncovered" for item in diagnostics)
