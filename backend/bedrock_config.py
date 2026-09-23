from __future__ import annotations

import os
import time

_QUOTA_TRIPPED_AT: float | None = None


LEGACY_NOVA_LITE = "amazon.nova-lite-v1:0"
APAC_NOVA_LITE = "apac.amazon.nova-lite-v1:0"
NOVA_MICRO = "amazon.nova-micro-v1:0"
APAC_NOVA_MICRO = "apac.amazon.nova-micro-v1:0"
NOVA_PRO = "amazon.nova-pro-v1:0"
APAC_NOVA_PRO = "apac.amazon.nova-pro-v1:0"


def resolve_bedrock_model(model_id: str | None = None) -> str:
    """Resolve the Bedrock model for the current deployment.

    In the hackathon/demo AWS deployment, prefer Nova Micro in ap-south-1
    because it has a separate per-model token quota from Nova Lite. Explicit
    non-empty model IDs remain respected, except legacy Nova Lite is normalized
    to the configured fallback model when requested through an old workflow.
    """
    requested = (model_id or os.getenv("SPECL00M_BEDROCK_MODEL_ID") or "").strip()
    region = os.getenv("AWS_REGION") or os.getenv("AWS_DEFAULT_REGION") or ""

    if not requested:
        requested = APAC_NOVA_PRO if region == "ap-south-1" else LEGACY_NOVA_LITE

    if region == "ap-south-1":
        if requested == LEGACY_NOVA_LITE:
            lite_profile = os.getenv("SPECL00M_NOVA_LITE_PROFILE", APAC_NOVA_LITE).strip()
            return lite_profile or APAC_NOVA_LITE
        if requested == NOVA_MICRO:
            micro_profile = os.getenv("SPECL00M_NOVA_MICRO_PROFILE", APAC_NOVA_MICRO).strip()
            return micro_profile or APAC_NOVA_MICRO
        if requested == NOVA_PRO:
            pro_profile = os.getenv("SPECL00M_NOVA_PRO_PROFILE", APAC_NOVA_PRO).strip()
            return pro_profile or APAC_NOVA_PRO

    return requested


def is_bedrock_quota_error(exc: BaseException) -> bool:
    text = str(exc).lower()
    return (
        "throttlingexception" in text
        or "too many tokens per day" in text
        or "rate exceeded" in text
        or "throughput" in text and "quota" in text
    )


def mark_bedrock_quota_exhausted() -> None:
    """Remember a quota rejection so later steps skip Bedrock instead of retrying for minutes."""
    global _QUOTA_TRIPPED_AT
    _QUOTA_TRIPPED_AT = time.monotonic()


def bedrock_quota_recently_exhausted() -> bool:
    if _QUOTA_TRIPPED_AT is None:
        return False
    cooldown = float(os.getenv("SPECL00M_BEDROCK_QUOTA_COOLDOWN_SECONDS", "900"))
    return time.monotonic() - _QUOTA_TRIPPED_AT < cooldown


def reset_bedrock_quota_state() -> None:
    global _QUOTA_TRIPPED_AT
    _QUOTA_TRIPPED_AT = None


class BedrockQuotaExhausted(RuntimeError):
    """Raised instead of calling Bedrock while a recent quota rejection is still cooling down."""

    def __str__(self) -> str:  # keeps is_bedrock_quota_error() matching
        return "ThrottlingException: Bedrock quota recently exhausted; skipping model call"


def quota_fallback_model() -> str:
    fallback = os.getenv("SPECL00M_BEDROCK_FALLBACK_MODEL_ID", APAC_NOVA_PRO).strip()
    if fallback == NOVA_MICRO and (os.getenv("AWS_REGION") or os.getenv("AWS_DEFAULT_REGION") or "") == "ap-south-1":
        return APAC_NOVA_PRO
    if fallback == NOVA_PRO and (os.getenv("AWS_REGION") or os.getenv("AWS_DEFAULT_REGION") or "") == "ap-south-1":
        return APAC_NOVA_PRO
    return fallback or APAC_NOVA_PRO
