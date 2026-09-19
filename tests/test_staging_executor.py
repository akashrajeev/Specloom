from __future__ import annotations

from unittest.mock import patch

from backend.compiler.models import Artifact
from backend.compiler.staging import StagingContainerExecutor


def test_staging_executor_builds_nested_generated_dockerfile(tmp_path):
    executor = StagingContainerExecutor()
    fake = type("Completed", (), {"returncode": 0, "stdout": "abc", "stderr": ""})()

    artifacts = [
        Artifact(
            path="generated/repository/Dockerfile",
            kind="config",
            content="FROM python:3.11-slim\n",
        ).with_hash()
    ]

    with patch("backend.compiler.staging.shutil.which", return_value="/usr/bin/docker"),          patch("backend.compiler.staging.subprocess.run", return_value=fake) as run:
        executor._run(
            ["docker", "build", "-f", "generated/repository/Dockerfile", "-t", "image", "."],
            cwd=tmp_path,
            timeout=5,
        )

    assert run.call_args.kwargs["timeout"] == 5
    assert run.call_args.args[0][2:4] == ["-f", "generated/repository/Dockerfile"]


def test_staging_executor_rejects_unsafe_artifact_paths(tmp_path):
    executor = StagingContainerExecutor()
    try:
        executor._materialize(
            tmp_path,
            [
                Artifact(
                    path="../escape.py",
                    kind="source",
                    content="raise SystemExit",
                )
            ],
        )
    except Exception as exc:
        assert "unsafe artifact path" in str(exc)
    else:
        raise AssertionError("unsafe artifact path was not rejected")
