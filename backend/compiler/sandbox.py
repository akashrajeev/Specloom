from __future__ import annotations

import ast
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Iterable

from pydantic import BaseModel, Field

from .models import Artifact
from .repository import PlannedFile


class SandboxPolicy(BaseModel):
    mode: str = "process"
    image: str = "python:3.11-slim"
    timeout_seconds: int = Field(default=10, ge=1, le=120)
    memory: str = "256m"
    cpus: str = "1"
    pids_limit: int = Field(default=64, ge=16, le=1024)


class SandboxVerificationResult(dict):
    pass


class SandboxVerifier:
    """Run compiler-owned verification in a temporary dependency-free sandbox.

    The sandbox executes compiler-owned contract and generated acceptance scripts.
    It does not install packages or read application secrets. It is an execution
    harness, not a hardened VM/container security boundary yet.
    """

    def __init__(self, policy: SandboxPolicy | None = None) -> None:
        self.policy = policy or SandboxPolicy()

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
                "generated/repository/tests/independent_acceptance.py",
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
                    proc = self._execute(root, executable_path)
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
            executed_independent_acceptance=(
                "generated/repository/tests/independent_acceptance.py"
                in executed_checks
            ),
            sandbox_mode=self.policy.mode,
        )



    def _execute(
        self,
        root: Path,
        relative_path: str,
    ) -> subprocess.CompletedProcess[str]:
        if self.policy.mode == "process":
            return subprocess.run(
                [sys.executable, "-B", str(root / relative_path)],
                cwd=root,
                env={
                    "PATH": os.environ.get("PATH", ""),
                    "PYTHONNOUSERSITE": "1",
                    "PYTHONDONTWRITEBYTECODE": "1",
                },
                capture_output=True,
                text=True,
                timeout=self.policy.timeout_seconds,
                check=False,
            )

        if self.policy.mode != "container":
            raise RuntimeError("sandbox mode must be process or container")

        return subprocess.run(
            [
                "docker",
                "run",
                "--rm",
                "--network=none",
                "--read-only",
                "--cap-drop=ALL",
                "--security-opt=no-new-privileges",
                f"--memory={self.policy.memory}",
                f"--cpus={self.policy.cpus}",
                f"--pids-limit={self.policy.pids_limit}",
                "--tmpfs=/tmp:rw,noexec,nosuid,size=64m",
                "-v",
                f"{root}:/workspace:ro",
                "-w",
                "/workspace",
                self.policy.image,
                "python",
                "-B",
                relative_path,
            ],
            cwd=root,
            env={
                "DOCKER_CONFIG": os.environ.get("DOCKER_CONFIG", ""),
            },
            capture_output=True,
            text=True,
            timeout=self.policy.timeout_seconds,
            check=False,
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
