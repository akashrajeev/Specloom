from __future__ import annotations

import json
import os
from typing import Any

from backend.context.models import ContextGraph, Constraint, Provenance, Requirement


class BedrockContextAnalyzer:
    """Extract structured context from source text using a Bedrock-backed Strands agent."""

    def __init__(self, model_id: str = "") -> None:
        try:
            from strands import Agent
            from strands.models import BedrockModel
        except ImportError as exc:
            raise RuntimeError(
                "AWS context-analysis dependencies are missing. Install backend/requirements-aws.txt"
            ) from exc

        resolved = model_id or os.getenv(
            "SPECL00M_BEDROCK_MODEL_ID", "amazon.nova-lite-v1:0"
        )
        self._agent = Agent(
            model=BedrockModel(model_id=resolved),
            system_prompt=(
                "You are Specloom's Context Analyst. Extract only facts explicitly "
                "supported by the supplied source. Do not invent missing rules. "
                "Return JSON only with requirements and constraints. Each item must "
                "include statement, priority/severity, locator, quote."
            ),
        )

    def analyze(self, text: str) -> dict[str, Any]:
        response = self._agent(
            "SOURCE TEXT:\n" + text[:100_000] + "\n\n"
            "JSON shape:\n"
            '{"requirements":[{"statement":"...","priority":"medium","locator":"line:1","quote":"..."}],'
            '"constraints":[{"statement":"...","severity":"blocking","locator":"line:2","quote":"..."}]}'
        )
        return self._extract_json(response)

    @staticmethod
    def _extract_json(response: Any) -> dict[str, Any]:
        message = getattr(response, "message", None)
        text = ""
        if isinstance(message, dict):
            content = message.get("content", [])
            for item in content:
                if isinstance(item, dict) and item.get("text"):
                    text += str(item["text"])

        if not text:
            text = str(response)

        start = text.find("{")
        end = text.rfind("}")
        if start < 0 or end <= start:
            raise ValueError("context analyst response did not contain JSON")
        value = json.loads(text[start:end + 1])
        if not isinstance(value, dict):
            raise ValueError("context analyst response must be an object")
        return value


def apply_bedrock_analysis(
    graph: ContextGraph,
    source_id: str,
    result: dict[str, Any],
) -> ContextGraph:
    requirements = [
        _requirement(source_id, item)
        for item in result.get("requirements", [])
        if isinstance(item, dict) and str(item.get("statement", "")).strip()
    ]
    constraints = [
        _constraint(source_id, item)
        for item in result.get("constraints", [])
        if isinstance(item, dict) and str(item.get("statement", "")).strip()
    ]

    current_req = {item.id: item for item in graph.requirements}
    current_con = {item.id: item for item in graph.constraints}
    current_req.update({item.id: item for item in requirements})
    current_con.update({item.id: item for item in constraints})

    return graph.model_copy(
        update={
            "requirements": list(current_req.values()),
            "constraints": list(current_con.values()),
        }
    )


def _requirement(source_id: str, item: dict[str, Any]) -> Requirement:
    statement = str(item["statement"]).strip()
    priority = str(item.get("priority", "medium")).lower()
    if priority not in {"low", "medium", "high", "critical"}:
        priority = "medium"
    return Requirement(
        id=_stable_id("req", source_id, statement),
        statement=statement,
        priority=priority,
        provenance=[
            Provenance(
                source_id=source_id,
                locator=str(item.get("locator") or "source"),
                quote=str(item.get("quote") or statement)[:280],
                confidence=0.9,
            )
        ],
    )


def _constraint(source_id: str, item: dict[str, Any]) -> Constraint:
    statement = str(item["statement"]).strip()
    severity = str(item.get("severity", "info")).lower()
    if severity not in {"info", "warning", "blocking"}:
        severity = "info"
    return Constraint(
        id=_stable_id("con", source_id, statement),
        statement=statement,
        severity=severity,
        provenance=[
            Provenance(
                source_id=source_id,
                locator=str(item.get("locator") or "source"),
                quote=str(item.get("quote") or statement)[:280],
                confidence=0.9,
            )
        ],
    )


def _stable_id(prefix: str, source_id: str, text: str) -> str:
    import hashlib
    normalized = " ".join(text.lower().split())
    digest = hashlib.sha1(f"{source_id}:{normalized}".encode()).hexdigest()[:10]
    return f"{prefix}_{digest}"
