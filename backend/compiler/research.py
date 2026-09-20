from __future__ import annotations

import json
import os
import re
from typing import Literal

from pydantic import BaseModel, Field

from backend.context.gaps import Gap
from backend.context.models import ContextGraph


class ResearchTask(BaseModel):
    id: str
    question: str
    purpose: str
    capability_family: str | None = None
    source_types: list[Literal["user_context", "url", "github", "api_spec", "readonly_mcp"]]
    required: bool = False


class ResearchPlan(BaseModel):
    version: Literal["0.1"] = "0.1"
    goal: str
    tasks: list[ResearchTask] = Field(default_factory=list)
    unresolved_gaps: list[str] = Field(default_factory=list)


class ResearchPlanner:
    def plan(
        self,
        goal: str,
        context: ContextGraph,
        gaps: list[Gap] | None = None,
    ) -> ResearchPlan:
        gaps = gaps or []
        tasks: list[ResearchTask] = []
        lowered = goal.lower()

        synthesized = [
            item
            for item in context.capabilities
            if item.kind == "synthesized"
        ]
        for capability in synthesized:
            family = (
                next(iter(capability.tags), None)
                or capability.name
                or capability.id
            )
            task_id = (
                "research-contract-"
                + re.sub(r"[^a-z0-9-]+", "-", str(family).lower()).strip("-")
            )
            tasks.append(
                ResearchTask(
                    id=task_id,
                    question=(
                        f"What official API specification, public contract, or trusted MCP "
                        f"interface can provide the {family} capability required by this goal?"
                    ),
                    purpose=(
                        "Replace the provider-neutral synthesized capability with a "
                        "verified concrete contract before implementation or production."
                    ),
                    source_types=["api_spec", "url", "readonly_mcp"],
                    required=True,
                    capability_family=str(family),
                )
            )

        if any(term in lowered for term in (
            "api", "integrat", "webhook", "oauth", "slack",
            "email", "calendar", "jira", "linear", "stripe", "twilio",
        )):
            tasks.append(
                ResearchTask(
                    id="research-integration-contracts",
                    question="Which official API or MCP contracts are required for the external integrations named by the goal?",
                    purpose="Resolve provider-specific interface, authentication, and schema details before implementation.",
                    source_types=["api_spec", "url", "readonly_mcp"],
                    required=True,
                )
            )

        if any(term in lowered for term in (
            "policy", "compliance", "regulated", "audit", "security", "privacy",
        )):
            tasks.append(
                ResearchTask(
                    id="research-domain-constraints",
                    question="What authoritative domain, security, compliance, or policy constraints govern this system?",
                    purpose="Prevent implementation choices that conflict with explicit domain constraints.",
                    source_types=["user_context", "url", "readonly_mcp"],
                    required=True,
                )
            )

        if any(term in lowered for term in (
            "company", "organization", "internal", "existing",
            "legacy", "repo", "repository", "codebase",
        )):
            tasks.append(
                ResearchTask(
                    id="research-existing-system",
                    question="What existing code, schemas, conventions, or APIs must the generated system interoperate with?",
                    purpose="Reuse and preserve existing system boundaries rather than inventing replacements.",
                    source_types=["github", "api_spec", "user_context"],
                    required=True,
                )
            )

        for gap in gaps:
            if gap.category in {"ambiguity", "capability", "goal"}:
                tasks.append(
                    ResearchTask(
                        id=f"research-gap-{gap.id}",
                        question=gap.question,
                        purpose="Resolve a blocking compiler gap before architecture or deployment.",
                        source_types=["user_context", "url", "readonly_mcp"],
                        required=gap.severity == "blocking",
                    )
                )

        # If there is no targeted research task, preserve a generic traceable
        # discovery task instead of pretending the problem needs no research.
        if not tasks:
            tasks.append(
                ResearchTask(
                    id="research-domain-discovery",
                    question="What domain facts, existing interfaces, or acceptance examples are necessary to implement this problem correctly?",
                    purpose="Check whether the natural-language goal omits material external context.",
                    source_types=["user_context", "url", "readonly_mcp"],
                    required=False,
                )
            )

        deduped: dict[str, ResearchTask] = {}
        for task in tasks:
            deduped[task.id] = task

        return ResearchPlan(
            goal=goal,
            tasks=list(deduped.values()),
            unresolved_gaps=[gap.id for gap in gaps if gap.severity == "blocking"],
        )


class BedrockResearchPlanner(ResearchPlanner):
    def __init__(self, model_id: str = "") -> None:
        try:
            from strands import Agent
            from strands.models import BedrockModel
        except ImportError as exc:
            raise RuntimeError(
                "AWS architect dependencies are missing. Install backend/requirements-aws.txt"
            ) from exc

        resolved_model = model_id or os.getenv(
            "SPECL00M_BEDROCK_MODEL_ID",
            "amazon.nova-lite-v1:0",
        )
        self._agent = Agent(
            model=BedrockModel(model_id=resolved_model),
            system_prompt=(
                "You are Specloom's research planner. Identify only the external "
                "facts or contracts needed to implement a software problem. Do not "
                "invent sources or claim research was completed. Return only ResearchPlan JSON."
            ),
        )

    def plan(
        self,
        goal: str,
        context: ContextGraph,
        gaps: list[Gap] | None = None,
    ) -> ResearchPlan:
        deterministic = super().plan(goal, context, gaps)
        prompt = f"""
USER GOAL
{goal}

CONTEXT
{context.model_dump_json(indent=2)}

KNOWN GAPS
{json.dumps([gap.__dict__ for gap in gaps or []], indent=2)}

Use the deterministic research plan as a baseline, then remove irrelevant tasks
and refine the questions. Keep the list concrete and small. Do not claim that
research has already been performed and do not invent a URL, API, provider,
credential, policy, or source.

BASELINE
{deterministic.model_dump_json(indent=2)}

Return only JSON matching:
{json.dumps(ResearchPlan.model_json_schema(), indent=2)}
""".strip()
        result = self._agent(
            prompt,
            structured_output_model=ResearchPlan,
        )
        structured = getattr(result, "structured_output", result)
        if isinstance(structured, ResearchPlan):
            return structured
        if isinstance(structured, dict):
            return ResearchPlan.model_validate(structured)
        return ResearchPlan.model_validate(json.loads(str(structured)))


def configured_research_planner() -> ResearchPlanner:
    mode = os.getenv("SPECL00M_RESEARCH_MODE", "auto").lower()
    if mode == "bedrock" or (
        mode == "auto"
        and os.getenv("SPECL00M_ARCHITECT_MODE", "bedrock").lower() == "bedrock"
    ):
        return BedrockResearchPlanner()
    return ResearchPlanner()


class ResearchEvidence(BaseModel):
    task_id: str
    summary: str
    facts: list[str] = Field(default_factory=list)
    source_refs: list[str] = Field(default_factory=list)
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)


class ResearchExecutionResult(BaseModel):
    status: Literal["completed", "partial", "failed"]
    evidence: list[ResearchEvidence] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)


class BedrockResearchExecutor:
    """Fulfil research tasks with read-only MCP tools and structured evidence."""

    def __init__(self, model_id: str = "") -> None:
        try:
            from strands import Agent
            from strands.models import BedrockModel
        except ImportError as exc:
            raise RuntimeError(
                "AWS architect dependencies are missing. Install backend/requirements-aws.txt"
            ) from exc
        resolved = model_id or os.getenv(
            "SPECL00M_BEDROCK_MODEL_ID",
            "amazon.nova-lite-v1:0",
        )
        self._Agent = Agent
        self._BedrockModel = BedrockModel
        self._model_id = resolved

    def execute(
        self,
        plan: ResearchPlan,
        context: ContextGraph,
        *,
        mcp_servers: list[str] | None = None,
    ) -> ResearchExecutionResult:
        from backend.tools.mcp import load_readonly_clients
        clients = load_readonly_clients(mcp_servers or [])

        evidence: list[ResearchEvidence] = []
        errors: list[str] = []
        for task in plan.tasks:
            if not task.required and not clients:
                continue
            try:
                agent = self._Agent(
                    model=self._BedrockModel(model_id=self._model_id),
                    system_prompt=(
                        "You are Specloom's read-only research executor. "
                        "Use only the supplied read-only MCP tools. "
                        "Do not perform writes, side effects, purchases, messages, or changes. "
                        "Do not invent sources or facts. Distinguish retrieved facts from uncertainty. "
                        "Return only ResearchEvidence JSON."
                    ),
                    tools=clients,
                )
                prompt = (
                    "Research task:\n"
                    + task.question
                    + "\n\nPurpose:\n"
                    + task.purpose
                    + "\n\nExisting context:\n"
                    + context.model_dump_json(indent=2)
                    + "\n\nReturn only JSON matching:\n"
                    + json.dumps(ResearchEvidence.model_json_schema(), indent=2)
                )
                result = agent(prompt, structured_output_model=ResearchEvidence)
                structured = getattr(result, "structured_output", result)
                item = (
                    structured
                    if isinstance(structured, ResearchEvidence)
                    else ResearchEvidence.model_validate(structured)
                    if isinstance(structured, dict)
                    else ResearchEvidence.model_validate(json.loads(str(structured)))
                )
                evidence.append(item.model_copy(update={"task_id": task.id}))
            except Exception as exc:
                errors.append(f"{task.id}: {exc}")

        status: Literal["completed", "partial", "failed"]
        if evidence and not errors:
            status = "completed"
        elif evidence:
            status = "partial"
        else:
            status = "failed"

        return ResearchExecutionResult(
            status=status,
            evidence=evidence,
            errors=errors,
        )


def apply_research_evidence(
    context: ContextGraph,
    result: ResearchExecutionResult,
) -> ContextGraph:
    existing = list(context.research_evidence)
    known = {
        str(item.get("task_id"))
        for item in existing
        if isinstance(item, dict)
    }
    additions = [
        evidence.model_dump(mode="json")
        for evidence in result.evidence
        if evidence.task_id not in known
    ]
    return context.model_copy(
        update={"research_evidence": [*existing, *additions]}
    )
