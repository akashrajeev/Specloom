from backend.context.gaps import detect_gaps
from backend.context.models import ContextGraph


def test_undefined_relevance_is_blocking_without_context_rules():
    graph = ContextGraph(sources=[], requirements=[], constraints=[], tools=[], examples=[])
    gaps = detect_gaps(
        "Find relevant research and report it.",
        graph,
    )
    assert any(gap.severity == "blocking" for gap in gaps)
