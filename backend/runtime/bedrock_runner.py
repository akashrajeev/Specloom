from __future__ import annotations

import os
from typing import Any

from backend.bedrock_config import resolve_bedrock_model
from backend.tools.registry import registry
from backend.workflow.models import Node


class BedrockAgentRunner:
    """Adapter for executing agent nodes with Strands + Amazon Bedrock."""

    def __init__(self, model_id: str | None = None) -> None:
        try:
            from strands import Agent
            from strands.models import BedrockModel
        except ImportError as exc:
            raise RuntimeError("Install backend/requirements-aws.txt for Bedrock runtime.") from exc

        resolved = resolve_bedrock_model(model_id)
        allowed = {
            item.strip()
            for item in os.getenv("SPECL00M_ALLOWED_BEDROCK_MODELS", resolved).split(",")
            if item.strip()
        }
        if resolved not in allowed:
            allowed.add(resolved)
        self._Agent = Agent
        self._default_model_id = resolved
        self._allowed_models = allowed
        self._BedrockModel = BedrockModel
        self._model = BedrockModel(model_id=resolved)

    def __call__(self, node: Node, payload: Any) -> Any:
        from backend.runtime.agent_tools import build_agent_tools

        requested = [str(tool_id) for tool_id in node.config.get("tools", [])]
        bindings = {
            str(item.get("id")): item
            for item in node.config.get("capability_bindings", [])
            if isinstance(item, dict) and item.get("id")
        }
        allowed_tools = []
        for tool_id in requested:
            if tool_id.startswith("apiop:"):
                binding = bindings.get(tool_id)
                if binding is None:
                    raise ValueError(f"agent {node.id} has no compiled capability binding: {tool_id}")
                if bool(binding.get("side_effecting")):
                    raise PermissionError(f"agent {node.id} cannot directly use side-effecting capability: {tool_id}")
                allowed_tools.append(tool_id)
                continue
            try:
                spec = registry.get(tool_id)
            except KeyError as exc:
                raise ValueError(f"agent {node.id} requested unknown tool: {tool_id}") from exc
            if spec.side_effecting:
                raise PermissionError(f"agent {node.id} cannot directly use side-effecting tool: {tool_id}")
            allowed_tools.append(tool_id)

        requested_model = str(node.config.get("model") or self._default_model_id)
        # Existing compiled workflows may contain the base Nova Lite ID.
        # In APAC production, normalize that legacy value to the supported
        # cross-Region inference profile before creating BedrockModel.
        if requested_model in {"amazon.nova-lite-v1:0", "apac.amazon.nova-lite-v1:0"}:
            fallback = os.getenv("SPECL00M_BEDROCK_FALLBACK_MODEL_ID", "").strip()
            # Demo deployments intentionally prefer the lower-quota-cost fallback
            # so previously compiled Lite workflows remain executable.
            if fallback and fallback != requested_model:
                requested_model = fallback
        if requested_model not in self._allowed_models:
            raise PermissionError(
                f"agent {node.id} requested model not in allowlist: {requested_model}"
            )
        model = (
            self._model
            if requested_model == self._default_model_id
            else self._BedrockModel(model_id=requested_model)
        )

        instructions = str(
            node.config.get("instructions")
            or node.config.get("role")
            or "Complete the task."
        )
        system_prompt = (
            instructions
            + "\n\nRuntime rules: use only the provided tools; do not invent facts or "
            "credentials; cite retrieved evidence when the task requires evidence."
        )
        mcp_servers = [str(name) for name in node.config.get("mcp_servers", [])]
        mcp_clients = []
        if mcp_servers:
            from backend.tools.mcp import load_readonly_clients
            mcp_clients = load_readonly_clients(mcp_servers)

        # Walk the same provider chain as the compiler (Bedrock regions, then free-tier
        # fallbacks) so a capped Bedrock quota does not fail every run.
        from backend.llm import resilient_agent

        del model  # model choice is validated above; the chain builds provider models
        # Read the pages this agent is told to read before the model runs, so its answer is
        # grounded in retrieved text instead of depending on model tool-calling (free-tier
        # models often skip or mangle tool calls and then guess).
        fetched = ""
        if "url_fetch" in allowed_tools:
            fetched = _prefetch_urls(instructions + "\n" + str(payload))
            if fetched:
                allowed_tools = [tool_id for tool_id in allowed_tools if tool_id != "url_fetch"]

        agent = resilient_agent(
            requested_model,
            system_prompt=system_prompt,
            tools=build_agent_tools(allowed_tools, list(bindings.values())) + mcp_clients,
        )
        response = agent(
            "Execute your assigned role using only the supplied workflow context. "
            "Return the result needed by downstream workflow nodes.\n\n"
            + (
                "FETCHED PAGES (retrieved just now; use only these facts, and say plainly if a "
                "value is missing or a fetch failed):\n" + fetched + "\n\n"
                if fetched
                else ""
            )
            + "WORKFLOW INPUT:\n"
            + str(payload)
        )
        message = getattr(response, "message", None)
        if isinstance(message, dict):
            return {
                "agent": node.id,
                "output": message.get("content", []),
            }
        return {"agent": node.id, "output": str(response)}


def _prefetch_urls(text: str, limit: int = 5) -> str:
    import re

    from backend.tools.adapters import live_url_fetch

    urls: list[str] = []
    for match in re.findall(r"https?://[^\s'\"<>),]+", text):
        url = match.rstrip(".;:")
        if url not in urls:
            urls.append(url)
    blocks = []
    for url in urls[:limit]:
        try:
            page = live_url_fetch({"url": url})
            blocks.append(f"--- {url}\n{page.get('content', '')}")
        except Exception as exc:  # noqa: BLE001 - report the failure to the model verbatim
            blocks.append(f"--- {url}\nFETCH FAILED: {type(exc).__name__}: {exc}")
    return "\n\n".join(blocks)
