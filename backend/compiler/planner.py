from __future__ import annotations

import hashlib
import json
import os
import re
from typing import Any, Protocol

from pydantic import BaseModel, Field

from backend.bedrock_config import resolve_bedrock_model
from backend.context.models import (
    ContextEntity,
    ContextGraph,
    Provenance,
    Requirement,
    Source,
)


class PlannerRequirement(BaseModel):
    statement: str = Field(min_length=5, max_length=500)
    priority: str = "high"


class PlannerEntity(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    type: str = Field(default="domain", min_length=1, max_length=80)
    fields: list[dict[str, Any]] = Field(default_factory=list)


class SystemPlan(BaseModel):
    requirements: list[PlannerRequirement] = Field(default_factory=list)
    entities: list[PlannerEntity] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)


class SystemPlanner(Protocol):
    def plan(self, goal: str, context: ContextGraph) -> SystemPlan:
        ...


class DeterministicSystemPlanner:
    """Conservative fallback that makes the goal itself an explicit requirement."""

    def plan(self, goal: str, context: ContextGraph) -> SystemPlan:
        requirements: list[PlannerRequirement] = [
            PlannerRequirement(
                statement=f"The system must satisfy the requested outcome: {goal.strip()}",
                priority="high",
            )
        ]

        text = goal.lower()
        heuristics = [
            (
                r"\b(login|sign in|authentication|oauth|jwt)\b",
                "The system must protect authenticated operations with an explicit identity boundary.",
            ),
            (
                r"\b(database|persist|store|save|records?)\b",
                "The system must persist required state durably and preserve it across executions.",
            ),
            (
                r"\b(search|filter|query)\b",
                "The system must support the requested search or filtering behavior.",
            ),
            (
                r"\b(dashboard|frontend|website|web app|ui)\b",
                "The system must expose the requested behavior through a usable web interface.",
            ),
            (
                r"\b(schedule|scheduled|daily|hourly|weekly|every morning)\b",
                "The system must execute the requested recurring operation according to its schedule.",
            ),
        ]
        for pattern, statement in heuristics:
            if re.search(pattern, text):
                requirements.append(
                    PlannerRequirement(statement=statement, priority="high")
                )

        return SystemPlan(
            requirements=self._dedupe_requirements(requirements),
            entities=[],
            assumptions=[],
        )

    @staticmethod
    def _dedupe_requirements(
        requirements: list[PlannerRequirement],
    ) -> list[PlannerRequirement]:
        seen: set[str] = set()
        result: list[PlannerRequirement] = []
        for item in requirements:
            key = " ".join(item.statement.lower().split())
            if key not in seen:
                seen.add(key)
                result.append(item)
        return result


class BedrockSystemPlanner:
    """LLM-backed planner producing structured requirements before architecture."""

    def __init__(self, model_id: str = "") -> None:
        try:
            from strands import Agent
            from strands.models import BedrockModel
        except ImportError as exc:
            raise RuntimeError(
                "AWS architect dependencies are missing. Install backend/requirements-aws.txt"
            ) from exc

        resolved_model = resolve_bedrock_model(model_id)
        self._agent = Agent(
            model=BedrockModel(model_id=resolved_model),
            system_prompt=(
                "You are Specloom's system requirements planner. "
                "Translate a natural-language software problem into a concise, "
                "implementation-relevant SystemPlan. Preserve facts from context, "
                "do not invent external APIs or credentials, and return only SystemPlan JSON."
            ),
        )

    def plan(self, goal: str, context: ContextGraph) -> SystemPlan:
        prompt = f"""
USER GOAL
{goal}

EXISTING CONTEXT
{context.model_dump_json(indent=2)}

PLANNING TASK
1. Extract the user's actual outcome and turn it into testable high-level requirements.
2. Add important security, persistence, scheduling, interface, reliability, and user-experience requirements only when the goal/context justifies them.
3. Identify obvious domain entities that a generated application would need.
4. Do not invent providers, URLs, credentials, undocumented permissions, or external systems.
5. Prefer 3-10 useful requirements over generic filler.
6. Return only JSON matching SystemPlan.

SystemPlan schema:
{json.dumps(SystemPlan.model_json_schema(), indent=2)}
""".strip()

        result = self._agent(
            prompt,
            structured_output_model=SystemPlan,
        )
        structured = getattr(result, "structured_output", result)

        if isinstance(structured, SystemPlan):
            return structured
        if isinstance(structured, dict):
            return SystemPlan.model_validate(structured)
        return SystemPlan.model_validate(json.loads(str(structured)))


class ConfiguredSystemPlanner:
    """Use the model-backed planner in production and a conservative fallback in tests."""

    def __init__(self, architect_mode: str | None = None) -> None:
        requested = os.getenv("SPECL00M_SYSTEM_PLANNER_MODE", "auto").lower()
        if requested not in {"auto", "bedrock", "deterministic", "off"}:
            requested = "auto"

        if requested == "auto":
            mode = (
                "bedrock"
                if (architect_mode or os.getenv("SPECL00M_ARCHITECT_MODE", "bedrock")).lower()
                == "bedrock"
                else "deterministic"
            )
        else:
            mode = requested

        self.mode = mode
        self._impl: SystemPlanner | None = None

    def _planner(self) -> SystemPlanner:
        if self._impl is not None:
            return self._impl

        if self.mode == "bedrock":
            self._impl = BedrockSystemPlanner()
        else:
            self._impl = DeterministicSystemPlanner()

        return self._impl

    def enrich(self, goal: str, context: ContextGraph) -> ContextGraph:
        if self.mode == "off":
            return context

        plan = self._planner().plan(goal, context)
        source_id = "src_planner_" + hashlib.sha256(goal.strip().encode("utf-8")).hexdigest()[:12]

        # A planner source belongs to one goal. Drop sources and requirements planned
        # for earlier goals so they do not leak into this design or its tests.
        stale_sources = {
            item.id for item in context.sources
            if item.id.startswith("src_planner_") and item.id != source_id
        }
        sources = [item for item in context.sources if item.id not in stale_sources]
        if stale_sources:
            context = context.model_copy(update={
                "requirements": [
                    item for item in context.requirements
                    if not item.provenance
                    or not {ref.source_id for ref in item.provenance} <= stale_sources
                ],
            })
        if not any(item.id == source_id for item in sources):
            sources.append(
                Source(
                    id=source_id,
                    kind="text",
                    name="System Planner",
                    content_hash=hashlib.sha256(goal.encode("utf-8")).hexdigest(),
                )
            )

        requirements = list(context.requirements)
        existing_requirements = {
            " ".join(item.statement.lower().split())
            for item in requirements
        }
        for index, item in enumerate(plan.requirements):
            statement = " ".join(item.statement.split())
            key = statement.lower()
            if key in existing_requirements:
                continue
            requirements.append(
                Requirement(
                    id=f"req_plan_{hashlib.sha1((source_id + str(index) + statement).encode('utf-8')).hexdigest()[:10]}",
                    statement=statement,
                    priority=item.priority
                    if item.priority in {"low", "medium", "high", "critical"}
                    else "high",
                    provenance=[
                        Provenance(
                            source_id=source_id,
                            locator=f"planner:{index + 1}",
                            quote=statement[:280],
                            confidence=0.88,
                        )
                    ],
                )
            )
            existing_requirements.add(key)

        entities = list(context.entities)
        existing_entities = {
            " ".join(item.name.lower().split())
            for item in entities
        }
        for entity in plan.entities:
            name = " ".join(entity.name.split())
            key = name.lower()
            if key in existing_entities:
                continue
            entities.append(
                ContextEntity(
                    id=f"entity_plan_{hashlib.sha1((source_id + key).encode('utf-8')).hexdigest()[:10]}",
                    type=entity.type,
                    name=name,
                    fields=[
                        field
                        for field in entity.fields
                        if isinstance(field, dict)
                        and field.get("name")
                    ],
                )
            )
            existing_entities.add(key)

        return context.model_copy(
            update={
                "sources": sources,
                "requirements": requirements,
                "entities": entities,
            }
        )
