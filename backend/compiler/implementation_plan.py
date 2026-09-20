from __future__ import annotations

import hashlib
import json
import os
from typing import Literal, Protocol

from pydantic import BaseModel, Field, model_validator

from backend.bedrock_config import resolve_bedrock_model
from backend.context.models import ContextGraph
from .decomposition import ProblemDecomposition


ImplementationKind = Literal[
    "logic",
    "service",
    "adapter",
    "data",
    "workflow",
    "interface",
    "verification",
]


class ImplementationTarget(BaseModel):
    step_id: str = Field(min_length=1)
    path: str = Field(min_length=1)
    symbol: str = Field(min_length=1)
    purpose: str = Field(min_length=5, max_length=500)
    implementation_kind: ImplementationKind = "logic"
    dependency_steps: list[str] = Field(default_factory=list, max_length=12)
    acceptance_criteria: list[str] = Field(default_factory=list, max_length=24)


class ImplementationPlan(BaseModel):
    version: Literal["0.1"] = "0.1"
    goal: str = Field(min_length=5, max_length=5000)
    targets: list[ImplementationTarget] = Field(min_length=1, max_length=48)
    test_paths: list[str] = Field(default_factory=lambda: [
        "generated/repository/tests/test_acceptance.py",
    ], max_length=12)
    dependency_paths: list[str] = Field(default_factory=list, max_length=24)
    unresolved_steps: list[str] = Field(default_factory=list, max_length=24)
    assumptions: list[str] = Field(default_factory=list, max_length=24)

    @model_validator(mode="after")
    def validate_targets(self) -> "ImplementationPlan":
        step_ids = {target.step_id for target in self.targets}
        for target in self.targets:
            unknown = set(target.dependency_steps) - step_ids
            if unknown:
                raise ValueError(
                    "implementation plan target references unknown step dependencies: "
                    + ", ".join(sorted(unknown))
                )
            if target.step_id in target.dependency_steps:
                raise ValueError(
                    f"implementation plan target cannot depend on itself: {target.step_id}"
                )
        return self


class ImplementationPlanner(Protocol):
    def compile(
        self,
        *,
        goal: str,
        context: ContextGraph,
        decomposition: ProblemDecomposition,
    ) -> ImplementationPlan:
        ...


class DeterministicImplementationPlanner:
    """Lower decomposition responsibilities into explicit generated-code targets."""

    _PATHS = {
        "logic": ("generated/repository/app/implementation.py", "handle"),
        "service": ("generated/repository/app/implementation.py", "handle"),
        "adapter": ("generated/repository/app/implementation.py", "handle"),
        "data": ("generated/repository/app/domain.py", "domain_model"),
        "workflow": ("generated/repository/app/implementation.py", "handle"),
        "interface": ("generated/repository/app/api.py", "router"),
        "verification": ("generated/repository/tests/test_acceptance.py", "test_generated_behavior"),
    }

    def compile(
        self,
        *,
        goal: str,
        context: ContextGraph,
        decomposition: ProblemDecomposition,
    ) -> ImplementationPlan:
        targets: list[ImplementationTarget] = []
        known = {step.id for step in decomposition.steps}

        for step in decomposition.steps:
            path, symbol = self._PATHS[step.implementation_kind]
            targets.append(
                ImplementationTarget(
                    step_id=step.id,
                    path=path,
                    symbol=symbol,
                    purpose=step.objective,
                    implementation_kind=step.implementation_kind,
                    dependency_steps=[
                        dependency
                        for dependency in step.dependencies
                        if dependency in known
                    ],
                )
            )

        unresolved = [
            step.id
            for step in decomposition.steps
            if not step.objective.strip()
        ]
        assumptions = [
            str(item.get("assumption"))
            for item in context.assumptions
            if item.get("assumption")
        ]
        return ImplementationPlan(
            goal=goal.strip(),
            targets=targets,
            dependency_paths=sorted({
                target.path
                for target in targets
                if target.path.endswith((".py", ".tsx"))
            }),
            unresolved_steps=unresolved,
            assumptions=assumptions,
        )


class BedrockImplementationPlanner:
    """Use a model to refine target symbols while preserving deterministic boundaries."""

    def __init__(self, model_id: str = "") -> None:
        try:
            from strands import Agent
            from strands.models import BedrockModel
        except ImportError as exc:
            raise RuntimeError(
                "AWS implementation-planner dependencies are missing. "
                "Install backend/requirements-aws.txt"
            ) from exc

        resolved = resolve_bedrock_model(model_id)
        self._agent = Agent(
            model=BedrockModel(model_id=resolved),
            system_prompt=(
                "You are Specloom's implementation planning compiler. "
                "Refine a deterministic implementation plan for a generated repository. "
                "Never invent dependencies, APIs, credentials, providers, or files outside "
                "the supplied generated extension boundary. Every decomposition step must "
                "have at least one target. Return only ImplementationPlan JSON."
            ),
        )

    def compile(
        self,
        *,
        goal: str,
        context: ContextGraph,
        decomposition: ProblemDecomposition,
    ) -> ImplementationPlan:
        baseline = DeterministicImplementationPlanner().compile(
            goal=goal,
            context=context,
            decomposition=decomposition,
        )
        prompt = f"""
USER GOAL
{goal}

CONTEXT
{context.model_dump_json(indent=2)}

PROBLEM DECOMPOSITION
{decomposition.model_dump_json(indent=2)}

DETERMINISTIC BASELINE
{baseline.model_dump_json(indent=2)}

PLANNING RULES
- Preserve every decomposition step.
- Use only these generated extension paths:
  generated/repository/app/implementation.py
  generated/repository/app/domain.py
  generated/repository/app/api.py
  generated/repository/web/src/App.tsx
  generated/repository/tests/test_acceptance.py
- Prefer existing symbols such as handle/router/domain_model unless a concrete reason
  requires a more specific symbol.
- Every target must remain attributable to exactly one decomposition step.
- Dependency steps must reference existing decomposition IDs.
- Acceptance criteria must come from supplied context; do not invent rules.
- Never add third-party dependencies in this planning stage.
- Never invent external integrations or provider details.

Return only JSON matching:
{json.dumps(ImplementationPlan.model_json_schema(), indent=2)}
""".strip()
        result = self._agent(prompt, structured_output_model=ImplementationPlan)
        structured = getattr(result, "structured_output", result)
        if isinstance(structured, ImplementationPlan):
            candidate = structured
        elif isinstance(structured, dict):
            candidate = ImplementationPlan.model_validate(structured)
        else:
            candidate = ImplementationPlan.model_validate(json.loads(str(structured)))

        allowed_paths = {
            "generated/repository/app/implementation.py",
            "generated/repository/app/domain.py",
            "generated/repository/app/api.py",
            "generated/repository/web/src/App.tsx",
            "generated/repository/tests/test_acceptance.py",
        }
        known_steps = {step.id for step in decomposition.steps}
        targets: list[ImplementationTarget] = []
        for target in candidate.targets:
            if target.step_id not in known_steps or target.path not in allowed_paths:
                continue
            targets.append(
                target.model_copy(update={
                    "dependency_steps": [
                        item
                        for item in target.dependency_steps
                        if item in known_steps and item != target.step_id
                    ]
                })
            )

        covered = {target.step_id for target in targets}
        targets.extend(
            baseline_target
            for baseline_target in baseline.targets
            if baseline_target.step_id not in covered
        )

        deduped: dict[tuple[str, str, str], ImplementationTarget] = {}
        for target in targets:
            deduped[(target.step_id, target.path, target.symbol)] = target

        final_targets = list(deduped.values())
        return candidate.model_copy(
            update={
                "goal": goal.strip(),
                "targets": final_targets,
                "unresolved_steps": sorted(
                    set(candidate.unresolved_steps)
                    | (known_steps - {target.step_id for target in final_targets})
                ),
            }
        )


class ConfiguredImplementationPlanner:
    """Select a deterministic or Bedrock implementation-plan compiler."""

    def __init__(self) -> None:
        requested = os.getenv("SPECL00M_IMPLEMENTATION_PLAN_MODE", "auto").lower()
        if requested not in {"auto", "bedrock", "deterministic", "off"}:
            requested = "auto"
        architect_mode = os.getenv("SPECL00M_ARCHITECT_MODE", "bedrock").lower()
        if requested == "auto":
            self.mode = "bedrock" if architect_mode == "bedrock" else "deterministic"
        else:
            self.mode = requested
        self._impl: ImplementationPlanner | None = None

    @staticmethod
    def _mode_for_request(configured: str, autonomous: bool) -> str:
        if configured in {"bedrock", "deterministic", "off"}:
            return "bedrock" if autonomous and configured == "deterministic" else configured
        return "bedrock" if autonomous else configured

    def _planner(self, mode: str) -> ImplementationPlanner:
        if mode == "bedrock" and isinstance(self._impl, BedrockImplementationPlanner):
            return self._impl
        if mode == "deterministic" and isinstance(self._impl, DeterministicImplementationPlanner):
            return self._impl
        self._impl = (
            BedrockImplementationPlanner()
            if mode == "bedrock"
            else DeterministicImplementationPlanner()
        )
        return self._impl

    def compile(
        self,
        *,
        goal: str,
        context: ContextGraph,
        decomposition: ProblemDecomposition,
        autonomous: bool = False,
    ) -> ImplementationPlan | None:
        mode = self._mode_for_request(self.mode, autonomous)
        if mode == "off":
            return None
        return self._planner(mode).compile(
            goal=goal,
            context=context,
            decomposition=decomposition,
        )


def implementation_plan_id(plan: ImplementationPlan) -> str:
    payload = plan.model_dump_json()
    return "implplan_" + hashlib.sha256(payload.encode("utf-8")).hexdigest()[:24]
