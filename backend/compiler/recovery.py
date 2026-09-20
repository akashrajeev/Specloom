from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

from backend.compiler.models import Artifact
from backend.compiler.repair import BedrockSoftwareRepairer, SoftwareRepairEngine
from backend.compiler.sandbox import SandboxPolicy, SandboxVerifier
from backend.compiler.staging import StagingContainerExecutor
from backend.context.store import store
from backend.workflow.models import WorkflowIR


@dataclass(frozen=True)
class RecoveryDecision:
    status: str
    reason: str
    attempts: int = 0
    errors: list[str] | None = None


class AutonomousRecoveryEngine:
    """Turn runtime failures into bounded, verifiable repair attempts."""

    def __init__(self) -> None:
        mode = os.getenv("SPECL00M_AUTORECOVERY_MODE", "off").lower()
        self.enabled = mode in {"bedrock", "on"}
        self.max_attempts = max(
            1,
            min(int(os.getenv("SPECL00M_AUTORECOVERY_ATTEMPTS", "2")), 2),
        )
        sandbox_mode = os.getenv("SPECL00M_SANDBOX_MODE", "process").lower()
        self.verifier = SandboxVerifier(
            SandboxPolicy(
                mode=sandbox_mode if sandbox_mode in {"process", "container"} else "process",
            )
        )

    def recover(self, project_id: str, *, run_id: str, failure: dict[str, Any]) -> RecoveryDecision:
        if not self.enabled:
            return RecoveryDecision(
                status="disabled",
                reason="SPECL00M_AUTORECOVERY_MODE is off",
            )

        project = store.get(project_id)
        if project.workflow is None:
            return RecoveryDecision(
                status="blocked",
                reason="project has no workflow snapshot",
            )
        if not project.artifacts:
            return RecoveryDecision(
                status="blocked",
                reason="project has no generated artifacts",
            )

        artifacts = [
            Artifact(path=path, kind=self._artifact_kind(path), content=content).with_hash()
            for path, content in project.artifacts.items()
        ]
        verification = {
            "status": "failed",
            "errors": self._failure_errors(failure),
            "checked_artifacts": len(artifacts),
            "executed_contract": False,
            "incident": {
                "run_id": run_id,
                "kind": "runtime_failure",
            },
        }

        if not verification["errors"]:
            verification["errors"] = ["runtime execution failed without an error detail"]

        if not any(item.path.startswith("generated/repository/") for item in artifacts):
            return RecoveryDecision(
                status="blocked",
                reason="failure has no repairable generated repository artifacts",
                errors=list(verification["errors"]),
            )

        if not self.enabled:
            return RecoveryDecision(
                status="disabled",
                reason="autonomous recovery is disabled",
                errors=list(verification["errors"]),
            )

        try:
            repaired, final_verification, attempts, findings = SoftwareRepairEngine(
                repairer=BedrockSoftwareRepairer(),
                verifier=self.verifier,
                max_attempts=self.max_attempts,
            ).repair(
                goal=self._goal(project_id),
                context=project.graph,
                workflow=project.workflow,
                artifacts=artifacts,
                initial_verification=verification,
            )
        except (RuntimeError, ValueError, OSError) as exc:
            return RecoveryDecision(
                status="failed",
                reason=f"repair engine failed: {exc}",
                errors=[str(exc)],
            )

        project.artifacts = {item.path: item.content for item in repaired}
        store.persist(project_id)

        errors = [
            str(item)
            for item in final_verification.get("errors", [])
        ]
        if final_verification.get("status") != "passed":
            return RecoveryDecision(
                status="failed",
                reason="generated artifacts remain invalid after recovery attempts",
                attempts=attempts,
                errors=[*errors, *findings[-10:]],
            )

        if os.getenv("SPECL00M_AUTORECOVERY_STAGING", "none").lower() == "container":
            try:
                staging = StagingContainerExecutor().execute(repaired)
            except (RuntimeError, ValueError, OSError) as exc:
                return RecoveryDecision(
                    status="failed",
                    reason=f"repaired artifacts passed sandbox verification but staging failed: {exc}",
                    attempts=attempts,
                    errors=[*findings[-10:], str(exc)],
                )
            if staging.get("status") != "passed":
                return RecoveryDecision(
                    status="failed",
                    reason="repaired artifacts passed sandbox verification but staging did not pass",
                    attempts=attempts,
                    errors=[*findings[-10:], str(staging)],
                )

        return RecoveryDecision(
            status="repaired",
            reason="runtime failure was mapped to generated artifacts and the repaired bundle passed sandbox verification",
            attempts=attempts,
            errors=findings[-10:],
        )

    @staticmethod
    def _failure_errors(failure: dict[str, Any]) -> list[str]:
        errors = failure.get("errors")
        if isinstance(errors, list):
            return [str(item) for item in errors if str(item).strip()]
        for key in ("error", "message", "cause"):
            value = failure.get(key)
            if value:
                return [str(value)]
        return []

    @staticmethod
    def _artifact_kind(path: str) -> str:
        if path.endswith(".json"):
            return "spec" if "/spec/" in path else "config"
        if path.endswith(".py"):
            return "test" if "/tests/" in path else "source"
        if path.endswith((".yaml", ".yml", ".tf")):
            return "infrastructure"
        if path.endswith(".md"):
            return "documentation"
        return "source"

    @staticmethod
    def _goal(project_id: str) -> str:
        project = store.get(project_id)
        workflow = project.workflow
        if workflow is not None:
            requirements = "\n".join(
                item.statement
                for item in project.graph.requirements[:20]
            )
            description = workflow.description or workflow.name
            return (
                f"Repair the generated system for project {project_id}. "
                f"Original workflow: {description}. "
                f"Declared requirements: {requirements}"
            )[:5000]
        return f"Repair the generated system for project {project_id}."
