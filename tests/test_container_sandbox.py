from __future__ import annotations

from unittest.mock import patch

from backend.compiler.sandbox import SandboxPolicy, SandboxVerifier


def test_container_sandbox_command_is_network_isolated(tmp_path):
    verifier = SandboxVerifier(
        SandboxPolicy(
            mode="container",
            image="python:3.11-slim",
            timeout_seconds=7,
        )
    )

    fake = type(
        "Completed",
        (),
        {"returncode": 0, "stdout": "ok", "stderr": ""},
    )()

    with patch("backend.compiler.sandbox.subprocess.run", return_value=fake) as run:
        verifier._execute(tmp_path, "check.py")

    command = run.call_args.args[0]
    assert command[:3] == ["docker", "run", "--rm"]
    assert "--network=none" in command
    assert "--read-only" in command
    assert "--cap-drop=ALL" in command
    assert "--security-opt=no-new-privileges" in command
    assert "--memory=256m" in command
    assert "--cpus=1" in command
    assert "--pids-limit=64" in command


def test_default_sandbox_remains_process_mode_for_compatibility():
    assert SandboxVerifier().policy.mode == "process"
