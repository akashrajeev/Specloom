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
