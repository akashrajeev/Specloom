from __future__ import annotations

from backend.compiler.implementation import (
    ConfiguredImplementationCompiler,
    DeterministicImplementationCompiler,
)
from backend.compiler.models import ServiceSpec
from backend.compiler.repository import RepositoryCompiler
from backend.compiler.system_ir import SystemCompiler
from backend.context.models import ContextGraph, Requirement
from backend.workflow.models import Node, Trigger, WorkflowIR


def _workflow() -> WorkflowIR:
    return WorkflowIR(
        ir_version="0.1",
        id="implementation-test",
        name="Implementation test",
        description="test",
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


def test_deterministic_implementation_compiler_is_a_safe_noop():
    context = ContextGraph(
        requirements=[
            Requirement(
                id="req-1",
                statement="The system must preserve submitted records.",
                priority="high",
            )
        ]
    )
    workflow = _workflow()
    system = SystemCompiler().compile(
        "Build a record service.",
        context,
        workflow,
        [ServiceSpec(id="runtime", name="Runtime", runtime="python")],
        [],
    )
    planned = RepositoryCompiler().compile(system, workflow)
    artifacts = [
        __import__("backend.compiler.models", fromlist=["Artifact"]).Artifact(
            path=item.path,
            kind=item.kind,
            content=item.content,
            executable=item.executable,
            generated_from=list(item.generated_from),
        ).with_hash()
        for item in planned
    ]

    patches = DeterministicImplementationCompiler().compile(
        goal=system.goal,
        context=context,
        system_ir=system,
        workflow=workflow,
        artifacts=artifacts,
    )
    assert patches.patches == []


def test_configured_implementation_compiler_uses_deterministic_mode_in_showcase(monkeypatch):
    monkeypatch.setenv("SPECL00M_IMPLEMENTATION_MODE", "auto")
    monkeypatch.setenv("SPECL00M_ARCHITECT_MODE", "showcase")

    compiler = ConfiguredImplementationCompiler()
    assert compiler.mode == "deterministic"
