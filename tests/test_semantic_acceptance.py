from __future__ import annotations

from backend.compiler.semantic_acceptance import (
    AcceptanceReview,
    GeneratedAcceptanceCase,
    GeneratedAcceptanceSet,
    validate_generated_cases,
)
from backend.compiler.universal import UniversalCompiler
from backend.context.models import ContextGraph, ContextExample, Provenance, Requirement, Source


def test_generated_acceptance_validation_requires_criterion_coverage():
    from backend.compiler.system_ir import SystemCompiler

    context = ContextGraph(
        sources=[Source(id="source-1", kind="text", name="Requirements")],
        requirements=[
            Requirement(
                id="req-1",
                statement="Return the normalized customer name.",
                provenance=[Provenance(source_id="source-1")],
            )
        ],
    )
    system = SystemCompiler().compile(
        "Return normalized customer names.",
        context,
        _workflow(),
        [],
        [],
    )

    cases = GeneratedAcceptanceSet(cases=[])
    errors = validate_generated_cases(cases, system)

    assert errors == ["criterion-0"] or any("criterion" in item for item in errors)


def test_bedrock_mode_can_autonomously_synthesize_and_review_acceptance_cases(monkeypatch):
    import backend.compiler.universal as universal_module

    from backend.compiler.semantic_acceptance import (
        AcceptanceReview,
        GeneratedAcceptanceCase,
        GeneratedAcceptanceSet,
    )

    class FakeSynthesizer:
        def __init__(self):
            pass

        def synthesize(self, *, goal, context, system_ir):
            criterion = next(
                item
                for item in system_ir.acceptance_criteria
                if item.source == "requirement"
            )
            return GeneratedAcceptanceSet(
                cases=[
                    GeneratedAcceptanceCase(
                        id="case-1",
                        criterion_id=criterion.id,
                        input={"name": "  Alice  "},
                        expected={"name": "Alice"},
                        rationale="Covers the normalization requirement.",
                    )
                ]
            )

    class FakeReviewer:
        def __init__(self):
            pass

        def review(self, *, goal, context, system_ir, cases):
            return AcceptanceReview(
                status="approved",
                approved=True,
                summary="All required criteria are covered by deterministic cases.",
            )

    monkeypatch.setattr(
        universal_module,
        "BedrockSemanticAcceptanceSynthesizer",
        FakeSynthesizer,
    )
    monkeypatch.setattr(
        universal_module,
        "BedrockSemanticAcceptanceReviewer",
        FakeReviewer,
    )
    monkeypatch.setenv("SPECL00M_ACCEPTANCE_MODE", "bedrock")

    source = Source(id="source-1", kind="text", name="Requirements")
    requirement = Requirement(
        id="req-1",
        statement="Return the normalized customer name.",
        provenance=[Provenance(source_id=source.id)],
    )
    context = ContextGraph(
        sources=[source],
        requirements=[requirement],
    )

    compiler = UniversalCompiler()
    bundle = compiler.compile(
        "Create a service that normalizes customer names.",
        context,
        _workflow(),
    )

    assert bundle.spec.acceptance_origin == "model"
    assert bundle.spec.acceptance_reviewed is True
    assert bundle.spec.acceptance_case_count == 1
    assert bundle.spec.acceptance_proven is True
    assert bundle.acceptance_review["approved"] is True

    paths = {item.path for item in bundle.artifacts}
    assert "generated/repository/tests/synthesized_acceptance.py" in paths
    assert "generated/repository/tests/synthesized-acceptance.json" in paths


def _workflow():
    from backend.workflow.models import WorkflowIR, WorkflowNode

    return WorkflowIR(
        id="semantic-acceptance-test",
        name="Semantic acceptance test",
        description="Run generated semantic checks.",
        nodes=[
            WorkflowNode(
                id="start",
                kind="start",
                name="Start",
            ),
            WorkflowNode(
                id="agent",
                kind="agent",
                name="Agent",
                config={"system_goal": "normalize customer names"},
            ),
            WorkflowNode(
                id="output",
                kind="end",
                name="Output",
            ),
        ],
        edges=[
            {"from": "start", "to": "agent"},
            {"from": "agent", "to": "output"},
        ],
    )
