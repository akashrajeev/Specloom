from backend import bedrock_config
from backend.compiler.research import BedrockResearchPlanner, ResearchPlanner
from backend.context.models import ContextGraph


class _Throttled:
    calls = 0

    def __call__(self, *_args, **_kwargs):
        type(self).calls += 1
        raise RuntimeError(
            "An error occurred (ThrottlingException) when calling the ConverseStream "
            "operation: Too many tokens per day, please wait before trying again."
        )


def _planner() -> BedrockResearchPlanner:
    planner = BedrockResearchPlanner.__new__(BedrockResearchPlanner)
    planner._agent = _Throttled()
    return planner


def test_research_planner_falls_back_on_daily_quota():
    bedrock_config.reset_bedrock_quota_state()
    _Throttled.calls = 0
    goal = "Check competitor prices every morning and email me a summary."
    graph = ContextGraph()
    plan = _planner().plan(goal, graph, [])
    assert plan == ResearchPlanner().plan(goal, graph, [])
    assert bedrock_config.bedrock_quota_recently_exhausted()


def test_tripped_breaker_skips_model_calls():
    bedrock_config.reset_bedrock_quota_state()
    bedrock_config.mark_bedrock_quota_exhausted()
    _Throttled.calls = 0
    _planner().plan("Summarize new support tickets daily.", ContextGraph(), [])
    assert _Throttled.calls == 0
    bedrock_config.reset_bedrock_quota_state()


def test_quota_exhausted_marker_matches_quota_detector():
    assert bedrock_config.is_bedrock_quota_error(bedrock_config.BedrockQuotaExhausted())
