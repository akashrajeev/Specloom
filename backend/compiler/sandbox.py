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

    This first sandbox intentionally executes only the generated deterministic
    contract verifier. It never installs packages, reads application secrets,
    or invokes user-selected commands.
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

        verifier_path = "generated/repository/verify.py"
        if verifier_path in normalized and not errors:
            with tempfile.TemporaryDirectory(prefix="specloom-sandbox-") as tmp:
                root = Path(tmp)
                for path, content in normalized.items():
                    target = root / path
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_text(content, encoding="utf-8")

                proc = subprocess.run(
                    [sys.executable, "-B", str(root / verifier_path)],
                    cwd=root,
                    env={
                        "PATH": os.environ.get("PATH", ""),
                        "PYTHONNOUSERSITE": "1",
                    },
                    capture_output=True,
                    text=True,
                    timeout=5,
                    check=False,
                )
                if proc.returncode != 0:
                    errors.append(
                        "generated contract failed: "
                        + (proc.stderr.strip() or proc.stdout.strip() or f"exit {proc.returncode}")
                    )

        return SandboxVerificationResult(
            status="failed" if errors else "passed",
            errors=errors,
            checked_artifacts=len(normalized),
            executed_contract=verifier_path in normalized and not errors,
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
