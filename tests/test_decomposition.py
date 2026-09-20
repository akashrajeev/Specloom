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
        "ticket record",
        "notification result",
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
                {"id": "step-a", "objective": "Implement A", "dependencies": ["step-b"]},
                {"id": "step-b", "objective": "Implement B", "dependencies": ["step-a"]},
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
    from backend.workflow.models import Node, Trigger, WorkflowIR

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
        nodes=[
            Node(
                id="node-1",
                type="output",
                name="Output",
            )
        ],
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




def test_workflow_requires_decomposition_step_coverage():
    from backend.workflow.models import Node, Trigger, WorkflowIR
    from backend.workflow.validator import validate_decomposition_coverage

    context = ContextGraph(
        problem_decomposition={
            "steps": [
                {"id": "step-1"},
                {"id": "step-2"},
            ]
        }
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
        nodes=[
            Node(id="node-1", type="agent", name="Worker", config={}),
            Node(id="node-2", type="output", name="Output"),
        ],
        edges=[
            {"from": "trigger", "to": "node-1"},
            {"from": "node-1", "to": "node-2"},
        ],
        variables=[],
        policies=[],
        tests=[],
    )

    errors = validate_decomposition_coverage(workflow, context)
    assert "decomposition step is not covered by workflow: step-1" in errors
    assert "decomposition step is not covered by workflow: step-2" in errors

    workflow.nodes[0].config["decomposition_step_refs"] = ["step-1", "step-2"]
    assert validate_decomposition_coverage(workflow, context) == []


def test_architect_prompt_renders_decomposition_contract():
    from backend.agents.prompt import ArchitectPrompt

    prompt = ArchitectPrompt.render(
        "Create a ticketing service.",
        ContextGraph(
            problem_decomposition={
                "steps": [
                    {
                        "id": "step-1",
                        "objective": "Persist incoming tickets.",
                    }
                ]
            }
        ),
    )

    assert "PROBLEM DECOMPOSITION" in prompt
    assert "step-1" in prompt
    assert "decomposition_step_refs" in prompt




def test_workflow_rejects_unknown_decomposition_step_reference():
    from backend.workflow.models import Node, Trigger, WorkflowIR
    from backend.workflow.validator import validate_decomposition_coverage

    context = ContextGraph(
        problem_decomposition={
            "steps": [{"id": "step-1"}],
        }
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
        nodes=[
            Node(
                id="node-1",
                type="agent",
                name="Worker",
                config={"decomposition_step_refs": ["step-unknown"]},
            ),
            Node(
                id="node-2",
                type="output",
                name="Output",
            ),
        ],
        edges=[
            {"from": "trigger", "to": "node-1"},
            {"from": "node-1", "to": "node-2"},
        ],
        variables=[],
        policies=[],
        tests=[],
    )

    errors = validate_decomposition_coverage(workflow, context)
    assert "node node-1 references unknown decomposition step: step-unknown" in errors
    assert "decomposition step is not covered by workflow: step-1" in errors




def test_decomposition_can_drive_unknown_capability_synthesis():
    from backend.compiler.synthesizer import synthesize_missing_capabilities

    decomposition = ProblemDecomposition(
        normalized_goal="Prepare procurement automation.",
        outcome="Prepare procurement automation.",
        steps=[
            {
                "id": "step-1",
                "objective": "Create the approved purchase order.",
                "implementation_kind": "adapter",
                "capability_families": ["erp"],
            }
        ],
    )

    capabilities, requirements, plans = synthesize_missing_capabilities(
        "Prepare procurement automation.",
        ContextGraph(),
        problem_decomposition=decomposition,
    )

    assert capabilities
    assert requirements
    assert plans
    assert plans[0].family == "erp"
    assert capabilities[0].kind == "synthesized"
    assert "URL" not in capabilities[0].description
    assert capabilities[0].provisioning_env




def test_decomposition_capability_is_bound_even_when_goal_hides_family():
    from backend.compiler.models import Artifact, SoftwareSpec
    from backend.compiler.synthesizer import infer_capability_requirements
    from backend.capabilities.models import CapabilitySpec

    decomposition = ProblemDecomposition(
        normalized_goal="Prepare procurement automation.",
        outcome="Prepare procurement automation.",
        steps=[
            {
                "id": "step-1",
                "objective": "Create the approved purchase order.",
                "implementation_kind": "adapter",
                "capability_families": ["erp"],
            }
        ],
    )
    capability = CapabilitySpec(
        id="synth:erp:test",
        kind="synthesized",
        name="Synthesized erp adapter",
        description="Provider-neutral ERP capability.",
        access="write",
        permissions=["READ", "WRITE"],
        side_effecting=True,
        requires_human_approval=True,
        tags=["erp", "synthesized"],
        input_schema={"type": "object"},
        output_schema={"type": "object"},
    )

    requirements = infer_capability_requirements(
        "Prepare procurement automation.",
        ContextGraph(capabilities=[capability]),
        problem_decomposition=decomposition,
    )

    assert len(requirements) == 1
    assert requirements[0].family == "erp"
    assert requirements[0].access == "write"
    assert requirements[0].external is True




def test_deterministic_implementation_plan_covers_every_decomposition_step():
    from backend.compiler.implementation_plan import (
        DeterministicImplementationPlanner,
        ImplementationPlan,
    )

    decomposition = ProblemDecomposition(
        normalized_goal="Build a procurement service.",
        outcome="Build a procurement service.",
        steps=[
            {
                "id": "step-1",
                "objective": "Validate the purchase request.",
                "implementation_kind": "logic",
            },
            {
                "id": "step-2",
                "objective": "Persist the approved purchase order.",
                "implementation_kind": "data",
                "dependencies": ["step-1"],
            },
            {
                "id": "step-3",
                "objective": "Expose the procurement result.",
                "implementation_kind": "interface",
                "dependencies": ["step-2"],
            },
        ],
    )

    plan = DeterministicImplementationPlanner().compile(
        goal="Build a procurement service.",
        context=ContextGraph(),
        decomposition=decomposition,
    )

    assert isinstance(plan, ImplementationPlan)
    assert {target.step_id for target in plan.targets} == {
        "step-1",
        "step-2",
        "step-3",
    }
    assert {target.path for target in plan.targets} == {
        "generated/repository/app/implementation.py",
        "generated/repository/app/domain.py",
        "generated/repository/app/api.py",
    }
    assert plan.targets[1].dependency_steps == ["step-1"]


def test_implementation_plan_artifact_is_emitted():
    from backend.compiler.codegen import ArtifactCompiler
    from backend.workflow.models import Node
    from backend.compiler.models import SoftwareSpec
    from backend.workflow.models import Trigger, WorkflowIR

    spec = SoftwareSpec(
        id="plan-artifact",
        name="Plan Artifact",
        goal="Build a planned system.",
        problem_decomposition={
            "steps": [{"id": "step-1"}],
        },
        implementation_plan={
            "version": "0.1",
            "goal": "Build a planned system.",
            "targets": [
                {
                    "step_id": "step-1",
                    "path": "generated/repository/app/implementation.py",
                    "symbol": "handle",
                    "purpose": "Implement the business behavior.",
                }
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
        nodes=[
            Node(id="node-1", type="output", name="Output"),
        ],
        edges=[{"from": "trigger", "to": "node-1"}],
        variables=[],
        policies=[],
        tests=[],
    )

    artifacts = ArtifactCompiler().compile(
        spec,
        workflow,
        context=ContextGraph(),
    )
    plan = next(item for item in artifacts.artifacts if item.path == "generated/spec/implementation-plan.json")
    assert '"step_id": "step-1"' in plan.content
