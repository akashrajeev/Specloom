from __future__ import annotations

from backend.compiler.benchmark import (
    DEFAULT_CASES,
    run_benchmark,
    summarize,
)


def test_universal_compiler_benchmark_compiles_representative_problem_classes():
    results = run_benchmark()
    assert len(results) == len(DEFAULT_CASES)
    assert all(item.compiled for item in results)

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
