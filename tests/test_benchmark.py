from __future__ import annotations

import json

from backend.compiler.benchmark import (
    DEFAULT_CASES,
    run_benchmark,
    summarize,
)


def test_universal_compiler_benchmark_compiles_representative_problem_classes():
    results = run_benchmark()
    assert len(results) == len(DEFAULT_CASES)
    failed = [
        {
            "case_id": item.case_id,
            "diagnostics": item.diagnostics,
            "architecture": item.architecture,
            "required_families": item.required_families,
            "write_capabilities": item.write_capabilities,
            "unresolved_dependencies": item.unresolved_dependencies,
            "blocking_diagnostics": item.blocking_diagnostics,
            "decomposition_step_count": item.decomposition_step_count,
            "workflow_step_coverage_complete": item.workflow_step_coverage_complete,
            "implementation_plan_step_coverage_complete": item.implementation_plan_step_coverage_complete,
            "implementation_plan_artifact_present": item.implementation_plan_artifact_present,
            "end_to_end_trace_complete": item.end_to_end_trace_complete,
            "production_allowed": item.production_allowed,
        }
        for item in results
        if not item.compiled
    ]
    assert not failed, json.dumps(failed, indent=2, default=str)

    summary = summarize(results)
    assert summary["compile_coverage"] == 1.0
    assert "agent_service" in summary["architectures"]
    assert "api_service" in summary["architectures"]
    assert "application" in summary["architectures"]
    assert "email" in summary["synthesized_families"]
    assert "slack" in summary["synthesized_families"]
    assert "calendar" in summary["synthesized_families"]
    assert "database" in summary["synthesized_families"]
    assert "payments" in summary["synthesized_families"]
    assert "browser" in summary["synthesized_families"]
    assert summary["end_to_end_trace_coverage"] == 1.0
    assert summary["implementation_plan_coverage"] == 1.0


def test_benchmark_proves_access_modes_dependencies_and_artifact_integrity():
    results = run_benchmark()
    by_id = {item.case_id: item for item in results}

    assert by_id["email-read"].compiled
    assert by_id["email-read"].write_capabilities == ()
    assert by_id["storage-write"].compiled
    assert "storage" in by_id["storage-write"].write_capabilities
    assert by_id["external-ticket"].compiled
    assert "external-service" in by_id["external-ticket"].synthesized_families
    assert all(not item.unresolved_dependencies for item in results)
    assert all(item.artifact_hashes_complete for item in results)



def test_benchmark_proves_hidden_capability_families_survive_decomposition():
    by_id = {item.case_id: item for item in run_benchmark()}

    assert by_id["hidden-erp"].compiled
    assert "erp" in by_id["hidden-erp"].required_families
    assert "erp" in by_id["hidden-erp"].synthesized_families
    assert by_id["hidden-erp"].end_to_end_trace_complete

    assert by_id["hidden-crm"].compiled
    assert "crm" in by_id["hidden-crm"].required_families
    assert "crm" in by_id["hidden-crm"].synthesized_families
    assert by_id["hidden-crm"].end_to_end_trace_complete



def test_event_pipeline_benchmark_has_expected_capability_access():
    from backend.compiler.benchmark import run_benchmark

    result = next(
        item for item in run_benchmark()
        if item.case_id == "event-pipeline"
    )

    assert result.architecture == "agent_service"
    assert "storage" in result.required_families
    assert "storage" in result.synthesized_families
    assert result.write_capabilities == ("storage",)
    assert result.unresolved_dependencies == ()
    assert result.artifact_hashes_complete is True
    assert result.blocking_diagnostics == ()
