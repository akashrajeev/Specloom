from __future__ import annotations

from typing import Any, Callable

from backend.tools.gateway import ToolGateway, ToolInvocation

gateway = ToolGateway()


def build_agent_tools(tool_ids: list[str]) -> list[Any]:
    from strands import tool

    tools: list[Any] = []

    for tool_id in tool_ids:
        if tool_id == "web_search":
            tools.append(_web_search_tool(tool))
        elif tool_id == "url_fetch":
            tools.append(_url_fetch_tool(tool))

    return tools


def _web_search_tool(decorator: Callable[..., Any]) -> Any:
    @decorator(name="web_search")
    def web_search(query: str) -> dict[str, Any]:
        """Search the configured public web sources for a query."""
        return gateway.invoke(
            ToolInvocation(
                tool_id="web_search",
                mode="live",
                input={"query": query},
            )
        )

    return web_search


def _url_fetch_tool(decorator: Callable[..., Any]) -> Any:
    @decorator(name="url_fetch")
    def url_fetch(url: str) -> dict[str, Any]:
        """Fetch readable text from a public HTTP or HTTPS URL."""
        return gateway.invoke(
            ToolInvocation(
                tool_id="url_fetch",
                mode="live",
                input={"url": url},
            )
        )

    return url_fetch
