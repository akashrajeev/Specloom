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

    required = [
        item
        for item in system.acceptance_criteria
        if item.required and item.source == "requirement"
    ]
    assert required
    assert errors == [required[0].id]


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

        def synthesize(self, *, goal, context, system_ir, feedback=""):
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
    from backend.workflow.models import Node, Trigger, WorkflowIR

    return WorkflowIR(
        ir_version="0.1",
        id="semantic-acceptance-test",
        name="Semantic acceptance test",
        description="Run generated semantic checks.",
        trigger=Trigger(
            id="trigger",
            type="trigger",
            name="Trigger",
            config={"mode": "manual"},
        ),
        nodes=[
            Node(
                id="start",
                type="agent",
                name="Start",
                config={},
            ),
            Node(
                id="agent",
                type="agent",
                name="Agent",
                config={"system_goal": "normalize customer names"},
            ),
            Node(
                id="output",
                type="output",
                name="Output",
            ),
        ],
        edges=[
            {"from": "trigger", "to": "start"},
            {"from": "start", "to": "agent"},
            {"from": "agent", "to": "output"},
        ],
        variables=[],
        policies=[],
        tests=[],
    )




def test_semantic_acceptance_engine_revises_after_adversarial_rejection():
    from backend.compiler.semantic_acceptance import (
        AcceptanceReview,
        AcceptanceReviewFinding,
        GeneratedAcceptanceCase,
        GeneratedAcceptanceSet,
        SemanticAcceptanceEngine,
    )
    from backend.compiler.system_ir import SystemCompiler

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
    system = SystemCompiler().compile(
        "Return the normalized customer name.",
        context,
        _workflow(),
        [],
        [],
    )

    synth_calls = []

    class Synthesizer:
        def synthesize(self, *, goal, context, system_ir, feedback=""):
            synth_calls.append(feedback)
            criterion = next(
                item
                for item in system_ir.acceptance_criteria
                if item.source == "requirement"
            )
            return GeneratedAcceptanceSet(
                cases=[
                    GeneratedAcceptanceCase(
                        id=f"case-{len(synth_calls)}",
                        criterion_id=criterion.id,
                        input={"name": "  Alice  "},
                        expected=(
                            {"wrong": True}
                            if len(synth_calls) == 1
                            else {"name": "Alice"}
                        ),
                    )
                ]
            )

    review_calls = 0

    class Reviewer:
        def review(self, *, goal, context, system_ir, cases):
            nonlocal review_calls
            review_calls += 1
            if review_calls == 1:
                return AcceptanceReview(
                    status="needs_revision",
                    approved=False,
                    summary="First hypothesis is not deterministic.",
                    findings=[
                        AcceptanceReviewFinding(
                            severity="blocking",
                            criterion_id=cases.cases[0].criterion_id,
                            message="Use the normalized name as the expected result.",
                        )
                    ],
                )
            return AcceptanceReview(
                status="approved",
                approved=True,
                summary="Revised case approved.",
            )

    cases, review, errors = SemanticAcceptanceEngine(
        synthesizer=Synthesizer(),
        reviewer=Reviewer(),
        max_attempts=2,
    ).compile(
        goal="Return the normalized customer name.",
        context=context,
        system_ir=system,
    )

    assert errors == []
    assert review is not None and review.approved is True
    assert cases is not None
    assert cases.cases[0].expected == {"name": "Alice"}
    assert len(synth_calls) == 2
    assert "normalized name" in synth_calls[1]
