from __future__ import annotations

from backend.compiler.research import ResearchPlanner
from backend.context.gaps import Gap
from backend.context.models import ContextGraph


def test_research_planner_creates_integration_and_gap_tasks():
    plan = ResearchPlanner().plan(
        "Build a calendar integration that sends email alerts.",
        ContextGraph(),
        gaps=[
            Gap(
                id="missing-capability-calendar",
                severity="blocking",
                category="capability",
                question="Which calendar provider is trusted?",
            )
        ],
    )

    ids = {item.id for item in plan.tasks}
    assert "research-integration-contracts" in ids
    assert "research-gap-missing-capability-calendar" in ids
    assert "missing-capability-calendar" in plan.unresolved_gaps


def test_research_planner_is_explicit_when_no_special_domain_is_detected():
    plan = ResearchPlanner().plan(
        "Build a small local utility.",
        ContextGraph(),
    )
    assert plan.tasks
    assert plan.tasks[0].id == "research-domain-discovery"
