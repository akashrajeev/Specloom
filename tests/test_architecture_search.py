from __future__ import annotations

from backend.agents.architect import BuildRequest
from backend.compiler.architecture_search import ArchitectureHypothesisSearcher
from backend.context.models import ContextGraph, Requirement
from backend.workflow.models import Node, Trigger, WorkflowIR


def _workflow(requirement_ref: str | None) -> WorkflowIR:
    agent_config = {}
    if requirement_ref is not None:
        agent_config["requirement_refs"] = [requirement_ref]
    return WorkflowIR(
        ir_version="0.1",
        id="candidate",
        name="Candidate",
        description="candidate",
        trigger=Trigger(
            id="trigger",
            type="trigger",
            name="Start",
            config={"mode": "manual"},
        ),
        nodes=[
            Node(
                id="agent",
                type="agent",
                name="Agent",
                config=agent_config,
            ),
            Node(
                id="output",
                type="output",
                name="Output",
                config={},
            ),
        ],
        edges=[
            {"from": "trigger", "to": "agent"},
            {"from": "agent", "to": "output"},
        ],
        variables=[],
        policies=[],
        tests=[],
    )


def test_architecture_search_filters_uncovered_candidate_and_selects_covered():
    class Architect:
        def __init__(self):
            self.calls = 0

        def build(self, request, context):
            self.calls += 1
            return _workflow(None if self.calls == 1 else "req-1")

    context = ContextGraph(
        requirements=[
            Requirement(
                id="req-1",
                statement="The system must return a processed result.",
                priority="high",
            )
        ]
    )

    result = ArchitectureHypothesisSearcher(
        Architect(),
        candidate_count=2,
    ).search(
        request=BuildRequest(
            goal="Create a service that processes input and returns the result.",
            project_id="architecture-search-test",
        ),
        context=context,
    )

    assert result.selected.index == 1
    assert result.selected.validation_errors == ()
    assert result.selected.evidence["coverage"] >= 1
    assert result.candidates[0].validation_errors
    assert "important requirement is not covered: req-1" in result.candidates[0].validation_errors


def test_architecture_search_never_accepts_only_invalid_hypotheses():
    class Architect:
        def build(self, request, context):
            return _workflow(None)

    context = ContextGraph(
        requirements=[
            Requirement(
                id="req-1",
                statement="The system must return a processed result.",
                priority="high",
            )
        ]
    )

    try:
        ArchitectureHypothesisSearcher(
            Architect(),
            candidate_count=2,
        ).search(
            request=BuildRequest(
                goal="Create a service.",
                project_id="architecture-search-test",
            ),
            context=context,
        )
    except ValueError as exc:
        assert "all architecture hypotheses were rejected" in str(exc)
    else:
        raise AssertionError("invalid architecture hypotheses were accepted")
