from __future__ import annotations

from copy import deepcopy

from backend.workflow.models import WorkflowIR

from .models import IRPatch, RepairResult


class Repairer:
    """Applies only known-safe, bounded IR repairs.

    The first repair rule converts a live side-effecting tool to sandbox mode
    when simulation explicitly blocks the live call.
    """

    def repair_from_error(self, ir: WorkflowIR, *, failed_node: str | None, error: str | None) -> RepairResult:
        if not failed_node or not error:
            return RepairResult(repaired=False)

        if "Live side effects are blocked by the simulator" not in error:
            return RepairResult(repaired=False)

        nodes = deepcopy(ir.nodes)
        for node in nodes:
            if node.id == failed_node and node.type == "tool" and node.config.get("mode") == "live":
                patched = ir.model_copy(deep=True)
                target = next(item for item in patched.nodes if item.id == failed_node)
                target.config["mode"] = "sandbox"

                patch = IRPatch(
                    description="Switch side-effecting tool to sandbox mode for safe simulation.",
                    target_node=failed_node,
                    path="config.mode",
                    old_value="live",
                    new_value="sandbox",
                    rationale="Simulation must not perform production side effects.",
                )
                return RepairResult(
                    repaired=True,
                    patch=patch,
                    workflow=patched.model_dump(mode="json"),
                )

        return RepairResult(repaired=False)
