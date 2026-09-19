import sys
import types

from backend.agents.reviewer import ArchitectureReview, BedrockArchitectureReviewer
from backend.context.models import ContextGraph, Requirement
from backend.workflow.models import WorkflowIR


def test_review_model_accepts_structured_findings():
    review = ArchitectureReview.model_validate(
        {
            "status": "needs_revision",
            "summary": "Missing an approval boundary.",
            "findings": [
                {
                    "severity": "blocking",
                    "category": "safety",
                    "message": "Write requires approval.",
                    "rationale": "The workflow changes external state.",
                    "node_id": "write",
                    "requirement_refs": ["req_1"],
                }
            ],
        }
    )
    assert review.findings[0].node_id == "write"
    assert review.status == "needs_revision"


def test_reviewer_uses_current_strands_structured_output(monkeypatch):
    class FakeAgent:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

        def __call__(self, prompt, *, structured_output_model):
            assert "REQUIREMENT" in prompt.upper()
            return types.SimpleNamespace(
                structured_output=ArchitectureReview(
                    status="passed",
                    summary="Looks good.",
                    findings=[],
                )
            )

    fake_strands = types.ModuleType("strands")
    fake_strands.Agent = FakeAgent
    fake_models = types.ModuleType("strands.models")
    fake_models.BedrockModel = lambda **kwargs: kwargs
    monkeypatch.setitem(sys.modules, "strands", fake_strands)
    monkeypatch.setitem(sys.modules, "strands.models", fake_models)

    workflow = WorkflowIR.model_validate(
        {
            "ir_version": "0.1",
            "id": "review-flow",
            "name": "Review flow",
            "trigger": {
                "id": "start",
                "type": "trigger",
                "name": "Start",
                "config": {"mode": "manual"},
            },
            "nodes": [
                {
                    "id": "agent",
                    "type": "agent",
                    "name": "Analyze",
                    "config": {"role": "Analyze", "output_mode": "structured"},
                },
                {
                    "id": "out",
                    "type": "output",
                    "name": "Return",
                    "config": {"mode": "return"},
                },
            ],
            "edges": [
                {"from": "start", "to": "agent"},
                {"from": "agent", "to": "out"},
            ],
            "variables": [],
            "policies": [],
            "tests": [],
        }
    )
    reviewer = BedrockArchitectureReviewer(model_id="test")
    result = reviewer.review(
        goal="Analyze this request.",
        context=ContextGraph(
            requirements=[
                Requirement(
                    id="req_1",
                    statement="The system must analyze the request.",
                    priority="high",
                )
            ]
        ),
        workflow=workflow,
    )
    assert result.status == "passed"
