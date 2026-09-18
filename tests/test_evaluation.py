from copy import deepcopy

from backend.evaluation.evaluator import Evaluator
from backend.evaluation.repairer import Repairer
from backend.simulation.executor import Simulator
from backend.workflow.loader import load_workflow
from backend.workflow.models import WorkflowIR


def test_showcase_evaluation_passes():
    ir = load_workflow("examples/showcase-workflow.json")
    result = Evaluator().evaluate(ir)
    assert result.status == "passed"
    assert result.passed == len(ir.tests)


def test_repairer_changes_live_tool_to_sandbox():
    ir = load_workflow("examples/showcase-workflow.json")
    broken = deepcopy(ir)
    broken.nodes[-2].config["mode"] = "live"

    failure = Simulator().run(broken, {"approved": True})
    assert failure.status == "failed"

    repaired = Repairer().repair_from_error(
        broken,
        failed_node=failure.failed_node,
        error=failure.error,
    )
    assert repaired.repaired is True
    assert repaired.patch is not None
    assert repaired.patch.new_value == "sandbox"

    repaired_ir = WorkflowIR.model_validate(repaired.workflow)
    assert repaired_ir.nodes[-2].config["mode"] == "sandbox"
