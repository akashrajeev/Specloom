from __future__ import annotations

from backend.compiler.repository import RepositoryCompiler
from backend.compiler.sandbox import SandboxVerifier
from backend.compiler.system_ir import SystemCompiler
from backend.compiler.models import ServiceSpec, DataModelSpec
from backend.context.models import ContextGraph, Requirement, ContextEntity
from backend.workflow.models import Trigger, WorkflowIR, Node


def _context() -> ContextGraph:
    return ContextGraph(
        requirements=[
            Requirement(id="req-1", statement="Users can submit a request", priority="high"),
        ],
        entities=[ContextEntity(id="entity-1", type="record", name="Request")],
    )


def _workflow() -> WorkflowIR:
    return WorkflowIR(
        ir_version="0.1",
        id="wf-system-test",
        name="System test",
        description="compiler test",
        trigger=Trigger(
            id="trigger",
            type="trigger",
            name="Manual",
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
        edges=[{"from": "trigger", "to": "output"}],
        variables=[],
        policies=[],
        tests=[],
    )


def test_system_ir_contains_acceptance_and_security():
    context = _context()
    workflow = _workflow()
    system = SystemCompiler().compile(
        "Build a request service",
        context,
        workflow,
        [ServiceSpec(id="api", name="API", runtime="python")],
        [DataModelSpec(name="Request", fields=[{"name": "id", "type": "string"}])],
    )

    assert system.workflow_id == workflow.id
    assert system.acceptance_criteria
    assert system.security.authorization == "least-privilege"
    assert system.data_models


def test_repository_and_sandbox_execute_generated_contract():
    context = _context()
    workflow = _workflow()
    system = SystemCompiler().compile(
        "Build a request service",
        context,
        workflow,
        [],
        [],
    )
    files = RepositoryCompiler().compile(system, workflow, context)

    result = SandboxVerifier().verify(files)

    assert result["status"] == "passed"
    assert result["executed_contract"] is True
    assert result["executed_acceptance"] is True
    assert result["errors"] == []


def test_repository_compiler_generates_full_stack_surfaces():
    context = _context()
    workflow = _workflow()
    system = SystemCompiler().compile(
        "Build a request dashboard application",
        context,
        workflow,
        [],
        [DataModelSpec(name="Request", fields=[{"name": "id", "type": "string"}])],
    )
    files = RepositoryCompiler().compile(system, workflow, context)
    paths = {item.path for item in files}

    assert "generated/repository/app/domain.py" in paths
    assert "generated/repository/app/persistence.py" in paths
    assert "generated/repository/migrations/001_initial.sql" in paths
    assert "generated/repository/web/package.json" in paths
    assert "generated/repository/web/src/App.tsx" in paths
    assert "generated/repository/web/src/main.tsx" in paths
    assert "generated/repository/web/tsconfig.json" in paths
