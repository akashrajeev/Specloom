from __future__ import annotations

import ast
import json
import os
import re
from typing import Any, Protocol

from pydantic import BaseModel, Field

from backend.context.models import ContextGraph
from backend.workflow.models import WorkflowIR

from .models import Artifact, CompilerDiagnostic
from .system_ir import SystemIR


class ImplementationPatch(BaseModel):
    path: str
    content: str
    rationale: str = ""
    step_ids: list[str] = Field(default_factory=list)


class ImplementationPatchSet(BaseModel):
    patches: list[ImplementationPatch] = Field(default_factory=list)
    summary: str = ""


class ImplementationCompiler(Protocol):
    def compile(
        self,
        *,
        goal: str,
        context: ContextGraph,
        system_ir: SystemIR,
        workflow: WorkflowIR,
        artifacts: list[Artifact],
        feedback: list[str] | None = None,
    ) -> ImplementationPatchSet:
        ...


class DeterministicImplementationCompiler:
    """Conservative implementation layer used for local/showcase operation."""

    def compile(
        self,
        *,
        goal: str,
        context: ContextGraph,
        system_ir: SystemIR,
        workflow: WorkflowIR,
        artifacts: list[Artifact],
        feedback: list[str] | None = None,
    ) -> ImplementationPatchSet:
        _ = feedback
        return ImplementationPatchSet(
            summary=(
                "Deterministic implementation scaffold. "
                "Enable the Bedrock implementation compiler for domain-specific code generation."
            )
        )


class BedrockImplementationCompiler:
    """Generate the domain-specific implementation layer from the canonical SystemIR."""

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
                "You are Specloom's implementation compiler. "
                "Implement only the domain-specific generated application layer. "
                "Do not modify canonical specifications, workflow runtime, security policy, "
                "or external capability contracts. Never embed secrets or invent APIs. "
                "Return only ImplementationPatchSet JSON."
            ),
        )

    def compile(
        self,
        *,
        goal: str,
        context: ContextGraph,
        system_ir: SystemIR,
        workflow: WorkflowIR,
        artifacts: list[Artifact],
        feedback: list[str] | None = None,
    ) -> ImplementationPatchSet:
        mutable = [
            {
                "path": item.path,
                "content": item.content,
                "kind": item.kind,
            }
            for item in artifacts
            if item.path in {
                "generated/repository/app/implementation.py",
                "generated/repository/app/api.py",
                "generated/repository/app/domain.py",
                "generated/repository/web/src/App.tsx",
                "generated/repository/tests/test_acceptance.py",
            }
        ]

        prompt = f"""
USER GOAL
{goal}

SYSTEM IR
{system_ir.model_dump_json(indent=2)}

WORKFLOW IR
{workflow.model_dump_json(indent=2)}

CONTEXT
{context.model_dump_json(indent=2)}

CURRENT EXTENSION FILES
{json.dumps(mutable, indent=2)}

PREVIOUS SYNTHESIS FEEDBACK
{json.dumps(feedback or [], indent=2)}

IMPLEMENTATION CONTRACT
- Implement business/domain behavior in generated/repository/app/implementation.py.
- You may refine generated/repository/app/domain.py and generated/repository/app/api.py.
- You may refine generated/repository/web/src/App.tsx for the user-facing behavior.
- The implementation module must expose:
    def handle(payload: dict, execution: dict) -> dict
- Use only dependencies already declared in the generated repository.
- Do not make network calls.
- Do not read credentials or environment secrets.
- Do not modify system-ir.json, workflow-ir.json, runtime.py, persistence.py,
  migrations, package manifests, Dockerfiles, or security boundaries.
- Use exact requirement and acceptance statements as the source of behavior.
- Keep behavior deterministic for identical inputs.
- generated/repository/tests/test_acceptance.py should exercise concrete behavior implied by the System IR.
- Do not invent unspecified product rules. Preserve uncertainty explicitly in returned data.
- Do not return prose outside ImplementationPatchSet JSON.
- Every patch must list the decomposition step IDs whose responsibilities it implements.
- Cover every required decomposition step that represents domain behavior; do not silently omit a step.
- Do not claim step coverage merely because a file was touched.
- Change the smallest number of files necessary.

Return only JSON matching:
{json.dumps(ImplementationPatchSet.model_json_schema(), indent=2)}
""".strip()

        result = self._agent(
            prompt,
            structured_output_model=ImplementationPatchSet,
        )
        structured = getattr(result, "structured_output", result)
        if isinstance(structured, ImplementationPatchSet):
            return structured
        if isinstance(structured, dict):
            return ImplementationPatchSet.model_validate(structured)
        return ImplementationPatchSet.model_validate(json.loads(str(structured)))


class ConfiguredImplementationCompiler:
    """Select deterministic or model-backed implementation compilation."""

    def __init__(self) -> None:
        requested = os.getenv("SPECL00M_IMPLEMENTATION_MODE", "auto").lower()
        if requested not in {"auto", "bedrock", "deterministic", "off"}:
            requested = "auto"

        if requested == "auto":
            architect_mode = os.getenv(
                "SPECL00M_ARCHITECT_MODE",
                "bedrock",
            ).lower()
            mode = "bedrock" if architect_mode == "bedrock" else "deterministic"
        else:
            mode = requested

        self.mode = mode
        self.materialized = False
        self.uncovered_steps: list[str] = []
        self._impl: ImplementationCompiler | None = None

    def _compiler(self) -> ImplementationCompiler:
        if self._impl is not None:
            return self._impl

        if self.mode == "bedrock":
            self._impl = BedrockImplementationCompiler()
        else:
            self._impl = DeterministicImplementationCompiler()

        return self._impl

    def compile(
        self,
        *,
        goal: str,
        context: ContextGraph,
        system_ir: SystemIR,
        workflow: WorkflowIR,
        artifacts: list[Artifact],
    ) -> tuple[list[Artifact], list[CompilerDiagnostic]]:
        if self.mode == "off":
            self.materialized = False
            self.uncovered_steps = []
            return artifacts, []

        max_attempts = max(
            1,
            min(int(os.getenv("SPECL00M_IMPLEMENTATION_ATTEMPTS", "2")), 3),
        )
        current_artifacts = list(artifacts)
        baseline_implementation = next(
            (
                item.content
                for item in artifacts
                if item.path == "generated/repository/app/implementation.py"
            ),
            None,
        )
        diagnostics: list[CompilerDiagnostic] = []
        required_step_ids = {
            str(item.get("id"))
            for item in system_ir.problem_decomposition.get("steps", [])
            if isinstance(item, dict) and item.get("id")
        }
        self.materialized = False
        self.uncovered_steps = sorted(required_step_ids)

        for attempt in range(max_attempts):
            feedback = [
                "Cover the following decomposition steps in this synthesis attempt: "
                + ", ".join(self.uncovered_steps)
            ] if self.uncovered_steps else []
            patch_set = self._compiler().compile(
                goal=goal,
                context=context,
                system_ir=system_ir,
                workflow=workflow,
                artifacts=current_artifacts,
                feedback=feedback,
            )

            by_path = {item.path: item for item in current_artifacts}
            covered_step_ids: set[str] = set()
            for patch in patch_set.patches:
                covered_step_ids.update(
                    step_id for step_id in patch.step_ids if step_id in required_step_ids
                )

                allowed = {
                    "generated/repository/app/implementation.py",
                    "generated/repository/app/api.py",
                    "generated/repository/app/domain.py",
                    "generated/repository/web/src/App.tsx",
                    "generated/repository/tests/test_acceptance.py",
                }
                if patch.path not in allowed:
                    diagnostics.append(
                        CompilerDiagnostic(
                            severity="blocking",
                            code="implementation-path-not-allowed",
                            message=(
                                "Implementation compiler may only modify "
                                "the generated domain extension files."
                            ),
                            artifact_path=patch.path,
                        )
                    )
                    continue
                if patch.path not in by_path:
                    diagnostics.append(
                        CompilerDiagnostic(
                            severity="blocking",
                            code="implementation-artifact-missing",
                            message="Implementation target is not present in the repository plan.",
                            artifact_path=patch.path,
                        )
                    )
                    continue
                if _contains_embedded_secret(patch.content):
                    diagnostics.append(
                        CompilerDiagnostic(
                            severity="blocking",
                            code="implementation-embedded-secret",
                            message="Generated implementation appears to contain an embedded credential.",
                            artifact_path=patch.path,
                        )
                    )
                    continue

                if patch.path.endswith(".py"):
                    try:
                        ast.parse(patch.content, filename=patch.path)
                    except SyntaxError as exc:
                        diagnostics.append(
                            CompilerDiagnostic(
                                severity="warning",
                                code="implementation-python-syntax-awaiting-repair",
                                message=str(exc),
                                artifact_path=patch.path,
                            )
                        )

                old = by_path[patch.path]
                by_path[patch.path] = old.model_copy(
                    update={
                        "content": patch.content,
                        "sha256": "",
                        "generated_from": [
                            *old.generated_from,
                            "implementation-compiler",
                        ],
                    }
                ).with_hash()

            current_artifacts = list(by_path.values())
            self.uncovered_steps = sorted(required_step_ids - covered_step_ids)
            if baseline_implementation is not None:
                current_implementation = next(
                    (
                        item.content
                        for item in current_artifacts
                        if item.path == "generated/repository/app/implementation.py"
                    ),
                    baseline_implementation,
                )
                self.materialized = current_implementation.strip() != baseline_implementation.strip()

            if not self.uncovered_steps:
                break

            if self.mode != "bedrock":
                break

        if self.uncovered_steps:
            diagnostics.append(
                CompilerDiagnostic(
                    severity="warning",
                    code="implementation-steps-uncovered",
                    message=(
                        "Generated implementation does not explicitly cover decomposition steps: "
                        + ", ".join(self.uncovered_steps)
                    ),
                )
            )

        return current_artifacts, diagnostics


def _contains_embedded_secret(content: str) -> bool:
    patterns = (
        r"sk-[A-Za-z0-9_-]{16,}",
        r"AKIA[0-9A-Z]{16}",
        r"-----BEGIN [A-Z ]+ PRIVATE KEY-----",
    )
    return any(re.search(pattern, content) for pattern in patterns)
