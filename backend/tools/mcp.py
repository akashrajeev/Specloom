from __future__ import annotations

import json
import os
from typing import Any


class MCPConfigurationError(ValueError):
    pass


def configured_mcp_servers() -> dict[str, dict[str, Any]]:
    raw = os.getenv("SPECL00M_MCP_SERVERS", "").strip()
    if not raw:
        return {}

    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise MCPConfigurationError("SPECL00M_MCP_SERVERS must contain valid JSON") from exc

    if "mcpServers" in value:
        value = value["mcpServers"]
    if not isinstance(value, dict):
        raise MCPConfigurationError("SPECL00M_MCP_SERVERS must be an object of server definitions")

    return {
        str(name): config
        for name, config in value.items()
        if isinstance(config, dict) and not config.get("disabled", False)
    }


def readonly_mcp_server_names() -> set[str]:
    raw = os.getenv("SPECL00M_MCP_READONLY_SERVERS", "").strip()
    if not raw:
        return set()
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise MCPConfigurationError(
            "SPECL00M_MCP_READONLY_SERVERS must be a JSON array of server names"
        ) from exc
    if not isinstance(value, list):
        raise MCPConfigurationError("SPECL00M_MCP_READONLY_SERVERS must be a JSON array")
    return {str(name) for name in value}


def load_readonly_clients(server_names: list[str]) -> list[Any]:
    configured = configured_mcp_servers()
    readonly = readonly_mcp_server_names()

    unknown = set(server_names) - set(configured)
    if unknown:
        raise MCPConfigurationError(
            "unknown MCP server(s): " + ", ".join(sorted(unknown))
        )

    not_readonly = set(server_names) - readonly
    if not_readonly:
        raise MCPConfigurationError(
            "MCP server(s) are not explicitly allowlisted as read-only: "
            + ", ".join(sorted(not_readonly))
        )

    selected = {"mcpServers": {name: configured[name] for name in server_names}}
    try:
        from strands.tools.mcp import MCPClient
    except ImportError as exc:
        raise RuntimeError("Install mcp and strands-agents for MCP runtime support") from exc

    return MCPClient.load_servers(
        selected,
        continue_on_error=False,
        prefix_with_server_name=True,
    )


def prompt_mcp_catalog() -> str:
    configured = configured_mcp_servers()
    if not configured:
        return "- none configured"

    readonly = readonly_mcp_server_names()
    rows: list[str] = []
    for name, config in configured.items():
        access = "READ-ONLY" if name in readonly else "NOT AVAILABLE TO AGENTS"
        transport = config.get("transport") or ("stdio" if config.get("command") else "http")
        rows.append(f"- {name}: transport={transport}; access={access}")
    return "\n".join(rows)
