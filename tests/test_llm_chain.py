import pytest

from backend import llm


@pytest.fixture(autouse=True)
def _reset(monkeypatch):
    llm.reset_provider_cooldowns()
    monkeypatch.setenv("AWS_REGION", "ap-south-1")
    monkeypatch.delenv("SPECL00M_FALLBACK_LLM_API_KEY", raising=False)
    monkeypatch.setattr(llm, "_build_model", lambda provider: provider)
    yield
    llm.reset_provider_cooldowns()


def test_chain_prefers_home_region_then_cross_region_then_openai(monkeypatch):
    monkeypatch.setenv("SPECL00M_FALLBACK_LLM_API_KEY", "test-key")
    keys = [provider.key for provider in llm.provider_chain("apac.amazon.nova-pro-v1:0")]
    assert keys[0] == "bedrock:ap-south-1:apac.amazon.nova-pro-v1:0"
    assert keys[1:3] == [
        "bedrock:ap-south-1:apac.amazon.nova-lite-v1:0",
        "bedrock:ap-south-1:apac.amazon.nova-micro-v1:0",
    ]
    assert "bedrock:us-east-1:us.amazon.nova-pro-v1:0" in keys
    assert keys[-1] == "openai:gemini-2.5-flash"
    assert len(keys) == len(set(keys))


def test_agent_switches_provider_on_quota_and_skips_cooled_ones():
    built = []

    class FakeAgent:
        def __init__(self, *, model, **_kwargs):
            self.provider = model
            built.append(model.key)

        def __call__(self, prompt, **_kwargs):
            if self.provider.region == "ap-south-1":
                raise RuntimeError("ThrottlingException: Too many tokens per day")
            return f"answer from {self.provider.key}"

    agent = llm.ResilientAgent("apac.amazon.nova-pro-v1:0", system_prompt="x", agent_factory=FakeAgent)
    assert agent("hi") == "answer from bedrock:us-east-1:us.amazon.nova-pro-v1:0"
    built.clear()
    second = llm.ResilientAgent("", system_prompt="y", agent_factory=FakeAgent)
    second("hi again")
    assert built == ["bedrock:us-east-1:us.amazon.nova-pro-v1:0"]


def test_non_quota_errors_are_not_swallowed():
    class Broken:
        def __init__(self, **_kwargs):
            pass

        def __call__(self, *_args, **_kwargs):
            raise ValueError("schema mismatch")

    with pytest.raises(ValueError):
        llm.ResilientAgent("", agent_factory=Broken)("hi")


def test_compact_context_drops_whitespace_and_long_quotes():
    from backend.context.models import ContextGraph, Provenance, Requirement

    graph = ContextGraph(requirements=[Requirement(
        id="r1", statement="Email a summary",
        provenance=[Provenance(source_id="s1", quote="x" * 500)],
    )])
    text = llm.compact_context_json(graph)
    assert "\n" not in text and len(text) < 400
