from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from backend.tools.api import ConfiguredAPI, configured_apis, invoke_configured_api
from backend.tools.adapters import (
    live_github_create_issue,
    live_github_get_repo,
    live_github_list_issues,
    live_github_search_code,
    live_url_fetch,
    live_web_search,
)


@dataclass(frozen=True)
class ToolSpec:
    id: str
    name: str
    description: str
    capabilities: tuple[str, ...]
    permissions: tuple[str, ...]
    side_effecting: bool = False
    handler: Callable[[dict[str, Any]], dict[str, Any]] | None = field(default=None, repr=False)

    def to_context(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "capabilities": list(self.capabilities),
            "permissions": list(self.permissions),
            "side_effecting": self.side_effecting,
            "requires_human_approval": self.side_effecting,
            "execution_modes": ["mock", "sandbox", "live"],
        }


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, ToolSpec] = {}

    def register(self, spec: ToolSpec) -> None:
        if spec.id in self._tools:
            raise ValueError(f"tool already registered: {spec.id}")
        self._tools[spec.id] = spec

    def get(self, tool_id: str) -> ToolSpec:
        existing = self._tools.get(tool_id)
        if existing is not None:
            return existing

        if tool_id.startswith("api:"):
            for api in configured_apis():
                if tool_id == api.read_tool_id:
                    return ToolSpec(
                        id=api.read_tool_id,
                        name=f"{api.name} API (read)",
                        description=api.description,
                        capabilities=(*api.capabilities, "api", "read"),
                        permissions=("READ",),
                        side_effecting=False,
                    )
                if tool_id == api.write_tool_id:
                    return ToolSpec(
                        id=api.write_tool_id,
                        name=f"{api.name} API (write)",
                        description=api.description,
                        capabilities=(*api.capabilities, "api", "write"),
                        permissions=("READ", "WRITE"),
                        side_effecting=True,
                    )
        raise KeyError(f"unknown tool: {tool_id}")

    def list(self) -> list[ToolSpec]:
        result = list(self._tools.values())
        known = {item.id for item in result}
        for item in configured_apis():
            for spec in (
                self.get(item.read_tool_id) if item.read_methods else None,
                self.get(item.write_tool_id) if item.write_methods else None,
            ):
                if spec is not None and spec.id not in known:
                    result.append(spec)
                    known.add(spec.id)
        return result

    def context_tools(self) -> list[dict[str, Any]]:
        return [spec.to_context() for spec in self._tools.values()]

    def invoke(
        self,
        tool_id: str,
        payload: dict[str, Any],
        *,
        allow_side_effects: bool = False,
    ) -> dict[str, Any]:
        spec = self.get(tool_id)
        if spec.side_effecting and not allow_side_effects:
            raise PermissionError(f"side-effecting tool blocked: {tool_id}")
        if tool_id.startswith("api:"):
            return invoke_configured_api(
                tool_id,
                payload,
                approved=allow_side_effects,
            )
        if spec.handler is None:
            return {"tool": tool_id, "status": "simulated", "input": payload}
        return spec.handler(payload)


registry = ToolRegistry()
registry.register(
    ToolSpec(
        id="web_search",
        name="Web Search",
        description="Search the public web for current information.",
        capabilities=("search", "read", "current_information"),
        permissions=("READ",),
        handler=live_web_search,
    )
)
registry.register(
    ToolSpec(
        id="url_fetch",
        name="URL Fetch",
        description="Fetch readable content from a public HTTP or HTTPS URL.",
        capabilities=("fetch", "read", "documents"),
        permissions=("READ",),
        handler=live_url_fetch,
    )
)
registry.register(
    ToolSpec(
        id="github.get_repo",
        name="GitHub Repository",
        description="Read public or authorized repository metadata.",
        capabilities=("github", "read", "repository_metadata"),
        permissions=("READ",),
        handler=live_github_get_repo,
    )
)
registry.register(
    ToolSpec(
        id="github.list_issues",
        name="GitHub Issues",
        description="List issues from a public or authorized repository.",
        capabilities=("github", "read", "issues"),
        permissions=("READ",),
        handler=live_github_list_issues,
    )
)
registry.register(
    ToolSpec(
        id="github.search_code",
        name="GitHub Code Search",
        description="Search repository code for relevant symbols or text.",
        capabilities=("github", "read", "code_search"),
        permissions=("READ",),
        handler=live_github_search_code,
    )
)
registry.register(
    ToolSpec(
        id="github.create_issue",
        name="GitHub Create Issue",
        description="Create an issue in an authorized repository.",
        capabilities=("github", "write", "create_issue"),
        permissions=("READ", "WRITE"),
        side_effecting=True,
        handler=live_github_create_issue,
    )
)
