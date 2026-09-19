from __future__ import annotations

import json
import re
from dataclasses import dataclass

from backend.workflow.models import WorkflowIR

from .system_ir import SystemIR


@dataclass(frozen=True)
class PlannedFile:
    path: str
    kind: str
    content: str
    executable: bool = False
    generated_from: tuple[str, ...] = ()


class RepositoryCompiler:
    """Lower SystemIR into a runnable, inspectable repository package."""

    def compile(self, system: SystemIR, workflow: WorkflowIR) -> list[PlannedFile]:
        system_json = json.dumps(system.model_dump(mode="json"), indent=2, sort_keys=True) + "\n"
        workflow_json = json.dumps(workflow.model_dump(mode="json"), indent=2, sort_keys=True) + "\n"

        return [
            PlannedFile(
                path="generated/repository/system-ir.json",
                kind="spec",
                content=system_json,
                generated_from=(system.id,),
            ),
            PlannedFile(
                path="generated/repository/workflow-ir.json",
                kind="spec",
                content=workflow_json,
                generated_from=(workflow.id,),
            ),
            PlannedFile(
                path="generated/repository/app/main.py",
                kind="source",
                content=self._main(system),
                executable=True,
                generated_from=(system.id, workflow.id),
            ),
            PlannedFile(
                path="generated/repository/app/system_contract.py",
                kind="source",
                content=self._contract(system),
                generated_from=(system.id,),
            ),
            PlannedFile(
                path="generated/repository/verify.py",
                kind="test",
                content=self._verifier(system),
                executable=True,
                generated_from=(system.id, workflow.id),
            ),
            PlannedFile(
                path="generated/repository/tests/README.md",
                kind="documentation",
                content=(
                    "# Generated Verification\n\n"
                    "This repository package contains a deterministic compiler-owned "
                    "contract verifier. The verifier is intentionally dependency-free "
                    "so Specloom can execute it before provisioning external services.\n"
                ),
                generated_from=(system.id,),
            ),
            PlannedFile(
                path="generated/repository/requirements.txt",
                kind="config",
                content="fastapi>=0.115,<1\nuvicorn>=0.34,<1\n",
                generated_from=(system.id,),
            ),
            PlannedFile(
                path="generated/repository/Dockerfile",
                kind="config",
                content=(
                    "FROM python:3.11-slim\n"
                    "WORKDIR /app\n"
                    "COPY generated/repository /app\n"
                    "RUN pip install --no-cache-dir -r requirements.txt\n"
                    "EXPOSE 8080\n"
                    'CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080"]\n'
                ),
                generated_from=(system.id,),
            ),
        ]

    @staticmethod
    def _main(system: SystemIR) -> str:
        title = system.name.replace('"', '\"')
        return f'''from __future__ import annotations

from fastapi import FastAPI

from app.system_contract import SYSTEM

app = FastAPI(title="{title}")


@app.get("/health")
def health() -> dict[str, str]:
    return {{"status": "ok", "system_id": SYSTEM["id"]}}


@app.get("/system")
def system_manifest() -> dict:
    return SYSTEM


@app.post("/run")
def run(payload: dict | None = None) -> dict:
    return {{
        "status": "accepted",
        "system_id": SYSTEM["id"],
        "workflow_id": SYSTEM["workflow_id"],
        "input": payload or {{}},
        "execution": "delegated-to-compiled-runtime",
    }}
'''

    @staticmethod
    def _contract(system: SystemIR) -> str:
        encoded = repr(system.model_dump(mode="json"))
        return f'''from __future__ import annotations

SYSTEM = {encoded}
'''

    @staticmethod
    def _verifier(system: SystemIR) -> str:
        return f'''from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent
system = json.loads((ROOT / "system-ir.json").read_text())
workflow = json.loads((ROOT / "workflow-ir.json").read_text())

assert system["id"] == {system.id!r}
assert system["workflow_id"] == {system.workflow_id!r}
assert system["acceptance_criteria"], "system must contain acceptance criteria"
assert workflow["id"] == {system.workflow_id!r}
assert workflow["nodes"], "workflow must contain executable nodes"

print("SPEClOOM_GENERATED_CONTRACT:PASS")
'''

    @staticmethod
    def slug(value: str) -> str:
        return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")[:50] or "generated"
