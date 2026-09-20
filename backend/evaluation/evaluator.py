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

        if "condition_covered" in expected:
            node_id = str(expected["condition_covered"])
            node = next((item for item in ir.nodes if item.id == node_id), None)
            branches = [
                edge for edge in ir.edges
                if edge.get("from") == node_id
                and (edge.get("condition") is not None or edge.get("label") is not None)
            ]
            expected_count = int(expected.get("branch_count", 0))
            return (
                node is not None and node.type == "condition" and len(branches) == expected_count and expected_count >= 2,
                f"condition {node_id} exposes {len(branches)} labeled branch(es)",
                {"condition_id": node_id, "branch_count": len(branches)},
            )

        if "parallel_covered" in expected:
            node_id = str(expected["parallel_covered"])
            node = next((item for item in ir.nodes if item.id == node_id), None)
            branches = node.config.get("branches", []) if node else []
            expected_count = int(expected.get("branch_count", 0))
            return (
                node is not None and node.type == "parallel" and isinstance(branches, list)
                and len(branches) == expected_count and expected_count >= 2,
                f"parallel {node_id} exposes {len(branches) if isinstance(branches, list) else 0} branch(es)",
                {"parallel_id": node_id, "branch_count": len(branches) if isinstance(branches, list) else 0},
            )

        if "loop_bounded" in expected:
            node_id = str(expected["loop_bounded"])
            node = next((item for item in ir.nodes if item.id == node_id), None)
            maximum = node.config.get("max_iterations") if node else None
            expected_maximum = expected.get("max_iterations")
            valid = (
                node is not None
                and node.type == "loop"
                and isinstance(maximum, int)
                and 1 <= maximum <= 1000
                and maximum == expected_maximum
            )
            return (
                valid,
                f"loop {node_id} has max_iterations={maximum}",
                {"loop_id": node_id, "max_iterations": maximum},
            )

        if "approval_waits_for" in expected:
            node_id = str(expected["approval_waits_for"])
            node = next((item for item in ir.nodes if item.id == node_id), None)
            valid = node is not None and node.type == "human_approval"
            return (
                valid,
                f"approval node {node_id} is present" if valid else f"approval node {node_id} missing",
                {"approval_node": node_id},
            )

        if "terminal_output" in expected:
            node_id = str(expected["terminal_output"])
            node = next((item for item in ir.nodes if item.id == node_id), None)
            outgoing = [
                edge for edge in ir.edges
                if edge.get("from") == node_id
            ]
            valid = node is not None and node.type == "output" and not outgoing
            return (
                valid,
                f"output {node_id} is terminal" if valid else f"output {node_id} is not terminal",
                {"output_node": node_id},
            )

        if "approval_required_for" in expected:
            target = str(expected["approval_required_for"])
            validation_errors = validate_workflow(ir)
            node = next((item for item in ir.nodes if item.id == target), None)
            capability = node.config.get("capability") if node else None
            if isinstance(capability, dict) and "side_effecting" in capability:
                side_effecting = bool(capability.get("side_effecting"))
            else:
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

        known = {
            "status",
            "github_called",
            "issues_created",
            "result_produced",
            "classification",
            "drafted",
            "briefed",
            "requirement_covered",
            "constraint_covered",
            "condition_covered",
            "parallel_covered",
            "loop_bounded",
            "approval_waits_for",
            "terminal_output",
            "approval_required_for",
        }
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

        if "result_produced" in expected:
            # A result exists only when the workflow reaches a terminal output
            # node. Waiting at human approval must not count as produced output.
            produced = (
                result.status == "passed"
                and any(
                    event.node_type == "output" and event.status == "completed"
                    for event in result.events
                )
            )
            if produced != bool(expected["result_produced"]):
                return (
                    False,
                    f"expected result_produced={expected['result_produced']}, got {produced}",
                )

        if "classification" in expected:
            expected_classification = str(expected["classification"]).strip().lower()
            classifiers = [
                node for node in ir.nodes
                if node.type == "agent"
                and (
                    "classif" in node.name.lower()
                    or "classif" in str(node.config.get("role", "")).lower()
                )
            ]
            valid = bool(classifiers) and any(
                expected_classification in str(node.config.get("role", "")).lower()
                or expected_classification in node.name.lower()
                for node in classifiers
            )
            return (
                valid,
                (
                    f"classification capability is represented by {classifiers[0].id}"
                    if valid
                    else f"classification capability for {expected_classification} is missing"
                ),
                {
                    "expected_classification": expected_classification,
                    "classifier_nodes": [node.id for node in classifiers],
                },
            )

        if "drafted" in expected:
            drafting_nodes = [
                node for node in ir.nodes
                if node.type == "agent"
                and (
                    "draft" in node.name.lower()
                    or "draft" in str(node.config.get("role", "")).lower()
                )
            ]
            valid = bool(drafting_nodes) == bool(expected["drafted"])
            return (
                valid,
                (
                    f"draft response capability is represented by {drafting_nodes[0].id}"
                    if valid
                    else "draft response capability is missing"
                ),
                {"draft_nodes": [node.id for node in drafting_nodes]},
            )

        if "briefed" in expected:
            briefing_nodes = [
                node for node in ir.nodes
                if node.type == "agent"
                and (
                    "brief" in node.name.lower()
                    or "brief" in str(node.config.get("role", "")).lower()
                    or "summar" in str(node.config.get("role", "")).lower()
                )
            ]
            valid = bool(briefing_nodes) == bool(expected["briefed"])
            return (
                valid,
                (
                    f"briefing capability is represented by {briefing_nodes[0].id}"
                    if valid
                    else "briefing capability is missing"
                ),
                {"briefing_nodes": [node.id for node in briefing_nodes]},
            )

        return True, "all expectations satisfied"
