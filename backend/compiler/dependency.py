from __future__ import annotations

import ast
import os
import re
import sys
from dataclasses import dataclass

from backend.compiler.models import Artifact, CompilerDiagnostic


_SAFE_PACKAGE_MAP = {
    "fastapi": "fastapi",
    "uvicorn": "uvicorn",
    "pydantic": "pydantic",
    "httpx": "httpx",
    "requests": "requests",
    "boto3": "boto3",
    "botocore": "botocore",
    "redis": "redis",
    "pymongo": "pymongo",
    "sqlalchemy": "sqlalchemy",
    "psycopg": "psycopg",
    "numpy": "numpy",
    "pandas": "pandas",
}


@dataclass(frozen=True)
class DependencyPlan:
    declared: tuple[str, ...]
    required: tuple[str, ...]
    unresolved: tuple[str, ...]


class DependencyCompiler:
    """Check generated Python imports against declared and explicitly approved dependencies."""

    def __init__(self, allowed_packages: set[str] | None = None) -> None:
        configured = os.getenv(
            "SPECL00M_ALLOWED_PYTHON_PACKAGES",
            "fastapi,uvicorn,pydantic,httpx,boto3",
        )
        defaults = {
            item.strip().lower()
            for item in configured.split(",")
            if item.strip()
        }
        self.allowed_packages = allowed_packages or defaults

    def compile(
        self,
        artifacts: list[Artifact],
    ) -> tuple[DependencyPlan, list[CompilerDiagnostic]]:
        declared = set()
        requirements = next(
            (
                item.content
                for item in artifacts
                if item.path == "generated/repository/requirements.txt"
            ),
            "",
        )
        for line in requirements.splitlines():
            candidate = re.split(r"[<>=!~]", line, maxsplit=1)[0].strip().lower()
            if candidate and not candidate.startswith("#"):
                declared.add(candidate)

        imports: set[str] = set()
        for artifact in artifacts:
            if not artifact.path.endswith(".py"):
                continue
            try:
                tree = ast.parse(artifact.content, filename=artifact.path)
            except SyntaxError:
                continue
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    imports.update(
                        alias.name.split(".", 1)[0]
                        for alias in node.names
                    )
                elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                    imports.add(node.module.split(".", 1)[0])

        stdlib = set(getattr(sys, "stdlib_module_names", ()))
        third_party = {
            _SAFE_PACKAGE_MAP.get(name, name)
            for name in imports
            if name not in stdlib
            and name not in {"app"}
        }
        required = set(declared) | {
            package
            for package in third_party
            if package in self.allowed_packages
        }
        unresolved = {
            package
            for package in third_party
            if package not in declared
            and package not in self.allowed_packages
        }

        diagnostics = [
            CompilerDiagnostic(
                severity="blocking",
                code="undeclared-dependency",
                message=(
                    f"Generated source imports '{package}', but the dependency "
                    "is neither declared nor on the explicit Specloom allowlist."
                ),
            )
            for package in sorted(unresolved)
        ]

        return (
            DependencyPlan(
                declared=tuple(sorted(declared)),
                required=tuple(sorted(required)),
                unresolved=tuple(sorted(unresolved)),
            ),
            diagnostics,
        )

    def materialize_allowed(
        self,
        artifacts: list[Artifact],
        plan: DependencyPlan,
    ) -> tuple[list[Artifact], list[CompilerDiagnostic]]:
        """Add newly required allowlisted packages to generated requirements."""
        additions = sorted(set(plan.required) - set(plan.declared))
        if not additions:
            return artifacts, []

        by_path = {item.path: item for item in artifacts}
        requirements_path = "generated/repository/requirements.txt"
        requirements_artifact = by_path.get(requirements_path)
        if requirements_artifact is None:
            return artifacts, [
                CompilerDiagnostic(
                    severity="blocking",
                    code="dependency-manifest-missing",
                    message=(
                        "Generated repository requirements.txt is missing; "
                        "allowlisted imports cannot be provisioned safely."
                    ),
                    artifact_path=requirements_path,
                )
            ]

        existing = {
            re.split(r"[<>=!~]", line, maxsplit=1)[0].strip().lower()
            for line in requirements_artifact.content.splitlines()
            if line.strip() and not line.lstrip().startswith("#")
        }
        new_lines = [
            package
            for package in additions
            if package.lower() not in existing
        ]
        if not new_lines:
            return artifacts, []

        content = requirements_artifact.content.rstrip() + "\n"
        content += "\n".join(new_lines) + "\n"
        by_path[requirements_path] = requirements_artifact.model_copy(
            update={"content": content}
        ).with_hash()

        diagnostics = [
            CompilerDiagnostic(
                severity="info",
                code="dependency-auto-declared",
                message=(
                    f"Auto-declared approved dependency '{package}' "
                    "in the generated repository requirements."
                ),
                artifact_path=requirements_path,
            )
            for package in new_lines
        ]
        return list(by_path.values()), diagnostics
