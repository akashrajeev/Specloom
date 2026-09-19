from __future__ import annotations

import ast

from backend.compiler.repository import RepositoryCompiler
from backend.compiler.runtime_template import RUNTIME_SOURCE
from backend.compiler.sandbox import SandboxVerifier
from backend.compiler.system_ir import SystemCompiler
from backend.compiler.models import ServiceSpec
from backend.context.models import ContextGraph
from backend.workflow.models import Node, Trigger, WorkflowIR


def _workflow() -> WorkflowIR:
    return WorkflowIR(
        ir_version="0.1",
        id="runtime-test",
        name="Runtime test",
        description="generated runtime test",
        trigger=Trigger(
            id="start",
            type="trigger",
            name="Start",
            config={"mode": "manual"},
        ),
        nodes=[
            Node(
                id="work",
                type="agent",
                name="Work",
                config={"role": "perform the task"},
            ),
            Node(
                id="output",
                type="output",
                name="Output",
                config={},
            ),
        ],
        edges=[
            {"from": "start", "to": "work"},
            {"from": "work", "to": "output"},
        ],
        variables=[],
        policies=[],
        tests=[],
    )


def test_runtime_template_is_valid_python():
    ast.parse(RUNTIME_SOURCE)


def test_generated_repository_executes_workflow_in_mock_mode():
    workflow = _workflow()
    system = SystemCompiler().compile(
        "Build an agent service",
        ContextGraph(),
        workflow,
        [ServiceSpec(id="runtime", name="Runtime", runtime="python")],
        [],
    )
    files = RepositoryCompiler().compile(system, workflow)
    result = SandboxVerifier().verify(files)

    assert result["status"] == "passed"
    runtime = next(item for item in files if item.path.endswith("/app/runtime.py"))
    assert "execute_workflow" in runtime.content
