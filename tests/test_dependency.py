from __future__ import annotations

from backend.compiler.dependency import DependencyCompiler
from backend.compiler.models import Artifact


def test_dependency_compiler_accepts_stdlib_and_declared_packages():
    artifacts = [
        Artifact(
            path="generated/repository/requirements.txt",
            kind="config",
            content="fastapi>=0.1\n",
        ),
        Artifact(
            path="generated/repository/app/main.py",
            kind="source",
            content="import json\nfrom fastapi import FastAPI\n",
        ),
    ]

    plan, diagnostics = DependencyCompiler().compile(artifacts)
    assert plan.unresolved == ()
    assert "fastapi" in plan.declared
    assert diagnostics == []


def test_dependency_compiler_blocks_unknown_third_party_import():
    artifacts = [
        Artifact(
            path="generated/repository/requirements.txt",
            kind="config",
            content="fastapi>=0.1\n",
        ),
        Artifact(
            path="generated/repository/app/domain.py",
            kind="source",
            content="import imaginary_generated_package\n",
        ),
    ]

    plan, diagnostics = DependencyCompiler(
        allowed_packages={"fastapi"},
    ).compile(artifacts)

    assert "imaginary_generated_package" in plan.unresolved
    assert diagnostics
    assert diagnostics[0].code == "undeclared-dependency"
