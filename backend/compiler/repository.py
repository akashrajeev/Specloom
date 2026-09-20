from __future__ import annotations

import json
import re
from dataclasses import dataclass

from backend.context.models import ContextGraph
from backend.workflow.models import WorkflowIR

from .acceptance import IndependentAcceptanceCompiler
from .runtime_template import RUNTIME_SOURCE
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

    def compile(
        self,
        system: SystemIR,
        workflow: WorkflowIR,
        context: ContextGraph | None = None,
    ) -> list[PlannedFile]:
        system_json = json.dumps(system.model_dump(mode="json"), indent=2, sort_keys=True) + "\n"
        workflow_json = json.dumps(workflow.model_dump(mode="json"), indent=2, sort_keys=True) + "\n"
        context = context or ContextGraph()
        acceptance_artifact, _, acceptance_manifest = IndependentAcceptanceCompiler().compile(
            system,
            context,
        )
        acceptance_manifest_artifact = PlannedFile(
            path="generated/repository/tests/independent-acceptance.json",
            kind="spec",
            content=json.dumps(
                acceptance_manifest.model_dump(mode="json"),
                indent=2,
                sort_keys=True,
            ) + "\n",
            generated_from=(system.id,),
        )

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
                path="generated/repository/app/__init__.py",
                kind="source",
                content="",
                generated_from=(system.id,),
            ),
            PlannedFile(
                path="generated/repository/app/main.py",
                kind="source",
                content=self._main(system),
                executable=True,
                generated_from=(system.id, workflow.id),
            ),
            PlannedFile(
                path="generated/repository/app/observability.py",
                kind="source",
                content=self._observability(),
                executable=False,
                generated_from=(system.id, workflow.id),
            ),
            PlannedFile(
                path="generated/repository/app/runtime.py",
                kind="source",
                content=RUNTIME_SOURCE,
                generated_from=(system.id, workflow.id),
            ),
            PlannedFile(
                path="generated/repository/app/implementation.py",
                kind="source",
                content=self._implementation_stub(system),
                executable=False,
                generated_from=(system.id, workflow.id),
            ),
            acceptance_manifest_artifact,
            PlannedFile(
                path="generated/repository/tests/independent_acceptance.py",
                kind="test",
                content=acceptance_artifact.content,
                generated_from=(system.id,),
            ),
            PlannedFile(
                path="generated/repository/tests/independent-acceptance.json",
                kind="spec",
                content=json.dumps(acceptance_manifest.model_dump(mode="json"), indent=2, sort_keys=True) + "\n",
                generated_from=(system.id,),
            ),
            PlannedFile(
                path="generated/repository/tests/independent_acceptance.py",
                kind="test",
                content=acceptance_artifact.content,
                generated_from=(system.id,),
            ),
            PlannedFile(
                path="generated/repository/tests/test_acceptance.py",
                kind="test",
                content=self._acceptance_test(system),
                executable=False,
                generated_from=(system.id,),
            ),
            PlannedFile(
                path="generated/repository/app/api.py",
                kind="source",
                content=self._api(),
                executable=False,
                generated_from=(system.id,),
            ),
            PlannedFile(
                path="generated/repository/app/domain.py",
                kind="source",
                content=self._domain(system),
                executable=False,
                generated_from=(system.id,),
            ),
            PlannedFile(
                path="generated/repository/app/persistence.py",
                kind="source",
                content=self._persistence(system),
                executable=False,
                generated_from=(system.id,),
            ),
            PlannedFile(
                path="generated/repository/migrations/001_initial.sql",
                kind="config",
                content=self._migration(system),
                executable=False,
                generated_from=(system.id,),
            ),
            PlannedFile(
                path="generated/repository/web/package.json",
                kind="config",
                content=self._frontend_package(system),
                executable=False,
                generated_from=(system.id,),
            ),
            PlannedFile(
                path="generated/repository/web/tsconfig.json",
                kind="config",
                content=self._frontend_tsconfig(),
                generated_from=(system.id,),
            ),
            PlannedFile(
                path="generated/repository/web/index.html",
                kind="source",
                content=self._frontend_index(),
                executable=False,
                generated_from=(system.id,),
            ),
            PlannedFile(
                path="generated/repository/web/src/main.tsx",
                kind="source",
                content=self._frontend_main(),
                executable=False,
                generated_from=(system.id,),
            ),
            PlannedFile(
                path="generated/repository/web/src/App.tsx",
                kind="source",
                content=self._frontend_app(system),
                executable=False,
                generated_from=(system.id,),
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
        title = system.name.replace("\\", "\\\\").replace('"', '\\"')
        return f'''from __future__ import annotations

from fastapi import FastAPI

from app.implementation import handle
from app.runtime import execute_workflow
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
    request = dict(payload or {{}})
    mode = str(request.pop("_mode", "mock"))
    approved = bool(request.pop("_approved", False))
    execution = execute_workflow(request, mode=mode, approved=approved)
    if execution["status"] == "completed":
        execution["application"] = handle(request, execution)
    return execution
'''

    @staticmethod
    def _implementation_stub(system: SystemIR) -> str:
        return '''from __future__ import annotations


def handle(payload: dict, execution: dict) -> dict:
    """Domain extension point compiled from the System IR."""
    return {
        "status": "scaffolded",
        "input": payload,
        "workflow_status": execution.get("status"),
        "system_goal": execution.get("system_goal"),
    }
'''


    @staticmethod
    def _acceptance_test(system: SystemIR) -> str:
        return '''import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.implementation import handle


result = handle(
    {"message": "verification"},
    {"status": "completed", "system_goal": "generated"},
)
assert isinstance(result, dict)
assert result["input"] == {"message": "verification"}
assert result["workflow_status"] == "completed"
'''


    @staticmethod
    def _api() -> str:
        return '''from __future__ import annotations

from fastapi import APIRouter

router = APIRouter(prefix="/api", tags=["generated"])


@router.get("/status")
def status() -> dict[str, str]:
    return {"status": "ok", "service": "generated"}
'''


    @staticmethod
    def _observability() -> str:
        return '''from __future__ import annotations

import json
import time
from typing import Any


SENSITIVE_KEYS = {
    "authorization",
    "api_key",
    "apikey",
    "password",
    "secret",
    "token",
}


def emit_event(events: list[dict[str, Any]], event: str, **fields: Any) -> None:
    safe = {
        key: _redact(value)
        for key, value in fields.items()
        if key not in {"payload"}
    }
    events.append(
        {
            "ts": time.time(),
            "event": event,
            **safe,
        }
    )


def serialize(events: list[dict[str, Any]]) -> str:
    return json.dumps(events, sort_keys=True, default=str)


def _redact(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: ("[REDACTED]" if key.lower() in SENSITIVE_KEYS else _redact(item))
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_redact(item) for item in value]
    return value
'''


    @staticmethod
    def _domain(system: SystemIR) -> str:
        names = [item.name for item in system.data_models]
        return f'''from __future__ import annotations

from typing import Any


MODEL_NAMES = {names!r}


def normalize_payload(payload: dict[str, Any]) -> dict[str, Any]:
    return dict(payload)


def model_names() -> list[str]:
    return list(MODEL_NAMES)
'''


    @staticmethod
    def _persistence(system: SystemIR) -> str:
        tables = []
        for item in system.data_models:
            table = re.sub(r"[^A-Za-z0-9_]+", "_", item.name).strip("_").lower() or "entity"
            tables.append({"model": item.name, "table": table})
        return f'''from __future__ import annotations

import json
import os
import sqlite3
from pathlib import Path
from typing import Any

DB_PATH = Path(os.getenv("SPECL00M_DB_PATH", "/tmp/specloom.db"))
MODEL_TABLES = {tables!r}


def initialize() -> None:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(DB_PATH) as db:
        for item in MODEL_TABLES:
            db.execute(
                f'CREATE TABLE IF NOT EXISTS "{{item["table"]}}" '
                '(id TEXT PRIMARY KEY, payload TEXT NOT NULL)'
            )
        db.commit()


def put(model: str, record_id: str, payload: dict[str, Any]) -> None:
    initialize()
    table = _table(model)
    encoded = json.dumps(payload, sort_keys=True)
    with sqlite3.connect(DB_PATH) as db:
        db.execute(
            f'INSERT OR REPLACE INTO "{{table}}" (id, payload) VALUES (?, ?)',
            (record_id, encoded),
        )
        db.commit()


def list_records(model: str) -> list[dict[str, Any]]:
    initialize()
    table = _table(model)
    with sqlite3.connect(DB_PATH) as db:
        rows = db.execute(
            f'SELECT id, payload FROM "{{table}}" ORDER BY id'
        ).fetchall()
    return [
        {{"id": row[0], **json.loads(row[1])}}
        for row in rows
    ]


def _table(model: str) -> str:
    for item in MODEL_TABLES:
        if item["model"] == model:
            return item["table"]
    raise ValueError(f"unknown model: {{model}}")
'''


    @staticmethod
    def _migration(system: SystemIR) -> str:
        lines = ["-- Generated SQLite baseline migration."]
        for item in system.data_models:
            table = re.sub(r"[^A-Za-z0-9_]+", "_", item.name).strip("_").lower() or "entity"
            lines.append(
                f'CREATE TABLE IF NOT EXISTS "{table}" '
                '(id TEXT PRIMARY KEY, payload TEXT NOT NULL);'
            )
        return "\n".join(lines) + "\n"


    @staticmethod
    def _frontend_package(system: SystemIR) -> str:
        name = re.sub(r"[^a-z0-9-]+", "-", system.name.lower()).strip("-") or "specloom-app"
        return json.dumps(
            {
                "name": name,
                "private": True,
                "version": "0.1.0",
                "type": "module",
                "scripts": {
                    "dev": "vite",
                    "build": "vite build",
                    "preview": "vite preview",
                },
                "dependencies": {
                    "react": "^19.0.0",
                    "react-dom": "^19.0.0",
                },
                "devDependencies": {
                    "typescript": "^5.8.0",
                    "vite": "^7.0.0",
                },
            },
            indent=2,
            sort_keys=True,
        ) + "\n"


    @staticmethod
    def _frontend_tsconfig() -> str:
        return '''{
  "compilerOptions": {
    "target": "ES2022",
    "useDefineForClassFields": true,
    "lib": ["ES2022", "DOM", "DOM.Iterable"],
    "allowJs": false,
    "skipLibCheck": true,
    "esModuleInterop": true,
    "allowSyntheticDefaultImports": true,
    "strict": true,
    "module": "ESNext",
    "moduleResolution": "Bundler",
    "resolveJsonModule": true,
    "isolatedModules": true,
    "noEmit": true,
    "jsx": "react-jsx"
  },
  "include": ["src"]
}
'''


    @staticmethod
    def _frontend_index() -> str:
        return '''<!doctype html>
<html lang="en">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>Specloom Generated System</title>
  </head>
  <body>
    <div id="root"></div>
    <script type="module" src="/src/main.tsx"></script>
  </body>
</html>
'''


    @staticmethod
    def _frontend_main() -> str:
        return '''import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import App from "./App";

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
'''


    @staticmethod
    def _frontend_app(system: SystemIR) -> str:
        title = system.name.replace("\\", "\\\\").replace('"', '\"')
        return f'''import {{ useState }} from "react";

const API = import.meta.env.VITE_API_BASE_URL ?? "";

export default function App() {{
  const [status, setStatus] = useState("ready");

  async function run() {{
    setStatus("running");
    try {{
      const response = await fetch(API + "/run", {{
        method: "POST",
        headers: {{ "content-type": "application/json" }},
        body: JSON.stringify({{}}),
      }});
      setStatus(response.ok ? "completed" : "failed");
    }} catch {{
      setStatus("failed");
    }}
  }}

  return (
    <main style={{{{ maxWidth: 960, margin: "3rem auto", fontFamily: "sans-serif" }}}}>
      <h1>{title}</h1>
      <p>Generated application control surface.</p>
      <button onClick={{run}}>Run system</button>
      <p>Status: {{status}}</p>
    </main>
  );
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
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

system = json.loads((ROOT / "system-ir.json").read_text())
workflow = json.loads((ROOT / "workflow-ir.json").read_text())

assert system["id"] == {system.id!r}
assert system["workflow_id"] == {system.workflow_id!r}
assert system["acceptance_criteria"], "system must contain acceptance criteria"
assert workflow["id"] == {system.workflow_id!r}
assert workflow["nodes"], "workflow must contain executable nodes"

from app.runtime import execute_workflow

result = execute_workflow({{"message": "compiler verification"}}, mode="mock")
assert result["system_id"] == system["id"]
assert result["workflow_id"] == workflow["id"]
assert result["status"] in {{"completed", "waiting"}}

print("SPECl00M_GENERATED_CONTRACT:PASS")
'''

    @staticmethod
    def slug(value: str) -> str:
        return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")[:50] or "generated"
