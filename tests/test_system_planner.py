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


def test_planner_outcome_does_not_create_duplicate_ambiguity_gap():
    from backend.context.gaps import detect_gaps

    enriched = ConfiguredSystemPlanner(architect_mode="showcase").enrich(
        "Find relevant research and report it.",
        ContextGraph(),
    )
    gaps = detect_gaps(
        "Find relevant research and report it.",
        enriched,
    )

    assert not any(
        gap.category == "ambiguity"
        and gap.related_requirement
        and gap.related_requirement.startswith("req_plan_")
        for gap in gaps
    )


def test_planner_preserves_inferred_entity_fields():
    from backend.compiler.planner import PlannerEntity

    entity = PlannerEntity(
        name="Customer",
        type="domain",
        fields=[
            {"name": "email", "type": "string", "required": True},
            {"name": "name", "type": "string"},
        ],
    )
    assert entity.fields[0]["name"] == "email"
