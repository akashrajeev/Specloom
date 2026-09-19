from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Iterable

from .models import Artifact


class DeploymentExecutionError(RuntimeError):
    pass


class StagingExecutionResult(dict):
    pass


class StagingContainerExecutor:
    """Build and smoke-test a generated repository inside an isolated container."""

    def __init__(
        self,
        *,
        image_prefix: str = "specloom-generated",
        timeout_seconds: int = 120,
    ) -> None:
        self.image_prefix = image_prefix
        self.timeout_seconds = timeout_seconds

    def execute(self, artifacts: Iterable[Artifact]) -> StagingExecutionResult:
        artifacts = list(artifacts)
        docker = shutil.which("docker")
        if docker is None:
            raise DeploymentExecutionError("Docker is required for staging container execution")

        with tempfile.TemporaryDirectory(prefix="specloom-staging-") as tmp:
            root = Path(tmp)
            self._materialize(root, artifacts)
            if not (root / "generated/repository/Dockerfile").exists():
                raise DeploymentExecutionError(
                    "generated repository Dockerfile is missing"
                )

            digest = hashlib.sha256(
                "|".join(
                    f"{item.path}:{item.sha256}"
                    for item in sorted(artifacts, key=lambda item: item.path)
                ).encode("utf-8")
            ).hexdigest()[:16]
            image = f"{self.image_prefix}:{digest}"

            self._run(
                [
                    docker,
                    "build",
                    "--pull",
                    "-f",
                    "generated/repository/Dockerfile",
                    "-t",
                    image,
                    ".",
                ],
                cwd=root,
                timeout=self.timeout_seconds,
            )

            container_id = ""
            try:
                run = self._run(
                    [
                        docker,
                        "run",
                        "-d",
                        "--network=none",
                        "--read-only",
                        "--cap-drop=ALL",
                        "--security-opt=no-new-privileges",
                        "--memory=512m",
                        "--cpus=1",
                        "--pids-limit=128",
                        "--tmpfs=/tmp:rw,noexec,nosuid,size=64m",
                        image,
                    ],
                    cwd=root,
                    timeout=30,
                )
                container_id = run.stdout.strip()

                health = self._run(
                    [
                        docker,
                        "exec",
                        container_id,
                        "python",
                        "-c",
                        (
                            "import json, urllib.request; "
                            "data=json.load(urllib.request.urlopen("
                            "'http://127.0.0.1:8080/health', timeout=5)); "
                            "assert data.get('status') == 'ok', data"
                        ),
                    ],
                    cwd=root,
                    timeout=15,
                )
                return StagingExecutionResult(
                    status="passed",
                    image=image,
                    container_id=container_id,
                    health_output=health.stdout.strip(),
                )
            finally:
                if container_id:
                    subprocess.run(
                        [docker, "rm", "-f", container_id],
                        cwd=root,
                        capture_output=True,
                        text=True,
                        timeout=15,
                        check=False,
                    )
                subprocess.run(
                    [docker, "image", "rm", image],
                    cwd=root,
                    capture_output=True,
                    text=True,
                    timeout=15,
                    check=False,
                )

    @staticmethod
    def _materialize(root: Path, artifacts: list[Artifact]) -> None:
        for artifact in artifacts:
            path = Path(artifact.path)
            if path.is_absolute() or ".." in path.parts:
                raise DeploymentExecutionError(
                    f"unsafe artifact path: {artifact.path}"
                )
            target = root / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(artifact.content, encoding="utf-8")

    @staticmethod
    def _run(
        command: list[str],
        *,
        cwd: Path,
        timeout: int,
    ) -> subprocess.CompletedProcess[str]:
        try:
            result = subprocess.run(
                command,
                cwd=cwd,
                capture_output=True,
                text=True,
                timeout=timeout,
                check=False,
                env={
                    "PATH": os.environ.get("PATH", ""),
                    "HOME": os.environ.get("HOME", ""),
                    "DOCKER_CONFIG": os.environ.get("DOCKER_CONFIG", ""),
                },
            )
        except subprocess.TimeoutExpired as exc:
            raise DeploymentExecutionError(
                f"staging command timed out: {' '.join(command[:4])}"
            ) from exc

        if result.returncode != 0:
            raise DeploymentExecutionError(
                f"staging command failed ({result.returncode}): "
                + (result.stderr.strip() or result.stdout.strip())
            )
        return result
