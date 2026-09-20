from __future__ import annotations

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
        }
        for item in results
        if not item.compiled
    ]
    assert not failed, failed

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
