from __future__ import annotations

from typing import Any, Callable

from backend.tools.gateway import ToolGateway, ToolInvocation
from backend.capabilities.models import CapabilitySpec

gateway = ToolGateway()


def build_agent_tools(
    tool_ids: list[str],
    capability_bindings: list[dict[str, Any]] | None = None,
) -> list[Any]:
    from strands import tool

    bindings = {
        str(item.get("id")): CapabilitySpec.model_validate(item)
        for item in (capability_bindings or [])
        if isinstance(item, dict) and item.get("id")
    }
    tools: list[Any] = []
    for tool_id in tool_ids:
        if tool_id.startswith("apiop:"):
            capability = bindings.get(tool_id)
            if capability is None:
                raise ValueError(f"missing compiled capability binding: {tool_id}")
            if capability.side_effecting:
                raise PermissionError(f"agent cannot use side-effecting capability: {tool_id}")
            tools.append(_openapi_tool(tool, capability))
        elif tool_id == "web_search":
            tools.append(_web_search_tool(tool))
        elif tool_id == "url_fetch":
            tools.append(_url_fetch_tool(tool))
        elif tool_id == "github.get_repo":
            tools.append(_github_get_repo_tool(tool))
        elif tool_id == "github.list_issues":
            tools.append(_github_list_issues_tool(tool))
        elif tool_id == "github.search_code":
            tools.append(_github_search_code_tool(tool))
        elif tool_id.startswith("api:"):
            tools.append(_configured_api_tool(tool, tool_id))
        else:
            raise ValueError(f"unknown agent tool: {tool_id}")
    return tools


def _openapi_tool(decorator: Callable[..., Any], capability: CapabilitySpec) -> Any:
    safe_name = capability.id.replace(":", "_").replace("-", "_")

    @decorator(name=safe_name)
    def openapi_capability(parameters: dict[str, Any]) -> dict[str, Any]:
        """Execute a discovered read-only OpenAPI operation using deployment-held credentials."""
        return gateway.invoke(
            ToolInvocation(
                tool_id=capability.id,
                mode="live",
                input=parameters,
                capability=capability.model_dump(mode="json"),
            ),
            approved=False,
        )

    return openapi_capability


def _web_search_tool(decorator: Callable[..., Any]) -> Any:
    @decorator(name="web_search")
    def web_search(query: str) -> dict[str, Any]:
        """Search the public web for current information."""
        return gateway.invoke(ToolInvocation(tool_id="web_search", mode="live", input={"query": query}))
    return web_search


def _url_fetch_tool(decorator: Callable[..., Any]) -> Any:
    @decorator(name="url_fetch")
    def url_fetch(url: str) -> dict[str, Any]:
        """Fetch readable text from a public HTTP or HTTPS URL."""
        return gateway.invoke(ToolInvocation(tool_id="url_fetch", mode="live", input={"url": url}))
    return url_fetch


def _github_get_repo_tool(decorator: Callable[..., Any]) -> Any:
    @decorator(name="github_get_repo")
    def github_get_repo(repository: str) -> dict[str, Any]:
        """Read metadata for a GitHub owner/name repository."""
        return gateway.invoke(ToolInvocation(tool_id="github.get_repo", mode="live", input={"repository": repository}))
    return github_get_repo


def _github_list_issues_tool(decorator: Callable[..., Any]) -> Any:
    @decorator(name="github_list_issues")
    def github_list_issues(repository: str, state: str = "open", per_page: int = 10) -> dict[str, Any]:
        """Read recent GitHub issues for a repository."""
        return gateway.invoke(ToolInvocation(tool_id="github.list_issues", mode="live", input={"repository": repository, "state": state, "per_page": per_page}))
    return github_list_issues


def _github_search_code_tool(decorator: Callable[..., Any]) -> Any:
    @decorator(name="github_search_code")
    def github_search_code(query: str, repository: str = "") -> dict[str, Any]:
        """Search GitHub code, optionally scoped to owner/name."""
        return gateway.invoke(ToolInvocation(tool_id="github.search_code", mode="live", input={"query": query, "repository": repository}))
    return github_search_code


def _configured_api_tool(decorator: Callable[..., Any], tool_id: str) -> Any:
    safe_name = tool_id.replace(":", "_").replace("-", "_")

    @decorator(name=safe_name)
    def configured_api_request(
        method: str,
        path: str,
        query: dict[str, Any] | None = None,
        json: Any = None,
    ) -> dict[str, Any]:
        """Call a configured read-only API endpoint using its deployment-held credential."""
        from backend.tools.registry import registry
        spec = registry.get(tool_id)
        if spec.side_effecting:
            raise PermissionError(f"{tool_id} is write-capable and must be a dedicated tool node after approval")
        return gateway.invoke(
            ToolInvocation(
                tool_id=tool_id,
                mode="live",
                input={"method": method, "path": path, "query": query or {}, "json": json},
            ),
            approved=False,
        )
    return configured_api_request
