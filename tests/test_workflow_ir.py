from pathlib import Path
from backend.workflow.loader import load_workflow
from backend.workflow.validator import validate_workflow

def test_showcase_workflow_loads_and_validates():
    ir = load_workflow(Path("examples/showcase-workflow.json"))
    assert validate_workflow(ir) == []

def test_expected_node_types_present():
    ir = load_workflow("examples/showcase-workflow.json")
    types = {n.type for n in ir.nodes}
    assert {"agent", "tool", "human_approval", "output"} <= types
