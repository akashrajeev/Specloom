from __future__ import annotations

from backend.compiler.acceptance import IndependentAcceptanceCompiler
from backend.compiler.models import ServiceSpec
from backend.compiler.repository import RepositoryCompiler
from backend.compiler.system_ir import SystemCompiler
from backend.context.models import ContextExample, ContextGraph, Provenance, Requirement
from backend.workflow.models import Node, Trigger, WorkflowIR


def _workflow():
    return WorkflowIR(
        ir_version="0.1",
        id="acceptance-demo",
        name="Acceptance",
        description="acceptance",
        trigger=Trigger(
            id="start",
            type="trigger",
            name="Start",
            config={"mode": "manual"},
        ),
        nodes=[
            Node(
                id="output",
                type="output",
                name="Output",
                config={},
            )
        ],
        edges=[{"from": "start", "to": "output"}],
        variables=[],
        policies=[],
        tests=[],
    )


def test_independent_acceptance_compiles_user_example():
    workflow = _workflow()
    source = "source-1"
    context = ContextGraph(
        requirements=[
            Requirement(
                id="req-1",
                statement="The system must return the supplied value.",
                priority="high",
                provenance=[
                    Provenance(
                        source_id=source,
                        locator="line:1",
                        quote="The system must return the supplied value.",
                    )
                ],
            )
        ],
        examples=[
            ContextExample(
                id="example-1",
                input={"value": 7},
                expected={"value": 7},
                provenance=[Provenance(source_id=source)],
            )
        ],
    )
    system = SystemCompiler().compile(
        "Return supplied values.",
        context,
        workflow,
        [ServiceSpec(id="runtime", name="Runtime", runtime="python")],
        [],
    )
    artifact, diagnostics, manifest = IndependentAcceptanceCompiler().compile(
        system,
        context,
    )

    assert manifest.cases[0].expected == {"value": 7}
    assert diagnostics
    assert artifact.path.endswith("independent_acceptance.py")
    assert "Acceptance case" in artifact.content


def test_repository_contains_independent_acceptance_script():
    workflow = _workflow()
    system = SystemCompiler().compile(
        "Return supplied values.",
        ContextGraph(),
        workflow,
        [],
        [],
    )
    files = RepositoryCompiler().compile(system, workflow, ContextGraph())
    paths = {item.path for item in files}
    assert "generated/repository/tests/independent_acceptance.py" in paths
    assert "generated/repository/tests/independent-acceptance.json" in paths
