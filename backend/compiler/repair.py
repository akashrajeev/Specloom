from __future__ import annotations

import ast
import json
import os
import re
from pathlib import Path
from typing import Any, Protocol

from pydantic import BaseModel, Field

from backend.context.models import ContextGraph
from backend.workflow.models import WorkflowIR

from .models import Artifact
from .sandbox import SandboxVerifier


class ArtifactPatch(BaseModel):
    path: str
    content: str
    rationale: str = ""


class ArtifactPatchSet(BaseModel):
    patches: list[ArtifactPatch] = Field(default_factory=list)
    summary: str = ""


class SoftwareRepairer(Protocol):
    def repair(
        self,
        *,
        goal: str,
        context: ContextGraph,
        workflow: WorkflowIR,
        artifacts: list[Artifact],
        verification: dict[str, Any],
    ) -> ArtifactPatchSet:
        ...


class SoftwareRepairEngine:
    """Apply bounded source-level repairs and re-run verification."""

    def __init__(
        self,
        repairer: SoftwareRepairer,
        verifier: SandboxVerifier | None = None,
        max_attempts: int = 2,
    ) -> None:
        self.repairer = repairer
        self.verifier = verifier or SandboxVerifier()
        self.max_attempts = max(1, min(max_attempts, 3))

    def repair(
        self,
        *,
        goal: str,
        context: ContextGraph,
        workflow: WorkflowIR,
        artifacts: list[Artifact],
        initial_verification: dict[str, Any] | None = None,
    ) -> tuple[list[Artifact], dict[str, Any], int, list[str]]:
        current = list(artifacts)
        findings: list[str] = []
        verification = dict(
            initial_verification
            if initial_verification is not None
            else self.verifier.verify(current)
        )

        if verification["status"] == "passed":
            return current, verification, 0, findings

        for attempt in range(1, self.max_attempts + 1):
            patch_set = self.repairer.repair(
                goal=goal,
                context=context,
                workflow=workflow,
                artifacts=current,
                verification=verification,
            )
            current, rejected = self._apply(current, patch_set)
            findings.extend(rejected)

            if rejected:
                verification = {
                    "status": "failed",
                    "errors": rejected,
                    "checked_artifacts": len(current),
                    "executed_contract": False,
                }
                continue

            verification = dict(self.verifier.verify(current))
            if verification["status"] == "passed":
                return current, verification, attempt, findings

            findings.extend(
                str(item)
                for item in verification.get("errors", [])
            )

        return current, verification, self.max_attempts, findings

    @classmethod
    def _apply(
        cls,
        artifacts: list[Artifact],
        patch_set: ArtifactPatchSet,
    ) -> tuple[list[Artifact], list[str]]:
        by_path = {item.path: item for item in artifacts}
        rejected: list[str] = []
        immutable = {
            "generated/repository/system-ir.json",
            "generated/repository/workflow-ir.json",
        }

        for patch in patch_set.patches:
            path = patch.path

            if not cls._allowed_path(path):
                rejected.append(
                    f"repair rejected unsafe path: {path}"
                )
                continue

            if path in immutable:
                rejected.append(
                    f"repair rejected immutable specification: {path}"
                )
                continue

            if path not in by_path:
                rejected.append(
                    f"repair rejected unknown artifact: {path}"
                )
                continue

            if cls._contains_embedded_secret(patch.content):
                rejected.append(
                    f"repair rejected possible embedded secret: {path}"
                )
                continue

            suffix = Path(path).suffix.lower()
            try:
                if suffix == ".py":
                    ast.parse(patch.content, filename=path)
                elif suffix == ".json":
                    json.loads(patch.content)
            except (SyntaxError, ValueError) as exc:
                rejected.append(
                    f"repair rejected invalid artifact {path}: {exc}"
                )
                continue

            old = by_path[path]
            by_path[path] = old.model_copy(
                update={
                    "content": patch.content,
                    "sha256": "",
                    "generated_from": [
                        *old.generated_from,
                        "software-repair",
                    ],
                }
            ).with_hash()

        return list(by_path.values()), rejected

    @staticmethod
    def _allowed_path(path: str) -> bool:
        if not path.startswith("generated/repository/"):
            return False
        pure = Path(path)
        return not pure.is_absolute() and all(
            part not in {"", ".", ".."}
            for part in pure.parts
        )

    @staticmethod
    def _contains_embedded_secret(content: str) -> bool:
        patterns = (
            r"sk-[A-Za-z0-9_-]{16,}",
            r"AKIA[0-9A-Z]{16}",
            r"-----BEGIN [A-Z ]+ PRIVATE KEY-----",
        )
        return any(
            re.search(pattern, content)
            for pattern in patterns
        )


class BedrockSoftwareRepairer:
    """Model-backed repairer constrained to generated implementation artifacts."""

    def __init__(self, model_id: str = "") -> None:
        try:
            from strands import Agent
            from strands.models import BedrockModel
        except ImportError as exc:
            raise RuntimeError(
                "AWS architect dependencies are missing. "
                "Install backend/requirements-aws.txt"
            ) from exc

        resolved_model = model_id or os.getenv(
            "SPECL00M_BEDROCK_MODEL_ID",
            "amazon.nova-lite-v1:0",
        )
        self._agent = Agent(
            model=BedrockModel(model_id=resolved_model),
            system_prompt=(
                "You are Specloom's software repair compiler. "
                "Repair generated source/config artifacts only. "
                "Never change canonical SystemIR or WorkflowIR files. "
                "Never embed credentials. Return only ArtifactPatchSet JSON."
            ),
        )

    def repair(
        self,
        *,
        goal: str,
        context: ContextGraph,
        workflow: WorkflowIR,
        artifacts: list[Artifact],
        verification: dict[str, Any],
    ) -> ArtifactPatchSet:
        mutable = [
            {
                "path": item.path,
                "content": item.content,
                "kind": item.kind,
            }
            for item in artifacts
            if item.path.startswith("generated/repository/")
            and item.path not in {
                "generated/repository/system-ir.json",
                "generated/repository/workflow-ir.json",
            }
        ]

        prompt = (
            "Repair the generated repository so compiler verification passes.\n\n"
            f"GOAL:\n{goal}\n\n"
            f"SYSTEM CONTEXT:\n{context.model_dump_json(indent=2)}\n\n"
            f"WORKFLOW:\n{workflow.model_dump_json(indent=2)}\n\n"
            f"VERIFICATION:\n{json.dumps(verification, indent=2)}\n\n"
            "MUTABLE ARTIFACTS:\n"
            f"{json.dumps(mutable, indent=2)}\n\n"
            "Return only JSON matching ArtifactPatchSet. "
            "Change the smallest number of files needed."
        )

        result = self._agent(
            prompt,
            structured_output_model=ArtifactPatchSet,
        )
        structured = getattr(result, "structured_output", result)

        if isinstance(structured, ArtifactPatchSet):
            return structured
        if isinstance(structured, dict):
            return ArtifactPatchSet.model_validate(structured)

        return ArtifactPatchSet.model_validate(
            json.loads(str(structured))
        )
