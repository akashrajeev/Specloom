from __future__ import annotations

import json
import os
import re
from typing import Any, Protocol

from pydantic import BaseModel, Field

from backend.context.models import ContextGraph
from .system_ir import SystemIR


class GeneratedAcceptanceCase(BaseModel):
    id: str
    criterion_id: str
    input: Any
    expected: Any
    rationale: str = ""


class GeneratedAcceptanceSet(BaseModel):
    cases: list[GeneratedAcceptanceCase] = Field(default_factory=list)
    uncovered_criteria: list[str] = Field(default_factory=list)


class AcceptanceReviewFinding(BaseModel):
    severity: str = "warning"
    criterion_id: str | None = None
    message: str


class AcceptanceReview(BaseModel):
    status: str
    approved: bool
    summary: str
    findings: list[AcceptanceReviewFinding] = Field(default_factory=list)


class SemanticAcceptanceSynthesizer(Protocol):
    def synthesize(
        self,
        *,
        goal: str,
        context: ContextGraph,
        system_ir: SystemIR,
        feedback: str = "",
        criterion_ids: set[str] | None = None,
    ) -> GeneratedAcceptanceSet:
        ...


class SemanticAcceptanceReviewer(Protocol):
    def review(
        self,
        *,
        goal: str,
        context: ContextGraph,
        system_ir: SystemIR,
        cases: GeneratedAcceptanceSet,
        criterion_ids: set[str] | None = None,
    ) -> AcceptanceReview:
        ...


class BedrockSemanticAcceptanceSynthesizer:
    """Generate black-box acceptance hypotheses without modifying implementation artifacts."""

    def __init__(self, model_id: str = "") -> None:
        try:
            from strands import Agent
            from strands.models import BedrockModel
        except ImportError as exc:
            raise RuntimeError(
                "AWS semantic acceptance dependencies are missing. "
                "Install backend/requirements-aws.txt"
            ) from exc

        resolved = model_id or os.getenv(
            "SPECL00M_BEDROCK_MODEL_ID",
            "amazon.nova-lite-v1:0",
        )
        self._agent = Agent(
            model=BedrockModel(model_id=resolved),
            system_prompt=(
                "You are Specloom's semantic acceptance compiler. "
                "Generate black-box acceptance hypotheses for the canonical SystemIR. "
                "Cover every required requirement/constraint criterion. "
                "Inputs must be deterministic and side-effect free. "
                "Expected outputs must be concrete JSON values. "
                "Do not inspect or modify implementation code. "
                "Return only GeneratedAcceptanceSet JSON."
            ),
        )

    def synthesize(
        self,
        *,
        goal: str,
        context: ContextGraph,
        system_ir: SystemIR,
    ) -> GeneratedAcceptanceSet:
        criteria = [
            item.model_dump(mode="json")
            for item in system_ir.acceptance_criteria
            if (
                item.required
                and item.source in {"requirement", "constraint"}
                and (criterion_ids is None or item.id in criterion_ids)
            )
        ]
        prompt = (
            "Generate executable black-box acceptance cases for the requested system.\n\n"
            f"GOAL:\n{goal}\n\n"
            f"CONTEXT:\n{context.model_dump_json(indent=2)}\n\n"
            f"REQUIRED CRITERIA:\n{json.dumps(criteria, indent=2)}\n\n"
            "Produce at least one case per criterion whenever its semantics permit. "
            "Do not invent external APIs, secrets, current facts, or hidden state. "
            "Prefer minimal cases that distinguish correct from incorrect behavior. "
            + (f"\nPRIOR REVIEW FEEDBACK:\n{feedback}\n" if feedback else "")
        )
        result = self._agent(prompt, structured_output_model=GeneratedAcceptanceSet)
        structured = getattr(result, "structured_output", result)
        if isinstance(structured, GeneratedAcceptanceSet):
            generated = structured
        elif isinstance(structured, dict):
            generated = GeneratedAcceptanceSet.model_validate(structured)
        else:
            generated = GeneratedAcceptanceSet.model_validate(json.loads(str(structured)))

        required_ids = {item["id"] for item in criteria}
        covered = {item.criterion_id for item in generated.cases}
        generated.uncovered_criteria = sorted(required_ids - covered)
        return generated


class BedrockSemanticAcceptanceReviewer:
    """Adversarially review model-generated acceptance hypotheses before promotion."""

    def __init__(self, model_id: str = "") -> None:
        try:
            from strands import Agent
            from strands.models import BedrockModel
        except ImportError as exc:
            raise RuntimeError(
                "AWS semantic acceptance dependencies are missing. "
                "Install backend/requirements-aws.txt"
            ) from exc

        resolved = model_id or os.getenv(
            "SPECL00M_BEDROCK_MODEL_ID",
            "amazon.nova-lite-v1:0",
        )
        self._agent = Agent(
            model=BedrockModel(model_id=resolved),
            system_prompt=(
                "You are Specloom's adversarial semantic acceptance reviewer. "
                "Review generated black-box acceptance hypotheses against the goal, "
                "context, and canonical acceptance criteria. Reject cases that are "
                "circular, ambiguous, impossible to execute deterministically, or "
                "unsupported by evidence. Require coverage of every required criterion. "
                "Return only AcceptanceReview JSON."
            ),
        )

    def review(
        self,
        *,
        goal: str,
        context: ContextGraph,
        system_ir: SystemIR,
        cases: GeneratedAcceptanceSet,
    ) -> AcceptanceReview:
        criteria = [
            item.model_dump(mode="json")
            for item in system_ir.acceptance_criteria
            if (
                item.required
                and item.source in {"requirement", "constraint"}
                and (criterion_ids is None or item.id in criterion_ids)
            )
        ]
        prompt = (
            "Review the following generated acceptance hypotheses.\n\n"
            f"GOAL:\n{goal}\n\n"
            f"CONTEXT:\n{context.model_dump_json(indent=2)}\n\n"
            f"REQUIRED CRITERIA:\n{json.dumps(criteria, indent=2)}\n\n"
            f"CASES:\n{cases.model_dump_json(indent=2)}\n\n"
            "Approve only when the cases collectively cover every required criterion "
            "and each expected result is concrete enough for deterministic execution."
        )
        result = self._agent(prompt, structured_output_model=AcceptanceReview)
        structured = getattr(result, "structured_output", result)
        if isinstance(structured, AcceptanceReview):
            return structured
        if isinstance(structured, dict):
            return AcceptanceReview.model_validate(structured)
        return AcceptanceReview.model_validate(json.loads(str(structured)))


class SemanticAcceptanceEngine:
    """Bounded synthesize -> validate -> adversarial review -> revise loop."""

    def __init__(
        self,
        synthesizer: SemanticAcceptanceSynthesizer,
        reviewer: SemanticAcceptanceReviewer,
        *,
        max_attempts: int = 2,
    ) -> None:
        self.synthesizer = synthesizer
        self.reviewer = reviewer
        self.max_attempts = max(1, min(max_attempts, 3))

    def compile(
        self,
        *,
        goal: str,
        context: ContextGraph,
        system_ir: SystemIR,
        criterion_ids: set[str] | None = None,
    ) -> tuple[GeneratedAcceptanceSet | None, AcceptanceReview | None, list[str]]:
        feedback: list[str] = []
        last_cases: GeneratedAcceptanceSet | None = None
        last_review: AcceptanceReview | None = None

        for _attempt in range(self.max_attempts):
            cases = self.synthesizer.synthesize(
                goal=goal,
                context=context,
                system_ir=system_ir,
                feedback="\n".join(feedback),
                criterion_ids=criterion_ids,
            )
            last_cases = cases
            validation_errors = validate_generated_cases(
                cases,
                system_ir,
                criterion_ids=criterion_ids,
            )
            if validation_errors:
                feedback = [
                    "Generated acceptance cases failed deterministic coverage validation:",
                    *validation_errors,
                ]
                continue

            review = self.reviewer.review(
                goal=goal,
                context=context,
                system_ir=system_ir,
                cases=cases,
                criterion_ids=criterion_ids,
            )
            last_review = review
            if review.approved:
                return cases, review, []

            findings = [
                item.message
                for item in review.findings
                if item.severity in {"warning", "blocking"}
            ]
            feedback = [
                "Adversarial acceptance review rejected the current case set.",
                *(findings or [review.summary]),
            ]

        return (
            last_cases,
            last_review,
            feedback
            or ["semantic acceptance synthesis exhausted its bounded attempts"],
        )


def render_synthesized_acceptance(cases: GeneratedAcceptanceSet) -> str:
    """Render verifier-owned Python checks for model-generated acceptance hypotheses."""
    payload = json.dumps(
        [item.model_dump(mode="json") for item in cases.cases],
        indent=2,
        sort_keys=True,
    )
    return f'''from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.implementation import handle


CASES = {payload}


def _matches(actual, expected):
    if isinstance(expected, dict) and isinstance(actual, dict):
        return all(actual.get(key) == value for key, value in expected.items())
    return actual == expected


for case in CASES:
    result = handle(
        case["input"],
        {{"status": "completed", "system_goal": "synthesized semantic acceptance"}},
    )
    assert _matches(result, case["expected"]), (
        f'Acceptance hypothesis {{case["id"]}} failed: '
        f'expected={{case["expected"]!r}} actual={{result!r}}'
    )

print("SPECL00M_SYNTHESIZED_ACCEPTANCE:PASS")
'''


def validate_generated_cases(
    cases: GeneratedAcceptanceSet,
    system_ir: SystemIR,
    criterion_ids: set[str] | None = None,
) -> list[str]:
    required_ids = {
        item.id
        for item in system_ir.acceptance_criteria
        if (
            item.required
            and item.source in {"requirement", "constraint"}
            and (criterion_ids is None or item.id in criterion_ids)
        )
    }
    errors = list(cases.uncovered_criteria)
    covered = {item.criterion_id for item in cases.cases}
    errors.extend(sorted(required_ids - covered))

    seen: set[str] = set()
    for case in cases.cases:
        if case.id in seen:
            errors.append(f"duplicate generated acceptance case: {case.id}")
        seen.add(case.id)
        if not re.fullmatch(r"[A-Za-z0-9_.:-]{1,128}", case.criterion_id):
            errors.append(f"invalid acceptance criterion id: {case.criterion_id}")
    return sorted(set(errors))
