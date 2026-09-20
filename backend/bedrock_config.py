from __future__ import annotations

import os


LEGACY_NOVA_LITE = "amazon.nova-lite-v1:0"
APAC_NOVA_LITE = "apac.amazon.nova-lite-v1:0"


def resolve_bedrock_model(model_id: str | None = None) -> str:
    """Resolve a Bedrock model identifier suitable for the deployed AWS region.

    Legacy Nova Lite IDs are normalized to the APAC inference profile in
    ap-south-1. Explicit non-legacy model IDs are preserved.
    """
    resolved = (model_id or os.getenv("SPECL00M_BEDROCK_MODEL_ID") or LEGACY_NOVA_LITE).strip()
    region = os.getenv("AWS_REGION") or os.getenv("AWS_DEFAULT_REGION") or ""
    if resolved == LEGACY_NOVA_LITE and region == "ap-south-1":
        return APAC_NOVA_LITE
    return resolved
