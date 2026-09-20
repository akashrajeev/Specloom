from __future__ import annotations

import os


LEGACY_NOVA_LITE = "amazon.nova-lite-v1:0"
APAC_NOVA_LITE = "apac.amazon.nova-lite-v1:0"
NOVA_MICRO = "amazon.nova-micro-v1:0"


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
        requested = NOVA_MICRO if region == "ap-south-1" else LEGACY_NOVA_LITE

    # The legacy bare Nova Lite ID is invalid for some APAC on-demand paths.
    # Keep the explicit APAC profile when the caller intentionally selects Lite.
    if requested == LEGACY_NOVA_LITE and region == "ap-south-1":
        lite_profile = os.getenv("SPECL00M_NOVA_LITE_PROFILE", APAC_NOVA_LITE).strip()
        return lite_profile or APAC_NOVA_LITE

    return requested


def is_bedrock_quota_error(exc: BaseException) -> bool:
    text = str(exc).lower()
    return (
        "throttlingexception" in text
        or "too many tokens per day" in text
        or "rate exceeded" in text
        or "throughput" in text and "quota" in text
    )


def quota_fallback_model() -> str:
    return os.getenv("SPECL00M_BEDROCK_FALLBACK_MODEL_ID", NOVA_MICRO).strip() or NOVA_MICRO
