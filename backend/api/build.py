from __future__ import annotations

import os

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from backend.agents.architect import BuildRequest, ConfiguredArchitect
from backend.agents.reviewer import ArchitectureReview, BedrockArchitectureReviewer
from backend.capabilities.bindings import bind_capabilities, validate_capability_bindings
from backend.compiler.assumptions import AutonomousAssumptionResolver
from backend.compiler.planner import ConfiguredSystemPlanner
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
research_planner = configured_research_planner()
research_execution_mode = os.getenv("SPECL00M_RESEARCH_EXECUTION_MODE", "off").lower()


class BuildRequestBody(BaseModel):
    goal: str = Field(min_length=10, max_length=5000)
    gap_answers: dict[str, str] = Field(default_factory=dict)
    autonomous: bool = False


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


@router.post("/{project_id}/build")
def build(project_id: str, request: BuildRequestBody) -> dict:
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
    project.graph = universal_compiler.prepare(request.goal, project.graph)
    store.persist(project_id)

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
    if research_execution_mode == "bedrock" and not any(
        gap.severity == "blocking" for gap in gaps
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
        }

    review_mode = os.getenv("SPECL00M_REVIEW_MODE", "none").lower()
    max_revisions = 3 if architect.mode == "bedrock" else 0
    review: ArchitectureReview | None = None
    evaluation = None
    plan = None
    workflow = None
    last_findings: list[dict] = []
    revision_count = 0

    try:
        workflow = architect.build(
            BuildRequest(goal=request.goal, project_id=project_id),
            project.graph,
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

        verification = sandbox_verifier.verify(bundle.artifacts)
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
            verification = repaired_verification

            if verification["status"] != "passed":
                raise ValueError(
                    "generated software verification failed after autonomous repair: "
                    + "; ".join(verification["errors"])
                )

        bundle.verification = dict(verification)

        staging_mode = os.getenv("SPECL00M_STAGING_MODE", "none").lower()
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
        "assumptions": project.graph.assumptions,
        "review_mode": review_mode,
        "review": review.model_dump(mode="json") if review else None,
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
