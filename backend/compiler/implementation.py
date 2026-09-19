from __future__ import annotations

import ast
import json
import os
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
    ) -> ImplementationPatchSet:
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

IMPLEMENTATION CONTRACT
- Implement business/domain behavior in generated/repository/app/implementation.py.
- The module must expose:
    def handle(payload: dict, execution: dict) -> dict
- Use only the Python standard library plus files already present in the generated repository.
- Do not make network calls.
- Do not read credentials or environment secrets.
- Do not modify system-ir.json, workflow-ir.json, runtime.py, or security boundaries.
- Use exact requirement and acceptance statements as the source of behavior.
- Keep behavior deterministic for identical inputs.
- generated/repository/tests/test_acceptance.py should exercise concrete behavior implied by the System IR.
- Do not invent unspecified product rules. Preserve uncertainty explicitly in returned data.
- Do not return prose outside ImplementationPatchSet JSON.
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
            return artifacts, []

        patch_set = self._compiler().compile(
            goal=goal,
            context=context,
            system_ir=system_ir,
            workflow=workflow,
            artifacts=artifacts,
        )

        by_path = {item.path: item for item in artifacts}
        diagnostics: list[CompilerDiagnostic] = []

        allowed = {
            "generated/repository/app/implementation.py",
            "generated/repository/tests/test_acceptance.py",
        }
        for patch in patch_set.patches:
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

            try:
                ast.parse(patch.content, filename=patch.path)
            except SyntaxError as exc:
                diagnostics.append(
                    CompilerDiagnostic(
                        severity="blocking",
                        code="implementation-python-syntax",
                        message=str(exc),
                        artifact_path=patch.path,
                    )
                )
                continue

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

        return list(by_path.values()), diagnostics
