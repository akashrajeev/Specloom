from __future__ import annotations

import hashlib
import json
import os
from typing import Any

from pydantic import BaseModel, Field

from backend.context.models import (
    ContextEntity,
    ContextExample,
    ContextGraph,
    Constraint,
    Provenance,
    Requirement,
)


class ExtractedRequirement(BaseModel):
    statement: str
    priority: str = "medium"
    quote: str = ""
    locator: str = ""


class ExtractedConstraint(BaseModel):
    statement: str
    severity: str = "info"
    quote: str = ""
    locator: str = ""


class ExtractedEntity(BaseModel):
    name: str
    type: str = "concept"


class ExtractedExample(BaseModel):
    input: Any
    expected: Any
    quote: str = ""
    locator: str = ""


class ContextAnalysis(BaseModel):
    requirements: list[ExtractedRequirement] = Field(default_factory=list)
    constraints: list[ExtractedConstraint] = Field(default_factory=list)
    entities: list[ExtractedEntity] = Field(default_factory=list)
    examples: list[ExtractedExample] = Field(default_factory=list)


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
                "supported by the supplied source. Never invent requirements, "
                "constraints, entities, examples, or capabilities. Preserve exact "
                "meaning and provide a short supporting quote for each extracted "
                "requirement or constraint. Return only the requested structured data."
            ),
        )

    def analyze(self, text: str) -> dict[str, Any]:
        prompt = (
            "Analyze this source for a system compiler. Extract explicit requirements, "
            "constraints/policies, named entities/concepts, and concrete examples. "
            "Do not infer missing rules. For requirements and constraints, quote the "
            "source and provide a locator when possible.\\n\\nSOURCE TEXT:\\n"
            + text[:100_000]
        )
        try:
            result = self._agent.structured_output(ContextAnalysis, prompt=prompt)
            if isinstance(result, ContextAnalysis):
                return result.model_dump(mode="json")
            if hasattr(result, "structured_output"):
                value = result.structured_output
                if isinstance(value, ContextAnalysis):
                    return value.model_dump(mode="json")
                if isinstance(value, dict):
                    return ContextAnalysis.model_validate(value).model_dump(mode="json")
        except Exception:
            pass

        response = self._agent(prompt)
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

    entities = [
        ContextEntity(
            id=_stable_id("ent", source_id, str(item.get("name", ""))),
            type=str(item.get("type") or "concept"),
            name=str(item["name"]).strip(),
        )
        for item in result.get("entities", [])
        if isinstance(item, dict) and str(item.get("name", "")).strip()
    ]
    current_entities = {item.id: item for item in graph.entities}
    current_entities.update({item.id: item for item in entities})

    examples = [
        _example(source_id, item, index)
        for index, item in enumerate(result.get("examples", []))
        if isinstance(item, dict) and "input" in item and "expected" in item
    ]
    current_examples = {item.id: item for item in graph.examples}
    current_examples.update({item.id: item for item in examples})

    return graph.model_copy(
        update={
            "requirements": list(current_req.values()),
            "constraints": list(current_con.values()),
            "entities": list(current_entities.values()),
            "examples": list(current_examples.values()),
        }
    )


def _requirement(source_id: str, item: dict[str, Any]) -> Requirement:
    statement = str(item["statement"]).strip()
    priority = str(item.get("priority", "medium")).lower()
    if priority not in {"low", "medium", "high", "critical"}:
        priority = "medium"
    quote = str(item.get("quote") or statement).strip()
    locator = str(item.get("locator") or _quote_locator(source_id, quote)).strip()
    return Requirement(
        id=_stable_id("req", source_id, statement),
        statement=statement,
        priority=priority,
        provenance=[
            Provenance(
                source_id=source_id,
                locator=locator,
                quote=quote[:280],
                confidence=0.9,
            )
        ],
    )


def _constraint(source_id: str, item: dict[str, Any]) -> Constraint:
    statement = str(item["statement"]).strip()
    severity = str(item.get("severity", "info")).lower()
    if severity not in {"info", "warning", "blocking"}:
        severity = "info"
    quote = str(item.get("quote") or statement).strip()
    locator = str(item.get("locator") or _quote_locator(source_id, quote)).strip()
    return Constraint(
        id=_stable_id("con", source_id, statement),
        statement=statement,
        severity=severity,
        provenance=[
            Provenance(
                source_id=source_id,
                locator=locator,
                quote=quote[:280],
                confidence=0.9,
            )
        ],
    )


def _example(source_id: str, item: dict[str, Any], index: int) -> ContextExample:
    quote = str(item.get("quote") or "").strip()
    locator = str(item.get("locator") or "source").strip()
    return ContextExample(
        id=_stable_id("ex", source_id, f"{index}:{item.get('input')!r}:{item.get('expected')!r}"),
        input=item["input"],
        expected=item["expected"],
        provenance=[
            Provenance(
                source_id=source_id,
                locator=locator,
                quote=quote[:280] if quote else None,
                confidence=0.85,
            )
        ],
    )


def _quote_locator(source_id: str, quote: str) -> str:
    # The model may not provide a locator; the source ID still keeps the provenance stable.
    return f"{source_id}:source"


def _stable_id(prefix: str, source_id: str, text: str) -> str:
    normalized = " ".join(text.lower().split())
    digest = hashlib.sha1(f"{source_id}:{normalized}".encode()).hexdigest()[:10]
    return f"{prefix}_{digest}"
