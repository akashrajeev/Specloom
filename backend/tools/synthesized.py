from __future__ import annotations

import os
from typing import Any
from urllib.parse import urljoin, urlparse

import httpx


def invoke_synthesized_capability(
    capability: dict[str, Any],
    payload: dict[str, Any],
    *,
    approved: bool = False,
) -> dict[str, Any]:
    """Execute a generated provider-neutral HTTP adapter after provisioning."""

    if bool(capability.get("side_effecting")) and not approved:
        raise PermissionError(
            f"tool {capability.get('id', 'synthesized capability')} requires explicit approval"
        )

    env = [str(item) for item in capability.get("provisioning_env", [])]
    if len(env) < 2:
        raise RuntimeError("synthesized capability has no provisioning contract")

    base_url = os.getenv(env[0], "").strip()
    path = os.getenv(env[1], "").strip()
    method = os.getenv(env[2], "POST").strip().upper() if len(env) >= 3 else "POST"
    api_key = os.getenv(env[3], "").strip() if len(env) >= 4 else ""

    if not base_url or not path:
        raise RuntimeError(
            f"capability {capability.get('id')} requires {env[0]} and {env[1]}"
        )

    parsed = urlparse(base_url)
    if parsed.scheme != "https" or not parsed.hostname:
        raise RuntimeError("synthesized external capabilities require HTTPS")

    target = urljoin(base_url.rstrip("/") + "/", path.lstrip("/"))
    target_parsed = urlparse(target)
    if target_parsed.scheme != "https" or target_parsed.hostname != parsed.hostname:
        raise RuntimeError("synthesized capability path cannot change the configured host")

    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = "Bearer " + api_key

    timeout = httpx.Timeout(20.0, connect=5.0)
    with httpx.Client(timeout=timeout, follow_redirects=False) as client:
        if method in {"GET", "HEAD", "OPTIONS"}:
            response = client.request(
                method,
                target,
                params={
                    key: value
                    for key, value in payload.items()
                    if not str(key).startswith("_")
                },
                headers=headers,
            )
        else:
            response = client.request(method, target, json=payload, headers=headers)

    if response.status_code >= 300:
        raise RuntimeError(
            f"synthesized capability returned HTTP {response.status_code}"
        )

    content_type = response.headers.get("content-type", "").lower()
    if "application/json" in content_type:
        value = response.json()
        return value if isinstance(value, dict) else {"data": value}

    body = response.text[:2_000_000]
    return {"status": "ok", "body": body, "content_type": content_type}
