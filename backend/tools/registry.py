from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from backend.tools.adapters import live_github_create_issue, live_url_fetch, live_web_search


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
        try:
            return self._tools[tool_id]
        except KeyError as exc:
            raise KeyError(f"unknown tool: {tool_id}") from exc

    def list(self) -> list[ToolSpec]:
        return list(self._tools.values())

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
        if spec.handler is None:
            return {"tool": tool_id, "status": "simulated", "input": payload}
        return spec.handler(payload)


registry = ToolRegistry()
registry.register(
    ToolSpec(
        id="web_search",
        name="Web Search",
        description="Search configured web sources.",
        capabilities=("search", "read"),
        permissions=("READ",),
        side_effecting=False,
        handler=live_web_search,
    )
)
registry.register(
    ToolSpec(
        id="url_fetch",
        name="URL Fetch",
        description="Fetch a readable public URL.",
        capabilities=("fetch", "read"),
        permissions=("READ",),
        side_effecting=False,
        handler=live_url_fetch,
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
