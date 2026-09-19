from __future__ import annotations

import json
from typing import Any

from pydantic import BaseModel, Field

from backend.context.models import ContextGraph, ContextExample
from .models import Artifact, CompilerDiagnostic
from .system_ir import SystemIR


class AcceptanceCase(BaseModel):
    id: str
    input: Any
    expected: Any
    source_id: str | None = None
    verification: str = "example"


class AcceptanceManifest(BaseModel):
    version: str = "0.1"
    system_id: str
    cases: list[AcceptanceCase] = Field(default_factory=list)
    unverified_criteria: list[str] = Field(default_factory=list)


class IndependentAcceptanceCompiler:
    """Compile user-supplied examples into verifier-owned executable tests."""

    def compile(
        self,
        system: SystemIR,
        context: ContextGraph,
    ) -> tuple[Artifact, list[CompilerDiagnostic], AcceptanceManifest]:
        cases = [
            AcceptanceCase(
                id=f"example-{example.id}",
                input=example.input,
                expected=example.expected,
                source_id=(
                    example.provenance[0].source_id
                    if example.provenance
                    else None
                ),
            )
            for example in context.examples
        ]

        verified_requirement_ids = {
            req.id
            for example in context.examples
            for req in system.acceptance_criteria
            if example.provenance
            and any(
                provenance.source_id
                in {item.source_id for item in example.provenance}
                for provenance in req_to_provenance(req, context)
            )
        }
        unverified = [
            criterion.statement
            for criterion in system.acceptance_criteria
            if criterion.required and criterion.id not in verified_requirement_ids
        ]

        manifest = AcceptanceManifest(
            system_id=system.id,
            cases=cases,
            unverified_criteria=unverified,
        )
        content = json.dumps(
            manifest.model_dump(mode="json"),
            indent=2,
            sort_keys=True,
        ) + "
"

        test_content = self._render_test(manifest)
        return (
            Artifact(
                path="generated/repository/tests/independent_acceptance.py",
                kind="test",
                content=test_content,
                generated_from=[system.id],
            ),
            [
                CompilerDiagnostic(
                    severity="warning",
                    code="acceptance-criteria-unverified",
                    message=(
                        f"{len(unverified)} required acceptance criterion/criteria "
                        "lack directly mapped user examples and remain unverified."
                    ),
                )
            ] if unverified else [],
            manifest,
        )

    @staticmethod
    def _render_test(manifest: AcceptanceManifest) -> str:
        cases = json.dumps(
            [item.model_dump(mode="json") for item in manifest.cases],
            indent=2,
            sort_keys=True,
        )
        return f'''from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.implementation import handle


CASES = {cases}


def _matches(actual, expected):
    if isinstance(expected, dict) and isinstance(actual, dict):
        return all(actual.get(key) == value for key, value in expected.items())
    return actual == expected


for case in CASES:
    result = handle(
        case["input"],
        {{"status": "completed", "system_goal": "independent acceptance"}},
    )
    assert _matches(result, case["expected"]), (
        f'Acceptance case {{case["id"]}} failed: '
        f'expected={{case["expected"]!r}} actual={{result!r}}'
    )

print("SPECl00M_INDEPENDENT_ACCEPTANCE:PASS")
'''


def req_to_provenance(req, context: ContextGraph):
    # Requirements currently carry provenance directly; this helper keeps
    # acceptance compilation resilient while the SystemIR becomes richer.
    matching = [
        requirement
        for requirement in context.requirements
        if requirement.id in req.requirement_refs
    ]
    return [
        provenance
        for requirement in matching
        for provenance in requirement.provenance
    ]
