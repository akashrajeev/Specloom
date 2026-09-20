from __future__ import annotations

import os
import re
from dataclasses import dataclass
from typing import Any, Literal

from backend.context.store import store


RepairLayer = Literal[
    "implementation",
    "staging",
    "workflow",
    "architecture",
    "capability",
    "contract",
    "unknown",
]


@dataclass(frozen=True)
class RepairRoute:
    layer: RepairLayer
    reason: str
    rebuild_required: bool


@dataclass(frozen=True)
class RebuildDecision:
    status: Literal["disabled", "blocked", "failed", "rebuilt"]
    reason: str
    attempts: int = 0
    build_run_id: str | None = None
    production_ready: bool = False
    staging_verified: bool = False
    route: RepairRoute | None = None
    result: dict[str, Any] | None = None


class UniversalRepairController:
    """Escalate runtime failures from source repair to a bounded full rebuild."""

    def __init__(self) -> None:
        mode = os.getenv("SPECL00M_AUTOREBUILD_MODE", "off").lower()
        self.enabled = mode in {"on", "bedrock"}
        self.max_attempts = max(
            1,
            min(int(os.getenv("SPECL00M_AUTOREBUILD_ATTEMPTS", "1")), 2),
        )

    @staticmethod
    def classify(failure: dict[str, Any]) -> RepairRoute:
        text = " ".join(
            str(value)
            for value in (
                failure.get("error"),
                failure.get("message"),
                *(failure.get("errors") or []),
            )
            if value
        ).lower()

        if re.search(r"\b(workflow|unreachable|edge|approval|policy)\b", text):
            return RepairRoute(
                layer="workflow",
                reason="runtime diagnostics indicate workflow/control-flow semantics",
                rebuild_required=True,
            )
        if re.search(r"\b(capability|adapter|tool_ref|tool)\b", text):
            return RepairRoute(
                layer="capability",
                reason="runtime diagnostics indicate capability wiring",
                rebuild_required=True,
            )
        if re.search(r"\b(contract|openapi|endpoint|authentication|credential)\b", text):
            return RepairRoute(
                layer="contract",
                reason="runtime diagnostics indicate an external contract boundary",
                rebuild_required=True,
            )
        if re.search(r"\b(staging|container|docker|startup|health)\b", text):
            return RepairRoute(
                layer="staging",
                reason="runtime diagnostics indicate container or staging behavior",
                rebuild_required=True,
            )
        if re.search(r"\b(architecture|service|system ir|decomposition)\b", text):
            return RepairRoute(
                layer="architecture",
                reason="runtime diagnostics indicate a system-level design mismatch",
                rebuild_required=True,
            )
        if text:
            return RepairRoute(
                layer="implementation",
                reason="runtime diagnostics are most directly attributable to generated implementation",
                rebuild_required=False,
            )
        return RepairRoute(
            layer="unknown",
            reason="runtime failure has insufficient structure for a narrower repair classification",
            rebuild_required=True,
        )

    def rebuild(
        self,
        project_id: str,
        *,
        run_id: str,
        failure: dict[str, Any],
    ) -> RebuildDecision:
        route = self.classify(failure)
        if not self.enabled:
            return RebuildDecision(
                status="disabled",
                reason="SPECL00M_AUTOREBUILD_MODE is off",
                route=route,
            )

        project = store.get(project_id)
        existing = next(
            (
                item
                for item in project.runs
                if item.get("kind") == "runtime"
                and item.get("run_id") == run_id
            ),
            None,
        )
        if existing is not None and existing.get("autonomous_rebuild_attempted"):
            return RebuildDecision(
                status="blocked",
                reason="autonomous full rebuild was already attempted for this runtime incident",
                route=route,
            )

        store.update_run(
            project_id,
            run_id,
            {
                "autonomous_rebuild_attempted": True,
                "autonomous_rebuild_route": route.layer,
            },
        )

        goal = self._goal(project_id)
        attempts = 0
        last_result: dict[str, Any] | None = None
        last_error = ""
        for attempt in range(1, self.max_attempts + 1):
            attempts = attempt
            try:
                from backend.api.build import BuildRequestBody, build

                result = build(
                    project_id,
                    BuildRequestBody(
                        goal=goal,
                        autonomous=True,
                        require_staging=True,
                    ),
                )
                last_result = result
                if not result.get("ready", True):
                    return RebuildDecision(
                        status="blocked",
                        reason="autonomous rebuild stopped at a compiler readiness boundary",
                        attempts=attempts,
                        route=route,
                        result=result,
                    )

                staging = result.get("staging") or {}
                production_ready = bool(result.get("production_ready", False))
                staging_verified = staging.get("status") == "passed"
                build_run_id = self._latest_build_run(project_id, result)
                return RebuildDecision(
                    status="rebuilt",
                    reason=(
                        "autonomous full rebuild produced a new verified build"
                        + (
                            " that is production-ready"
                            if production_ready
                            else ""
                        )
                    ),
                    attempts=attempts,
                    build_run_id=build_run_id,
                    production_ready=production_ready,
                    staging_verified=staging_verified,
                    route=route,
                    result=result,
                )
            except Exception as exc:
                last_error = str(exc)

        return RebuildDecision(
            status="failed",
            reason=(
                "autonomous full rebuild failed after bounded attempts"
                + (f": {last_error}" if last_error else "")
            ),
            attempts=attempts,
            route=route,
            result=last_result,
        )

    @staticmethod
    def _latest_build_run(project_id: str, result: dict[str, Any]) -> str | None:
        artifact_status = result.get("artifact_status") or {}
        project = store.get(project_id)
        candidate = next(
            (
                item
                for item in project.runs
                if item.get("kind") == "build"
                and item.get("artifact_hashes")
                and (
                    not artifact_status
                    or len(item.get("artifact_hashes", {})) == artifact_status.get("count")
                )
            ),
            None,
        )
        return str(candidate.get("run_id")) if candidate else None

    @staticmethod
    def _goal(project_id: str) -> str:
        project = store.get(project_id)
        for run in project.runs:
            if run.get("kind") == "autobuild" and run.get("goal"):
                return str(run["goal"])
            if run.get("kind") == "build" and run.get("goal"):
                return str(run["goal"])
        requirements = "\n".join(
            item.statement
            for item in project.graph.requirements[:24]
        )
        workflow = project.workflow
        description = workflow.description if workflow is not None else ""
        return (
            description
            or requirements
            or f"Rebuild the generated system for project {project_id}."
        )[:5000]
