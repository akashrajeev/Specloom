from __future__ import annotations

import ipaddress
import os
import socket
from typing import Any
from urllib.parse import urlparse

import httpx

from backend.capabilities.models import CapabilitySpec


class OpenAPIToolError(ValueError):
    pass


def invoke_openapi_capability(
    capability: CapabilitySpec | dict[str, Any],
    payload: dict[str, Any],
    *,
    approved: bool = False,
) -> dict[str, Any]:
    cap = capability if isinstance(capability, CapabilitySpec) else CapabilitySpec.model_validate(capability)
    if cap.side_effecting and not approved:
        raise PermissionError(f"capability {cap.id} requires explicit approval")
    if not cap.base_url or not cap.method or not cap.path:
        raise OpenAPIToolError(f"capability {cap.id} is missing executable binding")

    base_url = _validate_public_base(cap.base_url)
    path = _render_path(cap.path, payload)
    if path.startswith("http://") or path.startswith("https://"):
        raise OpenAPIToolError("OpenAPI capabilities accept relative paths only")
    url = base_url + "/" + path.lstrip("/")
    parsed = urlparse(url)
    if parsed.hostname != urlparse(base_url).hostname:
        raise OpenAPIToolError("capability request changed the configured API host")

    headers: dict[str, str] = {"Accept": "application/json"}
    if cap.auth_env:
        secret = os.getenv(cap.auth_env, "")
        if not secret:
            raise OpenAPIToolError(f"credential environment variable is not configured: {cap.auth_env}")
        headers[cap.auth_header] = f"{cap.auth_prefix}{secret}"

    query = dict(payload.get("query") or {})
    body = payload.get("body", payload.get("json"))
    consumed = {"query", "body", "json", * _path_names(cap.path)}
    for key, value in payload.items():
        if key not in consumed and not key.startswith("_"):
            query.setdefault(key, value)

    kwargs: dict[str, Any] = {"params": query, "headers": headers}
    if cap.method.upper() not in {"GET", "HEAD", "OPTIONS"}:
        if body is not None:
            kwargs["json"] = body
        elif query and cap.input_schema.get("properties", {}).get("body"):
            kwargs["json"] = query
            kwargs["params"] = {}

    with httpx.Client(timeout=30.0, follow_redirects=False) as client:
        response = client.request(cap.method.upper(), url, **kwargs)
    response.raise_for_status()

    content_type = response.headers.get("content-type", "")
    if "json" in content_type:
        value = response.json()
    else:
        value = response.text
    return {"status": "completed", "capability": cap.id, "status_code": response.status_code, "data": value}


def _path_names(path: str) -> set[str]:
    import re
    return set(re.findall(r"\{([^{}]+)\}", path))


def _render_path(path: str, payload: dict[str, Any]) -> str:
    import re
    names = _path_names(path)
    for name in names:
        if name not in payload:
            raise OpenAPIToolError(f"missing path parameter: {name}")
        value = str(payload[name])
        if "/" in value or "\\" in value:
            raise OpenAPIToolError(f"invalid path parameter: {name}")
        path = path.replace("{" + name + "}", value)
    return path


def _validate_public_base(value: str) -> str:
    parsed = urlparse(value)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
        raise OpenAPIToolError("OpenAPI base URL must be an HTTPS URL without credentials")
    try:
        addresses = {info[4][0] for info in socket.getaddrinfo(parsed.hostname, None)}
    except socket.gaierror as exc:
        raise OpenAPIToolError(f"cannot resolve API hostname: {parsed.hostname}") from exc
    for address in addresses:
        ip = ipaddress.ip_address(address)
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_multicast or ip.is_reserved or ip.is_unspecified:
            raise OpenAPIToolError("OpenAPI base URL resolves to a non-public address")
    return value.rstrip("/")
