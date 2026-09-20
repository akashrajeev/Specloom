from __future__ import annotations

from backend.compiler.models import Artifact
from backend.compiler.repair import (
    ArtifactPatch,
    ArtifactPatchSet,
    SoftwareRepairEngine,
)
from backend.compiler.sandbox import SandboxVerificationResult


class FakeVerifier:
    def __init__(self) -> None:
        self.calls = 0

    def verify(self, artifacts):
        self.calls += 1
        items = list(artifacts)
        broken = any("BROKEN" in artifact.content for artifact in items)
        return SandboxVerificationResult(
            status="failed" if broken else "passed",
            errors=["generated artifact contains BROKEN"] if broken else [],
            checked_artifacts=len(items),
            executed_contract=not broken,
        )


class FakeRepairer:
    def repair(self, **kwargs):
        target = next(
            item
            for item in kwargs["artifacts"]
            if item.path == "generated/repository/app/main.py"
        )
        return ArtifactPatchSet(
            summary="remove injected failure",
            patches=[
                ArtifactPatch(
                    path=target.path,
                    content=target.content.replace("BROKEN", "FIXED"),
                    rationale="remove injected failure",
                )
            ],
        )


def _artifacts():
    return [
        Artifact(
            path="generated/repository/app/main.py",
            kind="source",
            content="BROKEN",
        ),
        Artifact(
            path="generated/repository/system-ir.json",
            kind="spec",
            content="{}",
        ),
        Artifact(
            path="generated/repository/workflow-ir.json",
            kind="spec",
            content="{}",
        ),
    ]


def test_repair_engine_retries_and_applies_patch():
    verifier = FakeVerifier()
    engine = SoftwareRepairEngine(
        repairer=FakeRepairer(),
        verifier=verifier,
        max_attempts=2,
    )

    artifacts, result, attempts, findings = engine.repair(
        goal="repair a generated service",
        context=None,
        workflow=None,
        artifacts=_artifacts(),
    )

    assert result["status"] == "passed"
    assert attempts == 1
    assert verifier.calls == 2
    assert findings == []
    assert next(
        item
        for item in artifacts
        if item.path.endswith("main.py")
    ).content == "FIXED"


def test_repair_cannot_modify_canonical_specs():
    artifacts = _artifacts()
    patched, rejected = SoftwareRepairEngine._apply(
        artifacts,
        ArtifactPatchSet(
            patches=[
                ArtifactPatch(
                    path="generated/repository/workflow-ir.json",
                    content='{"tampered": true}',
                )
            ]
        ),
    )

    assert patched == artifacts
    assert "immutable specification" in rejected[0]


def test_repair_cannot_embed_known_secret_shapes():
    artifacts = _artifacts()
    patched, rejected = SoftwareRepairEngine._apply(
        artifacts,
        ArtifactPatchSet(
            patches=[
                ArtifactPatch(
                    path="generated/repository/app/main.py",
                    content='TOKEN = "sk-1234567890abcdefABCDEF"',
                )
            ],
        ),
    )

    assert patched == artifacts
    assert "embedded secret" in rejected[0]


def test_repair_engine_can_seed_from_external_staging_failure():
    verifier = FakeVerifier()
    engine = SoftwareRepairEngine(
        repairer=FakeRepairer(),
        verifier=verifier,
        max_attempts=1,
    )

    artifacts, result, attempts, findings = engine.repair(
        goal="repair a generated service",
        context=None,
        workflow=None,
        artifacts=_artifacts(),
        initial_verification={
            "status": "failed",
            "errors": ["container health check failed"],
        },
    )

    assert result["status"] == "passed"
    assert attempts == 1
    assert next(
        item
        for item in artifacts
        if item.path.endswith("main.py")
    ).content == "FIXED"
