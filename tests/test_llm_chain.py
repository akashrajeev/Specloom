import pytest

from backend import llm


@pytest.fixture(autouse=True)
def _reset(monkeypatch):
    llm.reset_provider_cooldowns()
    monkeypatch.setenv("AWS_REGION", "ap-south-1")
    for name in ("SPECL00M_FALLBACK_LLM_API_KEY", "SPECL00M_GROQ_API_KEY",
                 "SPECL00M_CLOUDFLARE_ACCOUNT_ID", "SPECL00M_CLOUDFLARE_API_TOKEN", "SPECL00M_CLOUDFLARE_MODELS"):
        monkeypatch.delenv(name, raising=False)
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
    assert keys[-3:] == ["openai:gemini-2.5-flash", "openai:gemini-3-flash-preview", "openai:gemini-2.5-flash-lite"]
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


def test_build_reruns_deterministically_when_all_providers_are_out(monkeypatch):
    import os

    from fastapi import HTTPException

    from backend.api import build as build_api

    seen = []

    def fake_once(project_id, request):
        seen.append(os.environ.get("SPECL00M_ARCHITECT_MODE"))
        if len(seen) == 1:
            raise HTTPException(status_code=422, detail="ThrottlingException: all model providers unavailable")
        return {"ready": True, "degraded_architecture": None}

    monkeypatch.setattr(build_api, "_build_once", fake_once)
    monkeypatch.setattr(build_api.architect, "mode", "bedrock")
    monkeypatch.setenv("SPECL00M_ARCHITECT_MODE", "bedrock")
    result = build_api.build("p", build_api.BuildRequestBody(goal="Email me a daily price summary."))
    assert seen == ["bedrock", "showcase"]
    assert "out of quota" in result["degraded_architecture"]
    assert os.environ["SPECL00M_ARCHITECT_MODE"] == "bedrock"
    assert build_api.architect.mode == "bedrock"


def test_cloudflare_comes_before_groq_when_configured(monkeypatch):
    monkeypatch.setenv("SPECL00M_GROQ_API_KEY", "gsk_test")
    monkeypatch.setenv("SPECL00M_CLOUDFLARE_ACCOUNT_ID", "acct123")
    monkeypatch.setenv("SPECL00M_CLOUDFLARE_API_TOKEN", "cf-token")
    chain = llm.provider_chain("apac.amazon.nova-pro-v1:0")
    keys = [p.key for p in chain]
    cf = keys.index("cloudflare:@cf/openai/gpt-oss-120b")
    assert cf < keys.index("groq:openai/gpt-oss-120b")
    provider = chain[cf]
    assert provider.base_url == "https://api.cloudflare.com/client/v4/accounts/acct123/ai/v1"
    assert "reasoning_effort" not in llm._openai_limits(provider)
    assert "reasoning_effort" in llm._openai_limits(chain[keys.index("groq:openai/gpt-oss-120b")])


def test_cloudflare_skipped_without_both_values(monkeypatch):
    monkeypatch.setenv("SPECL00M_CLOUDFLARE_API_TOKEN", "cf-token")
    assert not any(p.key.startswith("cloudflare:") for p in llm.provider_chain(""))
