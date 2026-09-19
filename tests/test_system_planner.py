from __future__ import annotations

from backend.compiler.planner import (
    ConfiguredSystemPlanner,
    DeterministicSystemPlanner,
)
from backend.context.models import ContextGraph


def test_deterministic_planner_makes_goal_explicit_and_adds_justified_requirements():
    context = ContextGraph()
    enriched = ConfiguredSystemPlanner(architect_mode="showcase").enrich(
        "Build a dashboard with login and persistent records.",
        context,
    )

    assert enriched.requirements
    statements = [item.statement for item in enriched.requirements]
    assert any("Build a dashboard" in item for item in statements)
    assert any("authenticated operations" in item for item in statements)
    assert any("persist required state" in item for item in statements)
    assert any("usable web interface" in item for item in statements)
    assert any(source.name == "System Planner" for source in enriched.sources)


def test_planner_deduplicates_equivalent_requirements():
    planner = DeterministicSystemPlanner()
    context = ContextGraph()

    first = planner.plan("Build a web app.", context)
    second = planner.plan("Build a web app.", context)

    assert [item.statement for item in first.requirements] == [
        item.statement for item in second.requirements
    ]
