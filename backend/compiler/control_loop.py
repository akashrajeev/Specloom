from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from backend.compiler.recovery import AutonomousRecoveryEngine
from backend.context.store import store


@dataclass(frozen=True)
class ControlDecision:
    status: str
    runtime_run_id: str | None
    diagnosis: str
    recovery: dict[str, Any] | None = None
    rollback_target: dict[str, Any] | None = None
    requires_approval: bool = False
    next_action: str = "none"


class AutonomousControlLoop:
    """Observe runtime incidents and choose bounded remediation actions."""

    def tick(
        self,
        project_id: str,
        *,
        runtime_run_id: str | None = None,
    ) -> ControlDecision:
        project = store.get(project_id)
        runtime = self._select_runtime_run(project.runs, runtime_run_id)
        if runtime is None:
            return ControlDecision(
                status="healthy",
                runtime_run_id=None,
                diagnosis="No runtime incident is available for control-loop analysis.",
            )

        status = str(runtime.get("status") or "")
        if status != "failed":
            return ControlDecision(
                status="healthy",
                runtime_run_id=str(runtime.get("run_id")),
                diagnosis=f"Runtime run status is {status or 'unknown'}, not failed.",
            )

        diagnosis = self._diagnose(runtime)
        recovery = runtime.get("recovery")
        if not runtime.get("recovery_attempted"):
            decision = AutonomousRecoveryEngine().recover(
                project_id,
                run_id=str(runtime.get("run_id")),
                failure={
                    "error": runtime.get("error"),
                    "errors": runtime.get("errors"),
                    "events": runtime.get("events"),
                },
            )
            recovery = {
                "status": decision.status,
                "reason": decision.reason,
                "attempts": decision.attempts,
                "errors": decision.errors or [],
            }
            store.update_run(
                project_id,
                str(runtime.get("run_id")),
                {
                    "recovery": recovery,
                    "recovery_attempted": True,
                },
            )

        recovery_status = str((recovery or {}).get("status") or "unknown")
        if recovery_status == "repaired":
            return ControlDecision(
                status="recovered",
                runtime_run_id=str(runtime.get("run_id")),
                diagnosis=diagnosis,
                recovery=recovery,
                requires_approval=True,
                next_action="review_and_approve_redeployment",
            )

        rollback_target = self._latest_deployment(project.runs)
        if rollback_target is not None:
            return ControlDecision(
                status="rollback_available",
                runtime_run_id=str(runtime.get("run_id")),
                diagnosis=diagnosis,
                recovery=recovery,
                rollback_target=rollback_target,
                requires_approval=True,
                next_action="approve_rollback",
            )

        return ControlDecision(
            status="blocked",
            runtime_run_id=str(runtime.get("run_id")),
            diagnosis=diagnosis,
            recovery=recovery,
            requires_approval=False,
            next_action="inspect_incident",
        )

    @staticmethod
    def _select_runtime_run(
        runs: list[dict[str, Any]],
        runtime_run_id: str | None,
    ) -> dict[str, Any] | None:
        candidates = [
            item
            for item in runs
            if item.get("kind") == "runtime"
            and (runtime_run_id is None or item.get("run_id") == runtime_run_id)
        ]
        if not candidates:
            return None
        return candidates[0]

    @staticmethod
    def _diagnose(runtime: dict[str, Any]) -> str:
        errors = runtime.get("errors")
        if isinstance(errors, list) and errors:
            return str(errors[0])
        for key in ("error", "message", "cause"):
            value = runtime.get(key)
            if value:
                return str(value)
        for event in reversed(runtime.get("events") or []):
            if isinstance(event, dict) and event.get("status") == "failed":
                message = event.get("message") or event.get("error")
                if message:
                    return str(message)
        return "Runtime execution failed without a structured diagnostic."

    @staticmethod
    def _latest_deployment(runs: list[dict[str, Any]]) -> dict[str, Any] | None:
        return next(
            (
                item
                for item in runs
                if item.get("kind") == "deployment"
                and item.get("status") in {"deployed", "rolled_back"}
                and item.get("container_image")
                and item.get("artifact_snapshot_id")
            ),
            None,
        )
