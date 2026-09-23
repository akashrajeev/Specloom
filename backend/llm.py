"""Quota-resilient model access for every Specloom compiler step.

Each step asks for an agent with ``resilient_agent(model_id, system_prompt=...)``
and calls it exactly like a Strands ``Agent``. On a quota or throttling error the
call moves to the next provider in the chain instead of retrying the same
exhausted model for minutes:

1. the requested Bedrock model in the home region (APAC profile in ap-south-1)
2. the cheaper Nova models in the home region (each has its own daily quota)
3. the same Nova models through US cross-region profiles (separate quotas)
4. an optional OpenAI-compatible provider (Gemini, Groq, OpenRouter) when a key is configured

Providers that throttle are skipped for a cool-down period so later steps in the
same build do not burn time on them.
"""
from __future__ import annotations

import re

import logging
import os
import time
from dataclasses import dataclass
from typing import Any, Callable

from backend.bedrock_config import (
    APAC_NOVA_LITE,
    APAC_NOVA_MICRO,
    APAC_NOVA_PRO,
    BedrockQuotaExhausted,
    is_bedrock_quota_error,
    mark_bedrock_quota_exhausted,
    resolve_bedrock_model,
)

logger = logging.getLogger(__name__)

_COOLDOWN_UNTIL: dict[str, float] = {}
_LAST_ERROR: dict[str, str] = {}


@dataclass(frozen=True)
class Provider:
    key: str
    kind: str  # "bedrock" or "openai"
    model_id: str
    region: str | None = None
    base_url: str | None = None
    key_env: str = "SPECL00M_FALLBACK_LLM_API_KEY"


def _cooldown_seconds() -> float:
    return float(os.getenv("SPECL00M_PROVIDER_COOLDOWN_SECONDS", "900"))


def _cooling(provider: Provider) -> bool:
    return _COOLDOWN_UNTIL.get(provider.key, 0.0) > time.monotonic()


def _cool(provider: Provider) -> None:
    _COOLDOWN_UNTIL[provider.key] = time.monotonic() + _cooldown_seconds()


def reset_provider_cooldowns() -> None:
    _COOLDOWN_UNTIL.clear()
    _LAST_ERROR.clear()


def _short(exc: BaseException) -> str:
    text = " ".join(f"{type(exc).__name__}: {exc}".split())
    lowered = text.lower()
    # Compact the common cases so every provider fits in the UI notice.
    if "too many tokens per day" in lowered:
        return "daily token quota exhausted"
    if "accessdenied" in lowered or "don't have access" in lowered or "not authorized" in lowered:
        return "model access not enabled"
    if "requested" in lowered and "limit" in lowered:
        start = lowered.find("limit")
        return text[max(0, start - 60):start + 120]
    if "request too large" in lowered or "413" in lowered:
        return "request larger than the free-tier token limit"
    if "invalid structured output" in lowered:
        return "design did not match the schema"
    if "throttl" in lowered or "too many requests" in lowered or "429" in lowered:
        return "throttled"
    if "api key" in lowered or "credential" in lowered:
        return "missing or invalid credentials"
    return text[:160]


def _csv(name: str, default: str) -> list[str]:
    return [item.strip() for item in os.getenv(name, default).split(",") if item.strip()]


def provider_chain(model_id: str = "") -> list[Provider]:
    home_region = os.getenv("AWS_REGION") or os.getenv("AWS_DEFAULT_REGION") or ""
    primary = resolve_bedrock_model(model_id)
    home_models = [primary]
    if home_region == "ap-south-1":
        home_models += [APAC_NOVA_PRO, APAC_NOVA_LITE, APAC_NOVA_MICRO]
    chain: list[Provider] = []
    seen: set[str] = set()

    def add(provider: Provider) -> None:
        if provider.key not in seen:
            seen.add(provider.key)
            chain.append(provider)

    for model in home_models:
        add(Provider(f"bedrock:{home_region}:{model}", "bedrock", model, home_region or None))

    if os.getenv("SPECL00M_BEDROCK_CROSS_REGION", "on").lower() not in {"off", "false", "0"}:
        cross_models = _csv(
            "SPECL00M_BEDROCK_CROSS_REGION_MODELS",
            "us.amazon.nova-pro-v1:0,us.amazon.nova-lite-v1:0,us.amazon.nova-micro-v1:0",
        )
        for region in _csv("SPECL00M_BEDROCK_FALLBACK_REGIONS", "us-east-1,us-west-2"):
            if region == home_region:
                continue
            for model in cross_models:
                add(Provider(f"bedrock:{region}:{model}", "bedrock", model, region))

    # Route keys by their format, so a key saved under the "wrong" secret name still works.
    keys = [os.getenv(name, "").strip() for name in ("SPECL00M_GROQ_API_KEY", "SPECL00M_FALLBACK_LLM_API_KEY")]
    groq_key = next((k for k in keys if k.startswith("gsk_")), "")
    gemini_key = next((k for k in keys if k and not k.startswith("gsk_")), "")
    if groq_key:
        os.environ["SPECL00M__GROQ_KEY"] = groq_key
    if gemini_key:
        os.environ["SPECL00M__GEMINI_KEY"] = gemini_key

    if groq_key:
        groq_url = os.getenv("SPECL00M_GROQ_BASE_URL", "https://api.groq.com/openai/v1")
        for model in _csv(
            "SPECL00M_GROQ_MODELS",
            "openai/gpt-oss-120b,openai/gpt-oss-20b",
        ):
            add(Provider(f"groq:{model}", "openai", model, None, groq_url, "SPECL00M__GROQ_KEY"))

    if gemini_key:
        # Free-tier quotas are per model, so walk several models before giving up.
        for model in _csv("SPECL00M_FALLBACK_LLM_MODEL", "gemini-2.5-flash,gemini-3-flash-preview,gemini-2.5-flash-lite"):
            add(Provider(f"openai:{model}", "openai", model, None, None, "SPECL00M__GEMINI_KEY"))
    return chain


def _build_model(provider: Provider) -> Any:
    if provider.kind == "openai":
        from strands.models.openai import OpenAIModel

        return OpenAIModel(
            client_args={
                "api_key": os.environ[provider.key_env].strip(),
                "base_url": provider.base_url or os.getenv(
                    "SPECL00M_FALLBACK_LLM_BASE_URL",
                    "https://generativelanguage.googleapis.com/v1beta/openai/",
                ),
            },
            model_id=provider.model_id,
            params=_openai_limits(provider),
        )
    from strands.models import BedrockModel

    kwargs: dict[str, Any] = {"model_id": provider.model_id}
    if provider.region:
        kwargs["region_name"] = provider.region
    try:
        from botocore.config import Config

        kwargs["boto_client_config"] = Config(
            retries={"max_attempts": 2, "mode": "standard"},
            read_timeout=120,
        )
    except ImportError:  # local test environments without boto
        pass
    return BedrockModel(**kwargs)


def _is_switchable_error(exc: BaseException) -> bool:
    if is_bedrock_quota_error(exc):
        return True
    text = f"{type(exc).__name__} {exc}".lower()
    return any(
        marker in text
        for marker in (
            "modelthrottled",
            "accessdenied",
            "don't have access to the model",
            "model access",
            "resourcenotfound",
            "validationexception: the provided model identifier",
            "rate limit",
            "429",
            "resource_exhausted",
            "quota",
            "413",
            "request too large",
            "tokens per minute",
            "model_decommissioned",
            "model_not_found",
            "does not exist",
            "json_validate_failed",
            "invalid structured output",
            "invalid api key",
            "valid api key",
            "api key not valid",
            "permission_denied",
            "invalid_api_key",
            "401",
        )
    )


def _openai_limits(provider: Provider) -> dict[str, Any]:
    """Keep each request inside small free-tier budgets (Groq counts max tokens in its per-minute limit)."""
    limits: dict[str, Any] = {"max_tokens": int(os.getenv("SPECL00M_OPENAI_MAX_TOKENS", "3000"))}
    if "gpt-oss" in provider.model_id:
        # Reasoning tokens count as output; low effort keeps the budget for the answer.
        limits["reasoning_effort"] = os.getenv("SPECL00M_OPENAI_REASONING_EFFORT", "low")
    return limits


def _openai_structured(provider: Provider, system_prompt: str | None, prompt: Any, output_model: Any) -> Any:
    """Structured output for OpenAI-compatible providers (e.g. Gemini) via JSON mode.

    Gemini's OpenAI-compatible endpoint does not reliably honour Strands' forced
    structured-output tool call, so ask for a JSON object that matches the schema
    and validate it with Pydantic, with one repair round on validation errors.
    """
    import json
    from types import SimpleNamespace

    from openai import OpenAI

    client = OpenAI(
        api_key=os.environ[provider.key_env].strip(),
        base_url=provider.base_url
        or os.getenv("SPECL00M_FALLBACK_LLM_BASE_URL", "https://generativelanguage.googleapis.com/v1beta/openai/"),
        max_retries=0,
    )
    schema = json.dumps(output_model.model_json_schema(), separators=(",", ":"))
    system = (system_prompt or "") + (
        "\n\nRespond with a single JSON object only, no prose or code fences. "
        "It must validate against this JSON Schema:\n" + schema
    )
    messages: list[dict[str, str]] = [
        {"role": "system", "content": system.strip()},
        {"role": "user", "content": prompt if isinstance(prompt, str) else json.dumps(prompt, default=str)},
    ]
    last_exc: Exception | None = None
    for _ in range(2):
        response = client.chat.completions.create(
            model=provider.model_id,
            messages=messages,
            response_format={"type": "json_object"},
            **_openai_limits(provider),
        )
        text = (response.choices[0].message.content or "").strip()
        if text.startswith("```"):
            text = text.strip("`")
            text = text[text.find("{"):]
        try:
            value = output_model.model_validate_json(text)
            return SimpleNamespace(structured_output=value, message=text)
        except Exception as exc:  # noqa: BLE001 - pydantic validation detail goes back to the model
            last_exc = exc
            messages += [
                {"role": "assistant", "content": text},
                {"role": "user", "content": f"That JSON failed validation: {str(exc)[:1500]}. Return the corrected JSON object only."},
            ]
    raise ValueError(f"fallback provider returned invalid structured output: {last_exc}")


class ResilientAgent:
    """Drop-in for ``strands.Agent`` that walks the provider chain on quota errors."""

    def __init__(
        self,
        model_id: str = "",
        *,
        system_prompt: str | None = None,
        agent_factory: Callable[..., Any] | None = None,
        **agent_kwargs: Any,
    ) -> None:
        self._chain = provider_chain(model_id)
        self._system_prompt = system_prompt
        self._agent_kwargs = agent_kwargs
        self._factory = agent_factory
        self._agents: dict[str, Any] = {}
        self.last_provider: Provider | None = None

    def _agent_for(self, provider: Provider) -> Any:
        if provider.key not in self._agents:
            factory = self._factory
            if factory is None:
                from strands import Agent

                factory = Agent
            kwargs: dict[str, Any] = {
                "model": _build_model(provider),
                "system_prompt": self._system_prompt,
                **self._agent_kwargs,
            }
            try:
                # Fail fast on throttling; the provider chain is the retry strategy.
                self._agents[provider.key] = factory(retry_strategy=None, callback_handler=None, **kwargs)
            except TypeError:
                # Older Strands releases or test doubles without these options.
                self._agents[provider.key] = factory(**kwargs)
        return self._agents[provider.key]

    def __call__(self, prompt: Any, **kwargs: Any) -> Any:
        last_error: BaseException | None = None
        for provider in self._chain:
            if _cooling(provider):
                continue
            try:
                if provider.kind == "openai" and kwargs.get("structured_output_model") is not None:
                    result = _openai_structured(provider, self._system_prompt, prompt, kwargs["structured_output_model"])
                    self.last_provider = provider
                    return result
                agent = self._agent_for(provider)
                result = agent(prompt, **kwargs)
                self.last_provider = provider
                return result
            except Exception as exc:  # noqa: BLE001 - provider errors vary by SDK
                if not _is_switchable_error(exc):
                    raise
                retried = self._wait_out_minute_limit(provider, prompt, kwargs, exc)
                if retried is not _NO_RESULT:
                    return retried
                logger.warning("model provider %s unavailable: %s", provider.key, exc)
                _cool(provider)
                _LAST_ERROR[provider.key] = _short(exc)
                last_error = exc
        mark_bedrock_quota_exhausted()
        summary = "; ".join(
            f"{provider.key} -> {_LAST_ERROR.get(provider.key, 'cooling down')}"
            for provider in self._chain
        )
        # Keep "ThrottlingException" in the text so callers treat this as a quota fallback.
        raise RuntimeError(f"ThrottlingException: all model providers unavailable: {summary}") from last_error


    def _wait_out_minute_limit(self, provider: Provider, prompt: Any, kwargs: dict, exc: BaseException) -> Any:
        """Free tiers (e.g. Groq's 8K tokens/minute) reject bursts but reset within a minute.

        When the provider says exactly how long to wait for a per-minute limit, wait and
        retry the same provider instead of burning the rest of the chain. Daily limits are
        not retried.
        """
        if provider.kind != "openai":
            return _NO_RESULT
        budget = float(os.getenv("SPECL00M_MINUTE_LIMIT_WAIT_SECONDS", "75"))
        error = exc
        for _ in range(3):
            wait = _minute_limit_wait(error)
            if wait is None or wait > budget:
                return _NO_RESULT
            budget -= wait
            logger.warning("provider %s per-minute limit; retrying in %.1fs", provider.key, wait)
            time.sleep(wait)
            try:
                if kwargs.get("structured_output_model") is not None:
                    result = _openai_structured(provider, self._system_prompt, prompt, kwargs["structured_output_model"])
                else:
                    result = self._agent_for(provider)(prompt, **kwargs)
                self.last_provider = provider
                return result
            except Exception as retry_exc:  # noqa: BLE001
                if not _is_switchable_error(retry_exc):
                    raise
                error = retry_exc
        return _NO_RESULT


_NO_RESULT = object()


def _minute_limit_wait(exc: BaseException) -> float | None:
    text = str(exc).lower()
    if "per day" in text or "(tpd)" in text or "(rpd)" in text:
        return None
    if "per minute" not in text and "(tpm)" not in text and "(rpm)" not in text:
        return None
    if "reduce your message size" in text:
        return None  # a single request above the limit never fits; waiting does not help
    match = re.search(r"try again in (?:(\d+)m)?([\d.]+)(ms|s)", text)
    if not match:
        return 20.0
    minutes = float(match.group(1) or 0)
    value = float(match.group(2))
    seconds = value / 1000 if match.group(3) == "ms" else value
    return minutes * 60 + seconds + 0.5


def resilient_agent(model_id: str = "", **kwargs: Any) -> ResilientAgent:
    return ResilientAgent(model_id, **kwargs)


def compact_context_json(context: Any, max_quote_chars: int = 160) -> str:
    """Context for prompts without indentation, empty fields, or long provenance quotes."""
    data = context.model_dump(mode="json", exclude_none=True, exclude_defaults=True)
    for key in ("requirements", "constraints", "examples"):
        for item in data.get(key, []) or []:
            for provenance in item.get("provenance", []) or []:
                quote = provenance.get("quote")
                if isinstance(quote, str) and len(quote) > max_quote_chars:
                    provenance["quote"] = quote[:max_quote_chars] + "…"
    for source in data.get("sources", []) or []:
        source.pop("content_hash", None)
    import json

    return json.dumps(data, separators=(",", ":"), ensure_ascii=False)
