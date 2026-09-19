from __future__ import annotations

import ast
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Iterable

from .models import Artifact
from .repository import PlannedFile


class SandboxVerificationResult(dict):
    pass


class SandboxVerifier:
    """Run compiler-owned verification in a temporary dependency-free sandbox.

    The sandbox executes compiler-owned contract and generated acceptance scripts.
    It does not install packages or read application secrets. It is an execution
    harness, not a hardened VM/container security boundary yet.
    """

    def verify(self, artifacts: Iterable[Artifact | PlannedFile]) -> SandboxVerificationResult:
        normalized = self._normalize(artifacts)
        errors: list[str] = []

        for path, content in normalized.items():
            if not self._safe_path(path):
                errors.append(f"unsafe generated path: {path}")
                continue

            suffix = Path(path).suffix.lower()
            try:
                if suffix == ".py":
                    ast.parse(content, filename=path)
                elif suffix == ".json":
                    json.loads(content)
            except (SyntaxError, ValueError) as exc:
                errors.append(f"{path}: {exc}")

        executable_checks = [
            path
            for path in (
                "generated/repository/verify.py",
                "generated/repository/tests/test_acceptance.py",
            )
            if path in normalized
        ]

        executed_checks: list[str] = []
        if executable_checks and not errors:
            with tempfile.TemporaryDirectory(prefix="specloom-sandbox-") as tmp:
                root = Path(tmp)
                for path, content in normalized.items():
                    target = root / path
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_text(content, encoding="utf-8")

                for executable_path in executable_checks:
                    proc = subprocess.run(
                        [sys.executable, "-B", str(root / executable_path)],
                        cwd=root,
                        env={
                            "PATH": os.environ.get("PATH", ""),
                            "PYTHONNOUSERSITE": "1",
                            "PYTHONDONTWRITEBYTECODE": "1",
                        },
                        capture_output=True,
                        text=True,
                        timeout=5,
                        check=False,
                    )
                    if proc.returncode != 0:
                        errors.append(
                            f"{executable_path} failed: "
                            + (
                                proc.stderr.strip()
                                or proc.stdout.strip()
                                or f"exit {proc.returncode}"
                            )
                        )
                    else:
                        executed_checks.append(executable_path)

        return SandboxVerificationResult(
            status="failed" if errors else "passed",
            errors=errors,
            checked_artifacts=len(normalized),
            executed_contract="generated/repository/verify.py" in executed_checks,
            executed_acceptance="generated/repository/tests/test_acceptance.py" in executed_checks,
        )

    @staticmethod
    def _normalize(artifacts: Iterable[Artifact | PlannedFile]) -> dict[str, str]:
        result: dict[str, str] = {}
        for artifact in artifacts:
            result[str(artifact.path)] = str(artifact.content)
        return result

    @staticmethod
    def _safe_path(path: str) -> bool:
        pure = Path(path)
        if pure.is_absolute():
            return False
        parts = pure.parts
        return all(part not in {"", ".", ".."} for part in parts)
