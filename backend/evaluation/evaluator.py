from __future__ import annotations

from typing import Any

from backend.simulation.executor import Simulator
from backend.workflow.models import WorkflowIR

from .models import EvaluationResult, TestResult

class Evaluator:
    def __init__(self, simulator: Simulator | None = None) -> None:
        self.simulator = simulator or Simulator()

    def evaluate(self, ir: WorkflowIR) -> EvaluationResult:
        results: list[TestResult] = []

        for test in ir.tests:
            test_id = str(test["id"])
            name = str(test["name"])
            result = self.simulator.run(ir, test.get("input", {}))
            passed, message = self._assert_expected(result, test.get("expected", {}))
            results.append(
                TestResult(
                    test_id=test_id,
                    name=name,
                    status="passed" if passed else "failed",
                    message=message,
                    simulation_status=result.status,
                    evidence={
                        "events": [event.model_dump(mode="json") for event in result.events],
                        "output": result.output,
                        "failed_node": result.failed_node,
                        "error": result.error,
                    },
                )
            )

        failed = sum(item.status == "failed" for item in results)
        return EvaluationResult(
            workflow_id=ir.id,
            status="failed" if failed else "passed",
            tests=results,
            passed=len(results) - failed,
            failed=failed,
        )

    @staticmethod
    def _assert_expected(result: Any, expected: dict[str, Any]) -> tuple[bool, str]:
        if "status" in expected and result.status != expected["status"]:
            return False, f"expected status {expected['status']}, got {result.status}"

        if "github_called" in expected:
            called = any(
                event.node_type == "tool"
                and event.status == "completed"
                and "GitHub" in event.message
                for event in result.events
            )
            if called != bool(expected["github_called"]):
                return False, f"expected github_called={expected['github_called']}, got {called}"

        if "issues_created" in expected:
            actual = (result.output or {}).get("issues_created")
            if actual != expected["issues_created"]:
                return False, f"expected issues_created={expected['issues_created']}, got {actual}"

        return True, "all expectations satisfied"
