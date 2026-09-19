from backend.tools.adapters import live_url_fetch
from backend.tools.gateway import ToolGateway, ToolInvocation


def test_gateway_blocks_write_without_approval():
    gateway = ToolGateway()
    try:
        gateway.invoke(
            ToolInvocation(
                tool_id="github.create_issue",
                mode="live",
                input={"title": "test"},
            ),
            approved=False,
        )
        assert False, "expected PermissionError"
    except PermissionError:
        pass


def test_gateway_simulates_read_tools():
    gateway = ToolGateway()
    result = gateway.invoke(
        ToolInvocation(
            tool_id="web_search",
            mode="mock",
            input={"query": "AI agents"},
        ),
        approved=False,
    )
    assert result["status"] == "simulated"


def test_url_scheme_guard():
    try:
        live_url_fetch({"url": "file:///etc/passwd"})
        assert False, "expected ValueError"
    except ValueError:
        pass



def test_mcp_readonly_allowlist_is_explicit(monkeypatch):
    from backend.tools.mcp import load_readonly_clients
    import pytest

    monkeypatch.setenv(
        "SPECL00M_MCP_SERVERS",
        '{"mcpServers":{"docs":{"url":"https://example.com/mcp"}}}',
    )
    monkeypatch.setenv("SPECL00M_MCP_READONLY_SERVERS", "[]")
    with pytest.raises(ValueError, match="not explicitly allowlisted"):
        load_readonly_clients(["docs"])


def test_configured_api_is_split_into_read_and_write_tools(monkeypatch):
    import os
    from backend.tools.api import configured_apis, get_api
    from backend.tools.registry import registry

    monkeypatch.setenv(
        "SPECL00M_API_ENDPOINTS",
        '{"crm":{"base_url":"https://example.com","description":"CRM","capabilities":["customers"],"read_methods":["GET"],"write_methods":["POST"],"auth_env":"CRM_TOKEN"}}',
    )
    monkeypatch.setenv("CRM_TOKEN", "secret")

    api = configured_apis()[0]
    assert api.read_tool_id == "api:crm:read"
    assert api.write_tool_id == "api:crm:write"
    assert registry.get(api.read_tool_id).side_effecting is False
    assert registry.get(api.write_tool_id).side_effecting is True
    assert "secret" not in registry.get(api.read_tool_id).description


def test_configured_api_write_requires_approval(monkeypatch):
    from backend.tools.gateway import ToolGateway, ToolInvocation

    monkeypatch.setenv(
        "SPECL00M_API_ENDPOINTS",
        '{"crm":{"base_url":"https://example.com","read_methods":["GET"],"write_methods":["POST"],"auth_env":"CRM_TOKEN"}}',
    )
    gateway = ToolGateway()
    try:
        gateway.invoke(
            ToolInvocation(
                tool_id="api:crm:write",
                mode="live",
                input={"method":"POST","path":"/tickets","json":{"title":"test"}},
            ),
            approved=False,
        )
        assert False, "expected PermissionError"
    except PermissionError:
        pass
