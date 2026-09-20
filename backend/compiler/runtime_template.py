from __future__ import annotations

RUNTIME_SOURCE = r'''from __future__ import annotations

import json
import os
import ssl
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

from .observability import emit_event

ROOT = Path(__file__).resolve().parent.parent
WORKFLOW = json.loads((ROOT / "workflow-ir.json").read_text())

_TRIGGER_ID = WORKFLOW["trigger"]["id"]
_NODES = {node["id"]: node for node in WORKFLOW["nodes"]}
_ALL_NODES = {_TRIGGER_ID: WORKFLOW["trigger"], **_NODES}


def execute_workflow(
    payload: dict[str, Any] | None = None,
    *,
    mode: str = "mock",
    approved: bool = False,
) -> dict[str, Any]:
    if mode not in {"mock", "sandbox", "live"}:
        raise ValueError("mode must be mock, sandbox, or live")

    events: list[dict[str, Any]] = []
    state: dict[str, Any] = {
        "input": payload or {},
        "nodes": {},
        "mode": mode,
        "events": events,
    }
    emit_event(events, "workflow.started", workflow_id=WORKFLOW["id"], mode=mode)
    pending_approval = False
    visited: set[str] = set()
    queue = [_TRIGGER_ID]

    while queue:
        node_id = queue.pop(0)
        if node_id in visited:
            continue

        visited.add(node_id)
        node = _ALL_NODES[node_id]

        if node["type"] != "trigger":
            emit_event(
                events,
                "node.started",
                node_id=node_id,
                node_type=node["type"],
            )
            try:
                outcome = _execute_node(
                    node,
                    state,
                    mode=mode,
                    approved=approved,
                )
            except Exception as exc:
                emit_event(
                    events,
                    "node.failed",
                    node_id=node_id,
                    node_type=node["type"],
                    error=str(exc),
                )
                raise
            state["nodes"][node_id] = outcome
            emit_event(
                events,
                "node.completed",
                node_id=node_id,
                node_type=node["type"],
                status=outcome.get("status"),
            )
            if outcome.get("status") == "waiting":
                pending_approval = True
                break

        children = [
            edge for edge in WORKFLOW["edges"]
            if edge.get("from") == node_id
        ]
        if node["type"] == "condition":
            children = _select_condition_edges(children, state)

        queue.extend(
            edge["to"]
            for edge in children
            if edge.get("to") not in visited
        )

    output_nodes = [
        node_id
        for node_id, node in _NODES.items()
        if node["type"] == "output" and node_id in state["nodes"]
    ]
    output = (
        state["nodes"][output_nodes[-1]]
        if output_nodes
        else {"value": state["input"]}
    )
    emit_event(
        events,
        "workflow.waiting" if pending_approval else "workflow.completed",
        workflow_id=WORKFLOW["id"],
    )
    return {
        "status": "waiting" if pending_approval else "completed",
        "system_id": _load_system()["id"],
        "workflow_id": WORKFLOW["id"],
        "output": output,
        "nodes": state["nodes"],
        "visited": sorted(visited),
        "events": events,
    }


def _execute_node(
    node: dict[str, Any],
    state: dict[str, Any],
    *,
    mode: str,
    approved: bool,
) -> dict[str, Any]:
    node_type = node["type"]
    config = node.get("config") or {}

    if node_type == "agent":
        return _run_agent(config, state, mode)

    if node_type == "tool":
        return _run_tool(config, state, mode, approved)

    if node_type == "human_approval":
        return {"status": "approved"} if approved else {
            "status": "waiting",
            "reason": "human approval required",
        }

    if node_type == "condition":
        return {"status": "evaluated"}

    if node_type == "parallel":
        return {"status": "parallel-dispatch"}

    if node_type == "loop":
        maximum = config.get("max_iterations", 1)
        executed = min(maximum, 1) if isinstance(maximum, int) else 1
        return {
            "status": "loop-bounded",
            "max_iterations": maximum,
            "executed_iterations": executed,
        }

    if node_type == "output":
        return {"status": "output", "value": state["input"]}

    return {"status": "completed"}


def _run_agent(
    config: dict[str, Any],
    state: dict[str, Any],
    mode: str,
) -> dict[str, Any]:
    role = str(
        config.get(
            "role",
            config.get("prompt", "perform the requested task"),
        )
    )

    if mode != "live":
        return {
            "status": "completed",
            "mode": mode,
            "text": f"mock-agent: {role}",
        }

    base_url = os.environ.get("SPECL00M_MODEL_BASE_URL", "").strip()
    model = os.environ.get("SPECL00M_MODEL_NAME", "").strip()
    api_key = os.environ.get("SPECL00M_MODEL_API_KEY", "").strip()
    if not base_url or not model:
        raise RuntimeError(
            "live agent execution requires SPECL00M_MODEL_BASE_URL "
            "and SPECL00M_MODEL_NAME"
        )

    url = base_url.rstrip("/") + "/chat/completions"
    body = {
        "model": model,
        "messages": [
            {"role": "system", "content": role},
            {
                "role": "user",
                "content": json.dumps(state["input"], default=str),
            },
        ],
    }
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    request = urllib.request.Request(
        url,
        data=json.dumps(body).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        decoded = json.loads(response.read().decode("utf-8"))

    choices = decoded.get("choices") or []
    text = (
        choices[0].get("message", {}).get("content", "")
        if choices
        else ""
    )
    return {
        "status": "completed",
        "mode": "live",
        "text": text,
        "raw": decoded,
    }


def _run_tool(
    config: dict[str, Any],
    state: dict[str, Any],
    mode: str,
    approved: bool,
) -> dict[str, Any]:
    capability = config.get("capability")
    if not isinstance(capability, dict):
        return {
            "status": "simulated",
            "mode": mode,
            "tool_ref": config.get("tool_ref"),
        }

    side_effecting = bool(capability.get("side_effecting"))
    if side_effecting and mode == "live" and not approved:
        return {
            "status": "waiting",
            "reason": "side-effecting capability requires approval",
        }

    if mode != "live":
        return {
            "status": "simulated",
            "mode": mode,
            "capability_id": capability.get("id"),
        }

    if capability.get("kind") == "synthesized":
        return _invoke_synthesized(capability, state["input"])

    return {
        "status": "unresolved",
        "reason": "standalone generated runtime requires a provisioned adapter",
        "capability_id": capability.get("id"),
    }


def _invoke_synthesized(
    capability: dict[str, Any],
    payload: dict[str, Any],
) -> dict[str, Any]:
    family_id = str(capability.get("id", "synth:external"))
    if ":" in family_id:
        family_id = family_id.split(":", 2)[1]

    family = "".join(
        char if char.isalnum() else "_"
        for char in family_id.upper()
    ).strip("_") or "EXTERNAL"

    prefix = f"SPECL00M_SYNTH_{family}"
    base_url = os.environ.get(f"{prefix}_BASE_URL", "").strip()
    path = os.environ.get(f"{prefix}_PATH", "/").strip() or "/"
    method = os.environ.get(f"{prefix}_METHOD", "POST").strip().upper()
    api_key = os.environ.get(f"{prefix}_API_KEY", "").strip()

    if not base_url:
        raise RuntimeError(
            f"missing {prefix}_BASE_URL for live synthesized capability"
        )

    parsed = urllib.parse.urlparse(base_url)
    if parsed.scheme != "https":
        raise RuntimeError(
            "live synthesized capabilities require HTTPS endpoints"
        )

    target = urllib.parse.urljoin(
        base_url.rstrip("/") + "/",
        path.lstrip("/"),
    )
    target_parsed = urllib.parse.urlparse(target)
    if target_parsed.hostname != parsed.hostname:
        raise RuntimeError(
            "synthesized capability path must stay on the configured host"
        )

    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    request = urllib.request.Request(
        target,
        data=json.dumps(payload).encode("utf-8"),
        headers=headers,
        method=method,
    )

    context = ssl.create_default_context()
    try:
        with urllib.request.urlopen(
            request,
            timeout=30,
            context=context,
        ) as response:
            body = response.read().decode("utf-8")
            content_type = response.headers.get("content-type", "")
            value: Any = (
                json.loads(body)
                if "json" in content_type
                else body
            )
            return {"status": "completed", "response": value}
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(
            f"generated capability request failed: HTTP {exc.code}: {detail}"
        ) from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(
            f"generated capability request failed: {exc.reason}"
        ) from exc


def _select_condition_edges(
    edges: list[dict[str, Any]],
    state: dict[str, Any],
) -> list[dict[str, Any]]:
    if not edges:
        return []

    for edge in edges:
        condition = edge.get("condition")
        if isinstance(condition, bool) and condition:
            return [edge]
        if isinstance(condition, str) and _matches_expression(
            condition,
            state,
        ):
            return [edge]

    defaults = [
        edge
        for edge in edges
        if str(edge.get("label", "")).lower()
        in {"else", "default", "fallback"}
    ]
    return defaults[:1] or edges[:1]


def _matches_expression(
    expression: str,
    state: dict[str, Any],
) -> bool:
    expression = expression.strip()
    for operator in ("==", "!=", ">=", "<=", ">", "<"):
        if operator in expression:
            left, right = (
                part.strip()
                for part in expression.split(operator, 1)
            )
            actual = _lookup(left, state)
            expected = _coerce(right)
            return {
                "==": actual == expected,
                "!=": actual != expected,
                ">=": actual >= expected,
                "<=": actual <= expected,
                ">": actual > expected,
                "<": actual < expected,
            }[operator]
    return bool(_lookup(expression, state))


def _lookup(path: str, state: dict[str, Any]) -> Any:
    path = path.removeprefix("input.")
    current: Any = state
    for part in path.split("."):
        if isinstance(current, dict):
            current = current.get(part)
        else:
            return None
    return current


def _coerce(value: str) -> Any:
    if value.lower() in {"true", "false"}:
        return value.lower() == "true"
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return value.strip("\"'")


def _load_system() -> dict[str, Any]:
    return json.loads((ROOT / "system-ir.json").read_text())
'''
