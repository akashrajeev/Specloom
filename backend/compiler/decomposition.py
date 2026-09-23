from __future__ import annotations

from backend.llm import compact_context_json, resilient_agent

import hashlib
import json
import os
import re
from typing import Any, Protocol, Literal

from pydantic import BaseModel, Field, model_validator

from backend.bedrock_config import resolve_bedrock_model
from backend.context.models import (
    ContextEntity,
    ContextGraph,
    Provenance,
    Requirement,
)


class DecompositionStep(BaseModel):
    id: str = Field(min_length=1, max_length=80)
    objective: str = Field(min_length=5, max_length=500)
    responsibilities: list[str] = Field(default_factory=list, max_length=12)
    inputs: list[str] = Field(default_factory=list, max_length=12)
    outputs: list[str] = Field(default_factory=list, max_length=12)
    dependencies: list[str] = Field(default_factory=list, max_length=12)
    implementation_kind: Literal[
        "logic",
        "service",
        "adapter",
        "data",
        "workflow",
        "interface",
        "verification",
    ] = "logic"
    capability_families: list[str] = Field(default_factory=list, max_length=8)


class ProblemDecomposition(BaseModel):
    version: Literal["0.1"] = "0.1"
    normalized_goal: str = Field(min_length=5, max_length=5000)
    outcome: str = Field(min_length=5, max_length=1000)
    steps: list[DecompositionStep] = Field(min_length=1, max_length=24)
    invariants: list[str] = Field(default_factory=list, max_length=24)
    assumptions: list[str] = Field(default_factory=list, max_length=24)
    unresolved_questions: list[str] = Field(default_factory=list, max_length=16)
    requirement_refs: list[str] = Field(default_factory=list, max_length=64)
    capability_refs: list[str] = Field(default_factory=list, max_length=64)

    @model_validator(mode="after")
    def validate_dependency_graph(self) -> "ProblemDecomposition":
        ids = [step.id for step in self.steps]
        if len(ids) != len(set(ids)):
            raise ValueError("problem decomposition step ids must be unique")
        known = set(ids)
        for step in self.steps:
            unknown = set(step.dependencies) - known
            if unknown:
                raise ValueError(
                    f"problem decomposition has unknown dependencies: {sorted(unknown)}"
                )

        state: dict[str, int] = {step_id: 0 for step_id in ids}
        graph = {step.id: list(step.dependencies) for step in self.steps}

        def visit(step_id: str) -> None:
            if state[step_id] == 1:
                raise ValueError("problem decomposition dependency graph contains a cycle")
            if state[step_id] == 2:
                return
            state[step_id] = 1
            for dependency in graph[step_id]:
                visit(dependency)
            state[step_id] = 2

        for step_id in ids:
            visit(step_id)
        return self


class ProblemDecomposer(Protocol):
    def compile(
        self,
        *,
        goal: str,
        context: ContextGraph,
    ) -> ProblemDecomposition:
        ...


class DeterministicProblemDecomposer:
    """Conservative decomposition fallback used for tests and offline development."""

    def compile(
        self,
        *,
        goal: str,
        context: ContextGraph,
    ) -> ProblemDecomposition:
        requirements = [item.statement for item in context.requirements if item.priority != "low"]
        if not requirements:
            requirements = [goal.strip()]

        steps: list[DecompositionStep] = []
        for index, requirement in enumerate(requirements[:8], start=1):
            kind = "logic"
            text = requirement.lower()
            if any(term in text for term in ("api", "integration", "slack", "email", "calendar", "webhook")):
                kind = "adapter"
            elif any(term in text for term in ("database", "persist", "store", "record")):
                kind = "data"
            elif any(term in text for term in ("ui", "website", "dashboard", "interface")):
                kind = "interface"
            elif any(term in text for term in ("schedule", "event", "trigger", "workflow")):
                kind = "workflow"
            steps.append(
                DecompositionStep(
                    id=f"step-{index}",
                    objective=requirement,
                    responsibilities=[requirement],
                    outputs=[f"result-{index}"],
                    dependencies=[f"step-{index - 1}"] if index > 1 else [],
                    implementation_kind=kind,
                )
            )

        if not steps:
            steps = [
                DecompositionStep(
                    id="step-1",
                    objective=goal.strip(),
                    responsibilities=[goal.strip()],
                    outputs=["system-result"],
                )
            ]

        return ProblemDecomposition(
            normalized_goal=" ".join(goal.split()),
            outcome=goal.strip(),
            steps=steps,
            invariants=[
                "Generated behavior must remain within the supplied requirements and constraints.",
                "External integrations require verified contracts before production use.",
            ],
            assumptions=[str(item.get("assumption", "")).strip() for item in context.assumptions if item.get("assumption")],
            requirement_refs=[item.id for item in context.requirements],
            capability_refs=[item.id for item in context.capabilities],
        )

    @staticmethod
    def enrich_context(
        context: ContextGraph,
        decomposition: ProblemDecomposition,
    ) -> ContextGraph:
        source_id = "src_decomposition_" + hashlib.sha256(
            decomposition.normalized_goal.encode("utf-8")
        ).hexdigest()[:12]
        sources = list(context.sources)
        if not any(item.id == source_id for item in sources):
            from backend.context.models import Source
            sources.append(
                Source(
                    id=source_id,
                    kind="text",
                    name="Problem Decomposer",
                    content_hash=hashlib.sha256(
                        decomposition.model_dump_json().encode("utf-8")
                    ).hexdigest(),
                )
            )

        requirements = list(context.requirements)
        seen = {" ".join(item.statement.lower().split()) for item in requirements}
        for index, step in enumerate(decomposition.steps, start=1):
            statement = f"The system must implement the subproblem: {step.objective.strip()}"
            key = " ".join(statement.lower().split())
            if key in seen:
                continue
            requirements.append(
                Requirement(
                    id="req_decomp_" + hashlib.sha1(
                        f"{source_id}:{index}:{statement}".encode("utf-8")
                    ).hexdigest()[:10],
                    statement=statement,
                    priority="high",
                    provenance=[
                        Provenance(
                            source_id=source_id,
                            locator=f"decomposition:step-{index}",
                            quote=step.objective[:280],
                            confidence=0.84,
                        )
                    ],
                )
            )
            seen.add(key)

        entities = list(context.entities)
        entity_names = {" ".join(item.name.lower().split()) for item in entities}
        for step in decomposition.steps:
            for output in step.outputs:
                name = re.sub(r"[^A-Za-z0-9 ]+", " ", output).strip()
                if not name:
                    continue
                key = " ".join(name.lower().split())
                if key in entity_names:
                    continue
                entities.append(
                    ContextEntity(
                        id="entity_decomp_" + hashlib.sha1(
                            f"{source_id}:{key}".encode("utf-8")
                        ).hexdigest()[:10],
                        type="derived-output",
                        name=name,
                    )
                )
                entity_names.add(key)

        return context.model_copy(
            update={
                "sources": sources,
                "requirements": requirements,
                "entities": entities,
                "problem_decomposition": decomposition.model_dump(mode="json"),
            }
        )


class BedrockProblemDecomposer:
    """Model-backed problem decomposition for previously unseen software domains."""

    def __init__(self, model_id: str = "") -> None:
        try:
            from strands import Agent
            from strands.models import BedrockModel
        except ImportError as exc:
            raise RuntimeError(
                "AWS decomposition dependencies are missing. Install backend/requirements-aws.txt"
            ) from exc

        resolved_model = resolve_bedrock_model(model_id)
        self._agent = resilient_agent(
            resolved_model,
            system_prompt=(
                "You are Specloom's problem decomposition compiler. "
                "Turn an arbitrary software problem into a finite dependency-aware implementation graph. "
                "Preserve the supplied facts and constraints. Never invent providers, APIs, credentials, "
                "permissions, or external facts. Each step must describe an independently implementable "
                "responsibility and explicit inputs/outputs. Return only ProblemDecomposition JSON."
            ),
        )

    def compile(
        self,
        *,
        goal: str,
        context: ContextGraph,
    ) -> ProblemDecomposition:
        prompt = f"""
USER GOAL
{goal}

CONTEXT
{compact_context_json(context)}

DECOMPOSITION RULES
1. Normalize the user's actual outcome without changing its meaning.
2. Decompose the problem into a finite DAG-like set of independently implementable steps.
3. Capture the interfaces between steps using explicit inputs and outputs.
4. Mark whether each step is primarily logic, service, adapter, data, workflow, interface, or verification.
5. Preserve material security, reliability, compliance, and domain invariants from context.
6. Do not invent external providers, URLs, credentials, permissions, or undocumented capabilities.
7. Reuse requirement and capability IDs from context whenever they are relevant.
8. Prefer concrete implementation responsibilities over generic phrases such as "build the system".
9. Record unresolved questions instead of silently guessing when the goal genuinely lacks a required fact.
10. Keep the result bounded: at most 24 steps.

Return only JSON matching:
{json.dumps(ProblemDecomposition.model_json_schema(), indent=2)}
""".strip()

        result = self._agent(
            prompt,
            structured_output_model=ProblemDecomposition,
        )
        structured = getattr(result, "structured_output", result)
        if isinstance(structured, ProblemDecomposition):
            return structured
        if isinstance(structured, dict):
            return ProblemDecomposition.model_validate(structured)
        return ProblemDecomposition.model_validate(json.loads(str(structured)))


class ConfiguredProblemDecomposer:
    """Select model-backed decomposition for autonomous builds."""

    def __init__(self) -> None:
        requested = os.getenv("SPECL00M_DECOMPOSITION_MODE", "auto").lower()
        if requested not in {"auto", "bedrock", "deterministic", "off"}:
            requested = "auto"
        architect_mode = os.getenv("SPECL00M_ARCHITECT_MODE", "bedrock").lower()
        if requested == "auto":
            mode = "bedrock" if architect_mode == "bedrock" else "deterministic"
        else:
            mode = requested
        self.mode = mode
        self._impl: ProblemDecomposer | None = None

    @staticmethod
    def _mode_for_request(configured: str, autonomous: bool) -> str:
        # Respect an explicit mode. Autonomous execution should not silently
        # upgrade a deterministic/offline configuration into a model call.
        if configured in {"bedrock", "deterministic", "off"}:
            return configured
        return "bedrock" if autonomous else configured

    def _compiler(self, mode: str) -> ProblemDecomposer:
        if self._impl is not None and (
            (isinstance(self._impl, BedrockProblemDecomposer) and mode == "bedrock")
            or (isinstance(self._impl, DeterministicProblemDecomposer) and mode == "deterministic")
        ):
            return self._impl
        if mode == "bedrock":
            self._impl = BedrockProblemDecomposer()
        else:
            self._impl = DeterministicProblemDecomposer()
        return self._impl

    def compile(
        self,
        *,
        goal: str,
        context: ContextGraph,
        autonomous: bool = False,
    ) -> ProblemDecomposition | None:
        mode = self._mode_for_request(self.mode, autonomous)
        if mode == "off":
            return None
        if mode == "bedrock":
            from backend.bedrock_config import (
                bedrock_quota_recently_exhausted,
                is_bedrock_quota_error,
                mark_bedrock_quota_exhausted,
            )

            if bedrock_quota_recently_exhausted():
                return self._compiler("deterministic").compile(goal=goal, context=context)
            try:
                return self._compiler(mode).compile(goal=goal, context=context)
            except Exception as exc:
                if not is_bedrock_quota_error(exc):
                    raise
                mark_bedrock_quota_exhausted()
                return self._compiler("deterministic").compile(goal=goal, context=context)
        return self._compiler(mode).compile(goal=goal, context=context)

    @staticmethod
    def enrich_context(
        context: ContextGraph,
        decomposition: ProblemDecomposition,
    ) -> ContextGraph:
        return DeterministicProblemDecomposer.enrich_context(context, decomposition)
