from __future__ import annotations

import ipaddress
import json
import os
import socket
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

import httpx


class APIConfigurationError(ValueError):
    pass


_READ_METHODS = {"GET", "HEAD", "OPTIONS"}
_WRITE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}


@dataclass(frozen=True)
class ConfiguredAPI:
    name: str
    base_url: str
    description: str
    capabilities: tuple[str, ...]
    read_methods: tuple[str, ...]
    write_methods: tuple[str, ...]
    auth_env: str | None = None
    auth_header: str = "Authorization"
    auth_prefix: str = "Bearer "
    timeout_seconds: float = 15.0

    @property
    def read_tool_id(self) -> str:
        return f"api:{self.name}:read"

    @property
    def write_tool_id(self) -> str:
        return f"api:{self.name}:write"

    @property
    def side_effecting(self) -> bool:
        return bool(self.write_methods)


def _public_url(value: str) -> str:
    parsed = urlparse(value)
    if parsed.scheme != "https" or not parsed.hostname:
        raise APIConfigurationError("configured API base_url must use https")
    try:
        addresses = {info[4][0] for info in socket.getaddrinfo(parsed.hostname, None)}
    except socket.gaierror as exc:
        raise APIConfigurationError(
            f"cannot resolve configured API host: {parsed.hostname}"
        ) from exc

    for address in addresses:
        ip = ipaddress.ip_address(address)
        if (
            ip.is_private
            or ip.is_loopback
            or ip.is_link_local
            or ip.is_multicast
            or ip.is_reserved
            or ip.is_unspecified
        ):
            raise APIConfigurationError(
                f"configured API host is not public: {parsed.hostname}"
            )
    return value.rstrip("/")


def _load() -> list[ConfiguredAPI]:
    raw = os.getenv("SPECL00M_API_ENDPOINTS", "").strip()
    if not raw:
        return []

    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise APIConfigurationError(
            "SPECL00M_API_ENDPOINTS must be valid JSON"
        ) from exc

    if not isinstance(value, dict):
        raise APIConfigurationError("SPECL00M_API_ENDPOINTS must be an object")

    result: list[ConfiguredAPI] = []
    for name, config in value.items():
        if not isinstance(config, dict):
            raise APIConfigurationError(f"API definition {name} must be an object")
        base_url = _public_url(str(config.get("base_url", "")).strip())
        read_methods = tuple(
            method.upper() for method in config.get("read_methods", ["GET"])
        )
        write_methods = tuple(
            method.upper() for method in config.get("write_methods", [])
        )
        if any(method not in _READ_METHODS for method in read_methods):
            raise APIConfigurationError(
                f"API {name} contains a non-read method in read_methods"
            )
        if any(method not in _WRITE_METHODS for method in write_methods):
            raise APIConfigurationError(
                f"API {name} contains an unsupported write method"
            )
        result.append(
            ConfiguredAPI(
                name=str(name),
                base_url=base_url,
                description=str(config.get("description") or f"Configured API: {name}"),
                capabilities=tuple(str(item) for item in config.get("capabilities", [])),
                read_methods=read_methods,
                write_methods=write_methods,
                auth_env=str(config["auth_env"]) if config.get("auth_env") else None,
                auth_header=str(config.get("auth_header") or "Authorization"),
                auth_prefix=str(config.get("auth_prefix") or "Bearer "),
                timeout_seconds=max(
                    1.0,
                    min(float(config.get("timeout_seconds", 15)), 60.0),
                ),
            )
        )
    return result


def configured_apis() -> list[ConfiguredAPI]:
    return _load()


def get_api(tool_id: str) -> tuple[ConfiguredAPI, str]:
    for api in configured_apis():
        if tool_id == api.read_tool_id and api.read_methods:
            return api, "read"
        if tool_id == api.write_tool_id and api.write_methods:
            return api, "write"
    raise KeyError(f"unknown configured API tool: {tool_id}")


def api_context_tools() -> list[dict[str, Any]]:
    tools: list[dict[str, Any]] = []
    for api in configured_apis():
        if api.read_methods:
            tools.append(
                {
                    "id": api.read_tool_id,
                    "name": f"{api.name} API (read)",
                    "description": api.description
                    + " Credentials stay in the deployment environment.",
                    "capabilities": [*api.capabilities, "api", "read"],
                    "permissions": ["READ"],
                    "side_effecting": False,
                    "requires_human_approval": False,
                    "execution_modes": ["live"],
                }
            )
        if api.write_methods:
            tools.append(
                {
                    "id": api.write_tool_id,
                    "name": f"{api.name} API (write)",
                    "description": api.description
                    + " Credentials stay in the deployment environment.",
                    "capabilities": [*api.capabilities, "api", "write"],
                    "permissions": ["READ", "WRITE"],
                    "side_effecting": True,
                    "requires_human_approval": True,
                    "execution_modes": ["mock", "sandbox", "live"],
                }
            )
    return tools


def invoke_configured_api(
    tool_id: str,
    payload: dict[str, Any],
    *,
    approved: bool = False,
) -> dict[str, Any]:
    api, access = get_api(tool_id)
    method = str(payload.get("method") or "").upper()
    path = str(payload.get("path") or "").strip()

    allowed_methods = api.read_methods if access == "read" else api.write_methods
    if method not in allowed_methods:
        raise APIConfigurationError(
            f"{tool_id} does not allow method {method or '<missing>'}"
        )

    if access == "write" and not approved:
        raise PermissionError(f"{tool_id} requires explicit human approval")

    if path.startswith("http://") or path.startswith("https://"):
        raise APIConfigurationError("configured API tools accept paths, not absolute URLs")

    url = f"{api.base_url}/{path.lstrip('/')}" if path else api.base_url
    parsed = urlparse(url)
    if parsed.hostname != urlparse(api.base_url).hostname:
        raise APIConfigurationError("configured API request changed the destination host")

    params = payload.get("query") or {}
    if not isinstance(params, dict):
        raise APIConfigurationError("query must be an object")

    request_body = payload.get("json")
    if request_body is not None and not isinstance(request_body, (dict, list, str, int, float, bool)):
        raise APIConfigurationError("json body must be JSON-compatible")

    headers: dict[str, str] = {
        "Accept": "application/json",
        "User-Agent": "Specloom/0.1",
    }
    if api.auth_env:
        token = os.getenv(api.auth_env, "")
        if not token:
            raise RuntimeError(
                f"configured API credential is missing from environment variable {api.auth_env}"
            )
        headers[api.auth_header] = f"{api.auth_prefix}{token}"

    with httpx.Client(
        follow_redirects=False,
        timeout=api.timeout_seconds,
        headers=headers,
    ) as client:
        response = client.request(
            method,
            url,
            params=params,
            json=request_body if method != "GET" else None,
        )

    if 300 <= response.status_code < 400:
        raise APIConfigurationError(
            "configured API redirects are blocked; use the canonical API base URL"
        )

    text = response.text[:50_000]
    try:
        data: Any = response.json()
    except ValueError:
        data = text

    if response.is_error:
        raise RuntimeError(
            f"configured API request failed ({response.status_code}): {text[:1000]}"
        )

    return {
        "tool": tool_id,
        "status": "ok",
        "method": method,
        "url": url,
        "status_code": response.status_code,
        "data": data,
    }
