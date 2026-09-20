from __future__ import annotations

from backend.compiler.assumptions import AutonomousAssumptionResolver
from backend.context.gaps import Gap, detect_gaps
from backend.context.models import ContextGraph


def test_safe_ambiguity_is_auto_resolved():
    goal = "Find relevant research and summarize it."
    context = ContextGraph()
    gaps = detect_gaps(goal, context)
    assert any(gap.id == "ambiguous-goal" for gap in gaps)

    enriched, decisions = AutonomousAssumptionResolver().resolve(
        goal,
        context,
        gaps,
    )

    assert decisions
    assert decisions[0].gap_id == "ambiguous-goal"
    assert enriched.assumptions[0]["safe"] is True

    remaining = detect_gaps(goal, enriched)
    assert not any(gap.id == "ambiguous-goal" for gap in remaining)


def test_safety_gaps_are_not_auto_resolved():
    goal = "Send a message to a customer."
    context = ContextGraph()
    gaps = detect_gaps(goal, context)

    enriched, decisions = AutonomousAssumptionResolver().resolve(
        goal,
        context,
        gaps,
    )

    assert any(gap.category == "safety" for gap in gaps)
    assert decisions == []
    assert enriched.assumptions == []
