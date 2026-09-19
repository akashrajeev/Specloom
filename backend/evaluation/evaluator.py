from __future__ import annotations

from typing import Any

from backend.context.models import ContextGraph
from backend.tools.registry import registry
from backend.workflow.models import WorkflowIR
from backend.workflow.validator import validate_workflow

from .models import EvaluationResult, TestResult
from . import testgen


class Evaluator:
    def __init__(self, simulator=None) -> None:
        from backend.simulation.executor import Simulator
        self.simulator = simulator or Simulator()

    def evaluate(self, ir: WorkflowIR) -> EvaluationResult:
        results: list[TestResult] = []

        for test in ir.tests:
            test_id = str(test["id"])
            name = str(test["name"])
            expected = test.get("expected", {})

            static = self._evaluate_static(ir, expected)
            if static is not None:
                passed, message, evidence = static
                results.append(
                    TestResult(
                        test_id=test_id,
                        name=name,
                        status="passed" if passed else "failed",
                        message=message,
                        simulation_status="passed",
                        evidence=evidence,
                    )
                )
                continue

            result = self.simulator.run(ir, test.get("input", {}))
            passed, message = self._assert_expected(result, expected)
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
    def _evaluate_static(
        ir: WorkflowIR,
        expected: dict[str, Any],
    ) -> tuple[bool, str, dict[str, Any]] | None:
        if "requirement_covered" in expected:
            requirement_id = str(expected["requirement_covered"])
            matched = [
                node.id
                for node in ir.nodes
                if requirement_id in [str(value) for value in node.config.get("requirement_refs", [])]
            ]
            return (
                bool(matched),
                f"requirement {requirement_id} covered by {matched or 'no nodes'}",
                {"requirement_id": requirement_id, "covered_by": matched},
            )

        if "constraint_covered" in expected:
            constraint_id = str(expected["constraint_covered"])
            matched = [
                node.id
                for node in ir.nodes
                if constraint_id in [str(value) for value in node.config.get("constraint_refs", [])]
            ]
            return (
                bool(matched),
                f"constraint {constraint_id} covered by {matched or 'no nodes'}",
                {"constraint_id": constraint_id, "covered_by": matched},
            )

        if "approval_required_for" in expected:
            target = str(expected["approval_required_for"])
            validation_errors = validate_workflow(ir)
            node = next((item for item in ir.nodes if item.id == target), None)
            try:
                side_effecting = bool(node) and bool(registry.get(str(node.config.get("tool_ref"))).side_effecting)
            except KeyError:
                side_effecting = False
            return (
                node is not None and side_effecting and not validation_errors,
                (
                    f"approval policy valid for {target}"
                    if node is not None and side_effecting and not validation_errors
                    else f"approval policy invalid for {target}"
                ),
                {"target_node": target, "validation_errors": validation_errors},
            )

        known = {"status", "github_called", "issues_created"}
        unknown = set(expected) - known
        if unknown:
            return (
                False,
                "unsupported expectation(s): " + ", ".join(sorted(str(item) for item in unknown)),
                {"unsupported_expectations": sorted(str(item) for item in unknown)},
            )

        return None

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
