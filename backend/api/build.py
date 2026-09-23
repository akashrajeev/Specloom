from __future__ import annotations

import hashlib
import json
import os
from contextlib import contextmanager
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from backend.agents.architect import BuildRequest, ConfiguredArchitect
from backend.agents.reviewer import ArchitectureReview, BedrockArchitectureReviewer
from backend.capabilities.bindings import bind_capabilities, validate_capability_bindings
from backend.compiler.architecture_search import ArchitectureHypothesisSearcher
from backend.compiler.assumptions import AutonomousAssumptionResolver
from backend.compiler.deployment import DeploymentCompiler
from backend.compiler.decomposition import ConfiguredProblemDecomposer
from backend.compiler.models import Artifact, artifact_digest
from backend.compiler.planner import ConfiguredSystemPlanner
from backend.compiler.capability_autobind import auto_bind_required_capabilities
from backend.compiler.contracts import CapabilityContractAcquirer
from backend.compiler.research import BedrockResearchExecutor, ResearchExecutionResult, apply_research_evidence, configured_research_planner
from backend.compiler.repair import BedrockSoftwareRepairer, SoftwareRepairEngine
from backend.compiler.sandbox import SandboxPolicy, SandboxVerifier
from backend.compiler.staging import StagingContainerExecutor
from backend.compiler.universal import UniversalCompiler
from backend.context.service import analyze_sources
from backend.context.ingestion import ingest_text
from backend.context.gaps import detect_gaps
from backend.context.models import Constraint, Provenance, Requirement
from backend.context.store import store
from backend.bedrock_config import (
    BedrockQuotaExhausted,
    bedrock_quota_recently_exhausted,
    is_bedrock_quota_error,
    mark_bedrock_quota_exhausted,
)
from backend.storage.build_jobs import build_jobs
from backend.evaluation.evaluator import Evaluator
from backend.evaluation.testgen import augment_with_generated_tests
from backend.workflow.compiler import compile_workflow
from backend.workflow.validator import validate_architecture_coverage, validate_workflow

router = APIRouter(prefix="/api/v1/projects", tags=["build"])
architect = ConfiguredArchitect()
universal_compiler = UniversalCompiler()
sandbox_mode = os.getenv("SPECL00M_SANDBOX_MODE", "process").lower()
sandbox_verifier = SandboxVerifier(
    SandboxPolicy(
        mode=sandbox_mode if sandbox_mode in {"process", "container"} else "process",
    )
)
system_planner = ConfiguredSystemPlanner(architect_mode=architect.mode)
assumption_resolver = AutonomousAssumptionResolver()
contract_acquirer = CapabilityContractAcquirer()
problem_decomposer = ConfiguredProblemDecomposer()
research_planner = configured_research_planner()
research_execution_mode = os.getenv("SPECL00M_RESEARCH_EXECUTION_MODE", "off").lower()


class BuildRequestBody(BaseModel):
    goal: str = Field(min_length=10, max_length=5000)
    gap_answers: dict[str, str] = Field(default_factory=dict)
    autonomous: bool = False
    require_staging: bool = False


class AutoBuildRequest(BaseModel):
    goal: str = Field(min_length=10, max_length=5000)
    gap_answers: dict[str, str] = Field(default_factory=dict)
    target: str = Field(default="artifact", pattern="^(artifact|staging|production)$")
    approved: bool = False


class AutoBuildResumeRequest(BaseModel):
    approved: bool = False


def _new_autobuild_state(project_id: str, request: AutoBuildRequest) -> dict:
    now = datetime.now(timezone.utc).isoformat()
    return {
        "kind": "autobuild",
        "run_id": uuid.uuid4().hex,
        "project_id": project_id,
        "goal": request.goal,
        "target": request.target,
        "status": "running",
        "current_stage": "discover",
        "started_at": now,
        "updated_at": now,
        "stages": {
            stage: {"status": "pending"}
            for stage in ("discover", "research", "assume", "architect", "compile", "verify", "repair", "stage", "provision", "promote", "observe")
        },
    }


def _autobuild_run(project_id: str, run_id: str) -> dict | None:
    project = store.get(project_id)
    return next((item for item in project.runs if item.get("run_id") == run_id), None)


def _set_autobuild_stage(project_id: str, run_id: str, stage: str, status: str, **details) -> dict:
    run = _autobuild_run(project_id, run_id)
    if run is None:
        return {"run_id": run_id, "current_stage": stage, "status": status}
    now = datetime.now(timezone.utc).isoformat()
    stages = dict(run.get("stages", {}))
    previous = dict(stages.get(stage, {}))
    entry = {**previous, "status": status, **details}
    if status == "running":
        entry.setdefault("started_at", now)
        entry["attempt"] = int(entry.get("attempt", 0)) + 1
    elif status in {"completed", "failed", "blocked", "skipped", "awaiting_approval"}:
        entry.setdefault("started_at", previous.get("started_at", now))
        entry["completed_at"] = now
    stages[stage] = entry
    run["stages"] = stages
    run["current_stage"] = stage
    run["updated_at"] = now
    store.persist(project_id)
    return run


def _finish_autobuild(project_id: str, run_id: str, status: str, stage: str, **details) -> dict:
    run = _autobuild_run(project_id, run_id) or {"run_id": run_id}
    run.update({
        "status": status,
        "current_stage": stage,
        "updated_at": datetime.now(timezone.utc).isoformat(),
        **details,
    })
    store.persist(project_id)
    return run


@router.post("/{project_id}/autobuild")
def autobuild(project_id: str, request: AutoBuildRequest) -> dict:
    state = _new_autobuild_state(project_id, request)
    state["gap_answers"] = dict(request.gap_answers)
    store.record_run(project_id, state)
    run_id = state["run_id"]
    _set_autobuild_stage(project_id, run_id, "discover", "running")

    try:
        result = build(
            project_id,
            BuildRequestBody(
                goal=request.goal,
                gap_answers=request.gap_answers,
                autonomous=True,
                require_staging=request.target in {"staging", "production"},
            ),
        )
    except HTTPException as exc:
        _set_autobuild_stage(project_id, run_id, "compile", "failed", error=exc.detail)
        state = _finish_autobuild(project_id, run_id, "failed", "compile", error=exc.detail)
        return {"status": "failed", "project_id": project_id, "target": request.target, "run_id": run_id, "state": state}

    research_execution = result.get("research_execution") or {}
    research_status = str(research_execution.get("status") or "skipped")
    _set_autobuild_stage(project_id, run_id, "discover", "completed", capability_count=len(result.get("capabilities", [])))
    _set_autobuild_stage(
        project_id, run_id, "research",
        "completed" if research_status == "completed" else ("failed" if research_status == "failed" else "skipped"),
        research_status=research_status,
        task_count=len((result.get("research_plan") or {}).get("tasks", [])),
    )
    assumptions = result.get("assumptions") or []
    _set_autobuild_stage(project_id, run_id, "assume", "completed" if assumptions else "skipped", count=len(assumptions))
    _set_autobuild_stage(project_id, run_id, "architect", "completed" if result.get("workflow") else "blocked")

    if result.get("ready") is False:
        _set_autobuild_stage(project_id, run_id, "compile", "blocked", gaps=result.get("gaps", []))
        for stage in ("verify", "repair", "stage", "provision", "promote", "observe"):
            _set_autobuild_stage(project_id, run_id, stage, "skipped")
        state = _finish_autobuild(project_id, run_id, "blocked", "compile", gaps=result.get("gaps", []))
        return {"status": "blocked", "project_id": project_id, "target": request.target, "run_id": run_id, "state": state, "build": result}

    artifact_status = result.get("artifact_status") or {}
    _set_autobuild_stage(project_id, run_id, "compile", "completed" if artifact_status.get("count") else "blocked", artifact_count=artifact_status.get("count", 0))
    verification = result.get("software_verification") or {}
    _set_autobuild_stage(project_id, run_id, "verify", "completed" if verification.get("status") == "passed" else "failed", result=verification)
    repair_attempts = int(result.get("software_repair_count") or 0)
    _set_autobuild_stage(project_id, run_id, "repair", "completed" if repair_attempts else "skipped", attempts=repair_attempts)
    staging = result.get("staging", {})
    staging_status = staging.get("status")
    _set_autobuild_stage(
        project_id, run_id, "stage",
        "completed" if staging_status == "passed" else ("skipped" if staging_status == "skipped" else "failed"),
        result=staging,
    )
    provisioning = result.get("provisioning", {})
    _set_autobuild_stage(project_id, run_id, "provision", "completed" if provisioning.get("ready") else "pending", ready=provisioning.get("ready"))

    project = store.get(project_id)
    proof_hashes = {
        path: hashlib.sha256(content.encode("utf-8")).hexdigest()
        for path, content in project.artifacts.items()
    }
    state = _autobuild_run(project_id, run_id) or state
    durable_build_proof = next(
        (
            item
            for item in store.get(project_id).runs
            if item.get("kind") == "build"
            and item.get("artifact_hashes") == proof_hashes
        ),
        None,
    )
    state["build_proof"] = {
        "production_ready": bool(result.get("production_ready", False)),
        "artifact_hashes": proof_hashes,
        "artifact_digest": (
            durable_build_proof.get("artifact_digest")
            if durable_build_proof is not None
            else None
        ),
        "run_id": (
            durable_build_proof.get("run_id")
            if durable_build_proof is not None
            else None
        ),
    }
    store.persist(project_id)

    if request.target == "artifact":
        _set_autobuild_stage(project_id, run_id, "promote", "skipped")
        _set_autobuild_stage(project_id, run_id, "observe", "completed", artifact_count=artifact_status.get("count", 0))
        state = _finish_autobuild(project_id, run_id, "completed", "observe", completed_at=datetime.now(timezone.utc).isoformat())
        return {"status": "built", "project_id": project_id, "target": "artifact", "run_id": run_id, "state": state, "build": result}

    if request.target == "staging":
        _set_autobuild_stage(project_id, run_id, "promote", "skipped")
        if staging_status != "passed":
            state = _finish_autobuild(project_id, run_id, "blocked", "stage", error="staging did not pass")
            return {"status": "staging_required", "project_id": project_id, "target": "staging", "run_id": run_id, "state": state, "build": result, "staging": staging}
        _set_autobuild_stage(project_id, run_id, "observe", "completed", artifact_count=artifact_status.get("count", 0))
        state = _finish_autobuild(project_id, run_id, "completed", "observe", completed_at=datetime.now(timezone.utc).isoformat())
        return {"status": "staged", "project_id": project_id, "target": "staging", "run_id": run_id, "state": state, "build": result, "staging": staging}

    if not request.approved:
        _set_autobuild_stage(project_id, run_id, "promote", "awaiting_approval")
        _set_autobuild_stage(project_id, run_id, "observe", "pending")
        state = _finish_autobuild(project_id, run_id, "awaiting_approval", "promote")
        return {"status": "awaiting_approval", "project_id": project_id, "target": "production", "run_id": run_id, "state": state, "build": result}

    if not result.get("production_ready", False):
        _set_autobuild_stage(project_id, run_id, "promote", "blocked", reasons=result.get("deployment", {}).get("blocking_reasons", []))
        _set_autobuild_stage(project_id, run_id, "observe", "skipped")
        state = _finish_autobuild(project_id, run_id, "production_blocked", "promote")
        return {"status": "production_blocked", "project_id": project_id, "target": "production", "run_id": run_id, "state": state, "build": result}

    _set_autobuild_stage(project_id, run_id, "promote", "running")
    from backend.api.deploy import GeneratedProductionDeployRequest, deploy_generated
    try:
        deployment = deploy_generated(project_id, GeneratedProductionDeployRequest(approved=True))
    except HTTPException as exc:
        state = _finish_autobuild(project_id, run_id, "failed", "promote", error=exc.detail)
        return {"status": "failed", "project_id": project_id, "target": "production", "run_id": run_id, "state": state, "build": result}
    _set_autobuild_stage(project_id, run_id, "promote", "completed", deployment=deployment)
    _set_autobuild_stage(project_id, run_id, "observe", "completed")
    state = _finish_autobuild(project_id, run_id, "deployed", "observe", completed_at=datetime.now(timezone.utc).isoformat())
    return {"status": "deployed", "project_id": project_id, "target": "production", "run_id": run_id, "state": state, "build": result, "deployment": deployment}
@router.post("/{project_id}/autobuild/{run_id}/resume")
def resume_autobuild(project_id: str, run_id: str, request: AutoBuildResumeRequest) -> dict:
    state = _autobuild_run(project_id, run_id)
    if state is None or state.get("kind") != "autobuild":
        raise HTTPException(status_code=404, detail="autobuild run not found")
    if state.get("status") != "awaiting_approval" or state.get("target") != "production":
        raise HTTPException(status_code=409, detail="only production autobuilds awaiting approval can be resumed in-place")
    if not request.approved:
        raise HTTPException(status_code=403, detail="production resume requires explicit approval")

    proof = state.get("build_proof") or {}
    if not proof.get("production_ready"):
        raise HTTPException(status_code=409, detail="autobuild run no longer has production readiness proof")
    project = store.get(project_id)
    current_hashes = {
        path: hashlib.sha256(content.encode("utf-8")).hexdigest()
        for path, content in project.artifacts.items()
    }
    if current_hashes != (proof.get("artifact_hashes") or {}):
        raise HTTPException(status_code=409, detail="generated artifacts changed after approval was requested; rebuild and re-verify before promotion")

    _set_autobuild_stage(project_id, run_id, "promote", "running")
    from backend.api.deploy import GeneratedProductionDeployRequest, deploy_generated
    try:
        deployment = deploy_generated(project_id, GeneratedProductionDeployRequest(approved=True))
    except HTTPException as exc:
        state = _finish_autobuild(project_id, run_id, "failed", "promote", error=exc.detail)
        return {"status": "failed", "project_id": project_id, "run_id": run_id, "state": state}
    _set_autobuild_stage(project_id, run_id, "promote", "completed", deployment=deployment)
    _set_autobuild_stage(project_id, run_id, "observe", "completed")
    state = _finish_autobuild(project_id, run_id, "deployed", "observe", completed_at=datetime.now(timezone.utc).isoformat())
    return {"status": "deployed", "project_id": project_id, "run_id": run_id, "state": state, "deployment": deployment}

@router.get("/{project_id}/autobuild/{run_id}")
def autobuild_status(project_id: str, run_id: str) -> dict:
    run = _autobuild_run(project_id, run_id)
    if run is None or run.get("kind") != "autobuild":
        raise HTTPException(status_code=404, detail="autobuild run not found")
    return {"project_id": project_id, "run_id": run_id, "state": run}



def _augment_semantic_verification(
    verification: dict,
    artifacts,
    *,
    acceptance_proven: bool,
    acceptance_reviewed: bool,
    acceptance_origin: str,
    unverified_criteria: list[str],
) -> dict:
    result = dict(verification)
    manifest = next(
        (
            item for item in artifacts
            if item.path == "generated/repository/tests/independent-acceptance.json"
        ),
        None,
    )
    cases = []
    if manifest is not None:
        try:
            cases = json.loads(manifest.content).get("cases", [])
        except (TypeError, ValueError):
            cases = []
    result["acceptance"] = {
        "case_count": len(cases),
        "unverified_criteria": list(unverified_criteria),
    }
    if acceptance_origin == "model":
        executed_semantic_acceptance = (
            result.get("executed_synthesized_acceptance") is True
        )
    elif acceptance_origin == "mixed":
        executed_semantic_acceptance = (
            result.get("executed_independent_acceptance") is True
            and result.get("executed_synthesized_acceptance") is True
        )
    else:
        executed_semantic_acceptance = (
            result.get("executed_independent_acceptance") is True
        )

    result["semantic_proof"] = bool(
        acceptance_proven
        and acceptance_reviewed
        and not unverified_criteria
        and result.get("status") == "passed"
        and executed_semantic_acceptance
    )
    return result


def _revision_findings(
    *,
    validation_errors: list[str],
    evaluation,
    review: ArchitectureReview | None,
) -> list[dict]:
    findings: list[dict] = []
    findings.extend(
        {
            "severity": "blocking",
            "category": "deterministic_validation",
            "message": error,
        }
        for error in validation_errors
    )
    if evaluation is not None and evaluation.status == "failed":
        findings.extend(
            {
                "severity": "blocking",
                "category": "proof_test",
                "message": f"{item.test_id}: {item.message}",
            }
            for item in evaluation.tests
            if item.status == "failed"
        )
    if review is not None:
        findings.extend(
            item.model_dump(mode="json")
            for item in review.findings
            if item.severity == "blocking"
        )
    return findings


_DETERMINISTIC_OVERRIDES = {
    "SPECL00M_ARCHITECT_MODE": "showcase",
    "SPECL00M_CONTEXT_MODE": "deterministic",
    "SPECL00M_DECOMPOSITION_MODE": "deterministic",
    "SPECL00M_RESEARCH_MODE": "deterministic",
    "SPECL00M_SYSTEM_PLANNER_MODE": "deterministic",
    "SPECL00M_REVIEW_MODE": "none",
    "SPECL00M_MODELS_OFF": "1",
}


@contextmanager
def _deterministic_compiler():
    """Run one build with every model-backed step switched to its deterministic path."""
    saved_env = {key: os.environ.get(key) for key in _DETERMINISTIC_OVERRIDES}
    saved_mode = architect.mode
    saved_impl = architect._impl
    os.environ.update(_DETERMINISTIC_OVERRIDES)
    architect.mode = "showcase"
    architect._impl = None  # drop a cached model-backed architect
    # Module-level configured stages (planner, research, implementation, ...) pick their
    # mode once at import; switch the model-backed ones to their deterministic paths too.
    switched = []
    for name, obj in list(globals().items()):
        if obj is architect or name.startswith("_"):
            continue
        if getattr(obj, "mode", None) == "bedrock" and hasattr(obj, "_impl"):
            switched.append((obj, obj.mode, obj._impl))
            obj.mode = "deterministic"
            obj._impl = None
    # Autonomous builds promote capability/acceptance compilation to model mode unless
    # it is explicitly "off"; the template fallback must not call any model.
    saved_universal = (universal_compiler.capability_mode, universal_compiler.acceptance_mode)
    universal_compiler.capability_mode = "off"
    universal_compiler.acceptance_mode = "off"
    try:
        yield
    finally:
        universal_compiler.capability_mode, universal_compiler.acceptance_mode = saved_universal
        for obj, mode, impl in switched:
            obj.mode = mode
            obj._impl = impl
        architect.mode = saved_mode
        architect._impl = saved_impl
        for key, value in saved_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


@router.post("/{project_id}/build")
def build(project_id: str, request: BuildRequestBody) -> dict:
    try:
        return _build_once(project_id, request)
    except (HTTPException, RuntimeError, ValueError) as exc:
        detail = str(exc.detail) if isinstance(exc, HTTPException) else str(exc)
        quota = is_bedrock_quota_error(RuntimeError(detail)) or "all model providers unavailable" in detail
        invalid = "could not produce a valid workflow" in detail
        if architect.mode != "bedrock" or not (quota or invalid):
            raise
        try:
            with _deterministic_compiler():
                result = _build_once(project_id, request)
        except Exception as retry_exc:  # surface where the template fallback itself failed
            import traceback

            root = retry_exc
            while root.__cause__ is not None:
                root = root.__cause__
            frames = traceback.extract_tb(root.__traceback__)[-6:]
            where = " <- ".join(f"{f.filename.rsplit('/', 1)[-1]}:{f.lineno}:{f.name}" for f in reversed(frames))
            raise RuntimeError(
                f"template fallback failed at {where}: {type(retry_exc).__name__}: {str(retry_exc)[:300]}"
            ) from retry_exc
        reason = (
            "Every AI model provider was out of quota"
            if quota
            else "The AI architect's design failed validation"
        )
        result["degraded_architecture"] = (
            reason + ", so Specloom built this with its validated deterministic compiler. "
            "Details: " + detail[:1500]
        )
        return result


def _build_once(project_id: str, request: BuildRequestBody) -> dict:
    project = store.get(project_id)
    existing_gaps = {
        gap.id: gap for gap in detect_gaps(request.goal, project.graph)
    }

    if request.gap_answers:
        answers = [
            f"Gap {gap_id}: {answer.strip()}"
            for gap_id, answer in request.gap_answers.items()
            if answer.strip()
        ]
        if answers:
            answer_source = ingest_text("Build answers", "\n".join(answers))
            store.add_source(project_id, answer_source)
            project = store.get(project_id)
            requirement_ids = {item.id for item in project.graph.requirements}
            constraint_ids = {item.id for item in project.graph.constraints}
            for gap_id, answer in request.gap_answers.items():
                cleaned = answer.strip()
                gap = existing_gaps.get(gap_id)
                if not cleaned or gap is None:
                    continue
                statement = f"User clarification for {gap_id}: {cleaned}"
                provenance = [
                    Provenance(
                        source_id=answer_source.source.id,
                        locator="build-answer",
                        quote=cleaned[:280],
                        confidence=1.0,
                    )
                ]
                if gap.category == "safety":
                    item = Constraint(
                        id="con_gap_" + gap_id.replace("-", "_"),
                        statement=statement,
                        severity="blocking",
                        provenance=provenance,
                    )
                    if item.id in constraint_ids:
                        project.graph.constraints = [
                            current if current.id != item.id else item
                            for current in project.graph.constraints
                        ]
                    else:
                        project.graph.constraints.append(item)
                        constraint_ids.add(item.id)
                else:
                    item = Requirement(
                        id="req_gap_" + gap_id.replace("-", "_"),
                        statement=statement,
                        priority="high",
                        provenance=provenance,
                    )
                    if item.id in requirement_ids:
                        project.graph.requirements = [
                            current if current.id != item.id else item
                            for current in project.graph.requirements
                        ]
                    else:
                        project.graph.requirements.append(item)
                        requirement_ids.add(item.id)
            store.persist(project_id)

    project = store.get(project_id)
    project.graph = analyze_sources(project.graph, project.documents)
    project.graph = system_planner.enrich(request.goal, project.graph)
    problem_decomposition = None
    if request.autonomous:
        problem_decomposition = problem_decomposer.compile(
            goal=request.goal,
            context=project.graph,
            autonomous=True,
        )
        if problem_decomposition is not None:
            project.graph = problem_decomposer.enrich_context(
                project.graph,
                problem_decomposition,
            )
            store.persist(project_id)
    contract_acquisition = None
    if request.autonomous:
        project.graph, contract_acquisition = contract_acquirer.acquire(
            request.goal,
            project.graph,
            project.documents,
        )
        if contract_acquisition.acquired_documents:
            project.documents.update(contract_acquisition.acquired_documents)
        if contract_acquisition.acquired_documents or contract_acquisition.acquired_capabilities:
            store.persist(project_id)

    project = store.get(project_id)
    project.graph = universal_compiler.prepare(
        request.goal,
        project.graph,
        autonomous=request.autonomous,
        problem_decomposition=problem_decomposition,
    )
    gaps = detect_gaps(request.goal, project.graph)
    assumption_decisions = []
    if request.autonomous:
        project.graph, assumption_decisions = assumption_resolver.resolve(
            request.goal,
            project.graph,
            gaps,
        )
        if assumption_decisions:
            store.persist(project_id)
            gaps = detect_gaps(request.goal, project.graph)

    research_plan = research_planner.plan(
        request.goal,
        project.graph,
        gaps,
    )
    research_execution = ResearchExecutionResult(status="completed")
    if (
        request.autonomous
        and research_execution_mode == "bedrock"
        and research_plan.tasks
    ):
        server_names = [
            item.strip()
            for item in os.getenv("SPECL00M_RESEARCH_MCP_SERVERS", "").split(",")
            if item.strip()
        ]
        if server_names:
            research_execution = BedrockResearchExecutor().execute(
                research_plan,
                project.graph,
                mcp_servers=server_names,
            )
            project.graph = apply_research_evidence(
                project.graph,
                research_execution,
            )
            store.persist(project_id)

            project.graph, research_contract_acquisition = contract_acquirer.acquire(
                request.goal,
                project.graph,
                project.documents,
            )
            contract_acquisition = research_contract_acquisition
            if research_contract_acquisition.acquired_documents:
                project.documents.update(research_contract_acquisition.acquired_documents)
            if (
                research_contract_acquisition.acquired_documents
                or research_contract_acquisition.acquired_capabilities
            ):
                store.persist(project_id)
            project = store.get(project_id)
            project.graph = universal_compiler.prepare(
                request.goal,
                project.graph,
                autonomous=request.autonomous,
                problem_decomposition=problem_decomposition,
            )
            gaps = detect_gaps(request.goal, project.graph)
            if assumption_decisions:
                project.graph, assumption_decisions = assumption_resolver.resolve(
                    request.goal,
                    project.graph,
                    gaps,
                )
                if assumption_decisions:
                    store.persist(project_id)
                    gaps = detect_gaps(request.goal, project.graph)

    if any(gap.severity == "blocking" for gap in gaps):
        return {
            "project_id": project_id,
            "ready": False,
            "architect_mode": architect.mode,
            "gaps": [gap.__dict__ for gap in gaps],
            "synthesized_capabilities": [
                capability.model_dump(mode="json")
                for capability in project.graph.capabilities
                if capability.kind == "synthesized"
            ],
            "research_plan": research_plan.model_dump(mode="json"),
            "assumptions": project.graph.assumptions,
            "contract_acquisition": contract_acquisition.__dict__ if contract_acquisition is not None else None,
        }

    review_mode = os.getenv("SPECL00M_REVIEW_MODE", "none").lower()
    max_revisions = 3 if architect.mode == "bedrock" else 0
    review: ArchitectureReview | None = None
    evaluation = None
    plan = None
    workflow = None
    architecture_search = None
    last_findings: list[dict] = []
    revision_count = 0

    try:
        search_mode = os.getenv("SPECL00M_ARCHITECT_SEARCH_MODE", "off").lower()
        seed_workflow = None
        if search_mode in {"bedrock", "on", "true"} and architect.mode == "bedrock":
            architecture_reviewer = (
                BedrockArchitectureReviewer()
                if review_mode == "bedrock"
                else None
            )
            architecture_search = ArchitectureHypothesisSearcher(
                architect,
                candidate_count=int(
                    os.getenv("SPECL00M_ARCHITECT_CANDIDATES", "3")
                ),
            ).search(
                request=BuildRequest(
                    goal=request.goal,
                    project_id=project_id,
                ),
                context=project.graph,
                reviewer=architecture_reviewer,
            )
            seed_workflow = architecture_search.selected.workflow

        degraded_architecture = None
        try:
            if seed_workflow is None and architect.mode == "bedrock" and bedrock_quota_recently_exhausted():
                raise BedrockQuotaExhausted()
            workflow = seed_workflow or architect.build(
                BuildRequest(goal=request.goal, project_id=project_id),
                project.graph,
            )
        except Exception as exc:
            if is_bedrock_quota_error(exc):
                mark_bedrock_quota_exhausted()
            if architect.mode == "bedrock" and is_bedrock_quota_error(exc) and os.getenv(
                "SPECL00M_ARCHITECT_FALLBACK", "showcase"
            ).lower() in {"showcase", "deterministic", "on", "true"}:
                from backend.workflow.templates import deterministic_goal_template

                workflow = deterministic_goal_template(
                    goal=request.goal,
                    context=project.graph,
                )
                degraded_architecture = (
                    "Bedrock quota/throughput unavailable; Specloom used its "
                    "deterministic validated architecture fallback."
                )
                # Never invoke Bedrock again for revisions in this build.
                max_revisions = 0
            else:
                raise
        workflow, _ = auto_bind_required_capabilities(
            workflow,
            project.graph,
            goal=request.goal,
            problem_decomposition=problem_decomposition,
        )
        workflow = bind_capabilities(workflow, project.graph)

        for attempt in range(max_revisions + 1):
            workflow = bind_capabilities(workflow, project.graph)
            validation_errors = validate_workflow(workflow)
            validation_errors.extend(
                validate_architecture_coverage(workflow, project.graph)
            )
            validation_errors.extend(
                validate_capability_bindings(workflow, project.graph)
            )
            if validation_errors:
                if attempt >= max_revisions:
                    raise ValueError(
                        "compiler rejected architecture: "
                        + "; ".join(validation_errors)
                    )
                last_findings = _revision_findings(
                    validation_errors=validation_errors,
                    evaluation=None,
                    review=None,
                )
                workflow = architect.revise(
                    BuildRequest(goal=request.goal, project_id=project_id),
                    project.graph,
                    workflow,
                    last_findings,
                )
                workflow, _ = auto_bind_required_capabilities(
                    workflow,
                    project.graph,
                    goal=request.goal,
                    problem_decomposition=problem_decomposition,
                )
                revision_count += 1
                continue

            workflow = augment_with_generated_tests(
                workflow,
                project.graph,
            )
            validation_errors = validate_workflow(workflow)
            validation_errors.extend(
                validate_architecture_coverage(workflow, project.graph)
            )
            validation_errors.extend(
                validate_capability_bindings(workflow, project.graph)
            )
            if validation_errors:
                if attempt >= max_revisions:
                    raise ValueError(
                        "compiler rejected architecture: "
                        + "; ".join(validation_errors)
                    )
                last_findings = _revision_findings(
                    validation_errors=validation_errors,
                    evaluation=None,
                    review=None,
                )
                workflow = architect.revise(
                    BuildRequest(goal=request.goal, project_id=project_id),
                    project.graph,
                    workflow,
                    last_findings,
                )
                workflow, _ = auto_bind_required_capabilities(
                    workflow,
                    project.graph,
                    goal=request.goal,
                )
                revision_count += 1
                continue

            plan = compile_workflow(workflow)
            evaluation = Evaluator().evaluate(workflow)
            if evaluation.status == "failed":
                if attempt >= max_revisions:
                    failed = [
                        item.message
                        for item in evaluation.tests
                        if item.status == "failed"
                    ]
                    raise ValueError(
                        "generated proof suite failed: " + "; ".join(failed)
                    )
                last_findings = _revision_findings(
                    validation_errors=[],
                    evaluation=evaluation,
                    review=None,
                )
                workflow = architect.revise(
                    BuildRequest(goal=request.goal, project_id=project_id),
                    project.graph,
                    workflow,
                    last_findings,
                )
                workflow, _ = auto_bind_required_capabilities(
                    workflow,
                    project.graph,
                    goal=request.goal,
                )
                revision_count += 1
                continue

            if review_mode == "bedrock":
                review = BedrockArchitectureReviewer().review(
                    goal=request.goal,
                    context=project.graph,
                    workflow=workflow,
                )
                blocking = [
                    item.model_dump(mode="json")
                    for item in review.findings
                    if item.severity == "blocking"
                ]
                if blocking:
                    if attempt >= max_revisions:
                        raise ValueError(
                            "semantic review rejected the architecture after "
                            f"{max_revisions} revision(s): "
                            + "; ".join(item["message"] for item in blocking)
                        )
                    last_findings = blocking
                    workflow = architect.revise(
                        BuildRequest(goal=request.goal, project_id=project_id),
                        project.graph,
                        workflow,
                        blocking,
                    )
                    revision_count += 1
                    continue
            else:
                review = ArchitectureReview(
                    status="passed",
                    summary=(
                        "Deterministic compiler and proof suite passed; "
                        "semantic review disabled."
                    ),
                    findings=[],
                )

            workflow = augment_with_generated_tests(
                workflow,
                project.graph,
            )
            plan = compile_workflow(workflow)
            store.save_workflow(project_id, workflow)
            break

        if workflow is None or plan is None or evaluation is None:
            raise ValueError("compiler did not produce a promotable workflow")

        bundle = universal_compiler.compile(
            request.goal,
            project.graph,
            workflow,
            autonomous=request.autonomous,
            problem_decomposition=problem_decomposition,
        )
        blocking_artifacts = [
            item
            for item in bundle.diagnostics
            if item.severity == "blocking"
        ]
        if blocking_artifacts:
            raise ValueError(
                "software artifact compilation failed: "
                + "; ".join(item.message for item in blocking_artifacts)
            )

        verification = _augment_semantic_verification(
            sandbox_verifier.verify(bundle.artifacts),
            bundle.artifacts,
            acceptance_proven=bundle.spec.acceptance_proven,
            acceptance_reviewed=bundle.spec.acceptance_reviewed,
            acceptance_origin=bundle.spec.acceptance_origin,
            unverified_criteria=bundle.spec.acceptance_unverified_criteria,
        )
        software_repair_count = 0
        software_repair_findings: list[str] = []

        if verification["status"] != "passed":
            if architect.mode != "bedrock":
                raise ValueError(
                    "generated software verification failed: "
                    + "; ".join(verification["errors"])
                )

            repaired_artifacts, repaired_verification, software_repair_count, software_repair_findings = (
                SoftwareRepairEngine(
                    repairer=BedrockSoftwareRepairer(),
                    verifier=sandbox_verifier,
                    max_attempts=2,
                ).repair(
                    goal=request.goal,
                    context=project.graph,
                    workflow=workflow,
                    artifacts=bundle.artifacts,
                )
            )
            bundle.artifacts = repaired_artifacts
            verification = _augment_semantic_verification(
                repaired_verification,
                bundle.artifacts,
                acceptance_proven=bundle.spec.acceptance_proven,
                acceptance_reviewed=bundle.spec.acceptance_reviewed,
                acceptance_origin=bundle.spec.acceptance_origin,
                unverified_criteria=bundle.spec.acceptance_unverified_criteria,
            )

            if verification["status"] != "passed":
                raise ValueError(
                    "generated software verification failed after autonomous repair: "
                    + "; ".join(verification["errors"])
                )

        bundle.verification = dict(verification)

        staging_mode = ("container" if request.require_staging else os.getenv("SPECL00M_STAGING_MODE", "none")).lower()
        staging_result = {"status": "skipped", "mode": staging_mode}
        staging_repair_count = 0
        if staging_mode == "container":
            for staging_attempt in range(3):
                try:
                    staging_result = dict(
                        StagingContainerExecutor().execute(bundle.artifacts)
                    )
                    break
                except RuntimeError as exc:
                    staging_result = {
                        "status": "failed",
                        "mode": "container",
                        "error": str(exc),
                    }
                    if architect.mode != "bedrock" or staging_attempt >= 2:
                        raise ValueError(
                            f"staging execution failed: {exc}"
                        ) from exc

                    repaired_artifacts, repaired_verification, attempts, repair_findings = (
                        SoftwareRepairEngine(
                            repairer=BedrockSoftwareRepairer(),
                            verifier=sandbox_verifier,
                            max_attempts=1,
                        ).repair(
                            goal=request.goal,
                            context=project.graph,
                            workflow=workflow,
                            artifacts=bundle.artifacts,
                            initial_verification={
                                "status": "failed",
                                "errors": [str(exc)],
                                "checked_artifacts": len(bundle.artifacts),
                                "executed_contract": False,
                            },
                        )
                    )
                    bundle.artifacts = repaired_artifacts
                    verification = _augment_semantic_verification(
                        repaired_verification,
                        bundle.artifacts,
                        acceptance_proven=bundle.spec.acceptance_proven,
                        acceptance_reviewed=bundle.spec.acceptance_reviewed,
                        acceptance_origin=bundle.spec.acceptance_origin,
                        unverified_criteria=bundle.spec.acceptance_unverified_criteria,
                    )
                    bundle.verification = dict(verification)
                    staging_repair_count += attempts
                    software_repair_findings.extend(repair_findings)
                    if repaired_verification.get("status") != "passed":
                        raise ValueError(
                            "staging failure could not be repaired: "
                            + "; ".join(
                                str(item)
                                for item in repaired_verification.get("errors", [])
                            )
                        )
            else:
                raise ValueError("staging execution did not complete")
        elif staging_mode != "none":
            raise ValueError(
                "SPECL00M_STAGING_MODE must be none or container"
            )

        # Rebuild the authoritative deployment plan after every possible
        # source/config mutation, including autonomous staging repairs.
        deployable_artifacts = [
            item
            for item in bundle.artifacts
            if item.path != "generated/deploy/deployment-plan.json"
        ]
        final_deployment_plan = DeploymentCompiler().compile(
            bundle.spec,
            deployable_artifacts,
            provisioning_ready=bool(bundle.provisioning.get("ready", False)),
        )
        deployment_artifact = Artifact(
            path="generated/deploy/deployment-plan.json",
            kind="infrastructure",
            content=(
                json.dumps(
                    final_deployment_plan.model_dump(mode="json"),
                    indent=2,
                    sort_keys=True,
                )
                + "\n"
            ),
            generated_from=[bundle.spec.id],
        ).with_hash()
        bundle.artifacts = [*deployable_artifacts, deployment_artifact]
        bundle.deployment = final_deployment_plan.model_dump(mode="json")
        bundle.verification = dict(verification)

        final_hashes = {item.path: item.sha256 for item in bundle.artifacts}
        final_digest = artifact_digest(
            bundle.artifacts,
            exclude_paths={"generated/deploy/deployment-plan.json"},
        )
        production_ready = (
            bool(final_deployment_plan.production_allowed)
            and staging_result.get("status") == "passed"
            and verification.get("status") == "passed"
        )
        build_run_id = f"build_{uuid.uuid4().hex}"
        store.record_run(
            project_id,
            {
                "run_id": build_run_id,
                "kind": "build",
                "status": "production_ready" if production_ready else "verified",
                "created_at": datetime.now(timezone.utc).isoformat(),
                "artifact_digest": final_digest,
                "artifact_hashes": final_hashes,
                "software_verification": dict(verification),
                "semantic_proof": bool(verification.get("semantic_proof", False)),
                "acceptance_proven": bundle.spec.acceptance_proven,
                "staging": dict(staging_result),
                "deployment_plan": final_deployment_plan.model_dump(mode="json"),
                "implementation_materialized": bundle.spec.implementation_materialized,
                "production_ready": production_ready,
                "repair_count": software_repair_count + staging_repair_count,
            },
        )
        store.save_artifacts(project_id, bundle.artifact_map())

    except (RuntimeError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    return {
        "project_id": project_id,
        "architect_mode": architect.mode,
        "system_planner_mode": system_planner.mode,
        "research_planner": research_planner.__class__.__name__,
        "research_plan": research_plan.model_dump(mode="json"),
        "research_execution_mode": research_execution_mode,
        "research_execution": research_execution.model_dump(mode="json"),
        "problem_decomposition": (
            problem_decomposition.model_dump(mode="json")
            if problem_decomposition is not None
            else None
        ),
        "contract_acquisition": contract_acquisition.__dict__ if contract_acquisition is not None else None,
        "assumptions": project.graph.assumptions,
        "review_mode": review_mode,
        "review": review.model_dump(mode="json") if review else None,
        "degraded_architecture": degraded_architecture,
        "architecture_search": (
            {
                "candidate_count": len(architecture_search.candidates),
                "selected_index": architecture_search.selected.index,
                "candidates": [
                    {
                        "index": item.index,
                        "score": item.score,
                        "validation_errors": list(item.validation_errors),
                        "evidence": item.evidence,
                    }
                    for item in architecture_search.candidates
                ],
            }
            if architecture_search
            else None
        ),
        "evaluation": evaluation.model_dump(mode="json"),
        "capabilities": [
            item.model_dump(mode="json")
            for item in project.graph.capabilities
        ],
        "synthesized_capabilities": [
            item.model_dump(mode="json")
            for item in project.graph.capabilities
            if item.kind == "synthesized"
        ],
        "workflow": workflow.model_dump(mode="json"),
        "system_ir": bundle.system_ir,
        "software_spec": bundle.spec.model_dump(mode="json"),
        "artifact_status": {
            "count": len(bundle.artifacts),
            "ready_for_runtime": bundle.ready_for_runtime,
            "requires_provisioning": bundle.requires_provisioning,
            "diagnostics": [
                item.model_dump(mode="json")
                for item in bundle.diagnostics
            ],
        },
        "software_verification": bundle.verification,
        "staging": staging_result,
        "deployment": bundle.deployment,
        "production_ready": bool(bundle.deployment.get("production_allowed", False)) and staging_result.get("status") == "passed",
        "provisioning": bundle.provisioning,
        "capability_bindings": bundle.capability_bindings,
        "dependencies": bundle.dependencies,
        "software_repair_count": software_repair_count + staging_repair_count,
        "software_repair_findings": software_repair_findings,
        "artifacts": [
            {
                "path": item.path,
                "kind": item.kind,
                "sha256": item.sha256,
                "executable": item.executable,
                "generated_from": item.generated_from,
            }
            for item in bundle.artifacts
        ],
        "version": len(store.get(project_id).workflow_versions),
        "ready": True,
        "gaps": [],
        "execution_plan": {
            "workflow_id": plan.workflow_id,
            "ordered_nodes": [node.__dict__ for node in plan.ordered_nodes],
        },
        "repair_count": revision_count,
        "last_revision_findings": last_findings,
    }



class AsyncBuildRequest(BaseModel):
    goal: str = Field(min_length=10, max_length=5000)
    gap_answers: dict[str, str] = Field(default_factory=dict)


def _build_job(project_id: str, run_id: str) -> dict | None:
    return _autobuild_run(project_id, run_id) or next(
        (item for item in store.get(project_id).runs if item.get("run_id") == run_id),
        None,
    )


@router.post("/{project_id}/build/async", status_code=202)
def start_async_build(project_id: str, request: AsyncBuildRequest) -> dict:
    run_id = uuid.uuid4().hex
    now = datetime.now(timezone.utc).isoformat()
    state = {
        "run_id": run_id,
        "project_id": project_id,
        "kind": "build_job",
        "status": "queued",
        "current_stage": "queued",
        "goal": request.goal,
        "gap_answers": dict(request.gap_answers),
        "created_at": now,
        "updated_at": now,
    }
    # Keep the normal run history, but use a dedicated durable job record for
    # cross-Lambda polling.
    store.record_run(project_id, state)
    build_jobs.put(state)

    function_name = os.getenv("AWS_LAMBDA_FUNCTION_NAME")
    if function_name:
        try:
            import boto3
            boto3.client("lambda").invoke(
                FunctionName=function_name,
                InvocationType="Event",
                Payload=json.dumps({
                    "source": "specloom.build",
                    "detail": {
                        "project_id": project_id,
                        "run_id": run_id,
                        "goal": request.goal,
                        "gap_answers": request.gap_answers,
                    },
                }).encode("utf-8"),
            )
        except Exception as exc:
            build_jobs.update(
                project_id,
                run_id,
                status="failed",
                current_stage="queue",
                error=f"Could not queue background build: {exc}",
            )
            raise HTTPException(status_code=503, detail="Could not queue background build") from exc

        return {"project_id": project_id, "run_id": run_id, "status": "queued"}

    # Local/dev fallback: preserve one API contract while running synchronously.
    try:
        result = build(
            project_id,
            BuildRequestBody(goal=request.goal, gap_answers=request.gap_answers),
        )
    except HTTPException as exc:
        build_jobs.update(
            project_id,
            run_id,
            status="failed",
            current_stage="compile",
            error=exc.detail,
        )
        return {"project_id": project_id, "run_id": run_id, "status": "failed", "error": exc.detail}
    build_jobs.update(
        project_id,
        run_id,
        status="completed",
        current_stage="complete",
        build=result,
    )
    return {"project_id": project_id, "run_id": run_id, "status": "completed", "build": result}

@router.get("/{project_id}/build/jobs/{run_id}")
def get_async_build(project_id: str, run_id: str) -> dict:
    job = build_jobs.get(project_id, run_id)
    if job is None:
        raise HTTPException(status_code=404, detail="build job not found")
    return job

def get_async_build(project_id: str, run_id: str) -> dict:
    job = _build_job(project_id, run_id)
    if job is None or job.get("kind") != "build_job":
        raise HTTPException(status_code=404, detail="build job not found")
    return job
