from __future__ import annotations

import json
import sys
import types
from pathlib import Path

from backend.compiler.runtime_template import RUNTIME_SOURCE


def _load_runtime(tmp_path: Path):
    generated = tmp_path / "generated"
    repository = generated / "repository"
    app = repository / "app"
    (generated / "spec").mkdir(parents=True)
    (generated / "capabilities" / "contracts").mkdir(parents=True)
    app.mkdir(parents=True)

    (repository / "workflow-ir.json").write_text(
        json.dumps(
            {
                "id": "runtime-test",
                "trigger": {
                    "id": "trigger",
                    "type": "trigger",
                    "name": "Start",
                    "config": {"mode": "manual"},
                },
                "nodes": [
                    {
                        "id": "output",
                        "type": "output",
                        "name": "Output",
                        "config": {},
                    }
                ],
                "edges": [{"from": "trigger", "to": "output"}],
            }
        ),
        encoding="utf-8",
    )
    (repository / "system-ir.json").write_text(
        json.dumps({"id": "runtime-system"}),
        encoding="utf-8",
    )

    adapter = generated / "capabilities" / "contracts" / "apiop_orders_create.py"
    adapter.write_text(
        "def invoke(payload):\n"
        "    return {'echo': payload, 'adapter': True}\n",
        encoding="utf-8",
    )
    (generated / "spec" / "capability-adapter-registry.json").write_text(
        json.dumps(
            {
                "apiop:orders:create": {
                    "artifact_path": "generated/capabilities/contracts/apiop_orders_create.py",
                    "method": "POST",
                }
            }
        ),
        encoding="utf-8",
    )

    observable = types.ModuleType("generated.repository.app.observability")
    observable.emit_event = lambda events, event, **kwargs: events.append(
        {"event": event, **kwargs}
    )
    sys.modules["generated.repository.app.observability"] = observable

    module = types.ModuleType("generated.repository.app.runtime")
    module.__file__ = str(app / "runtime.py")
    module.__package__ = "generated.repository.app"
    sys.modules[module.__name__] = module
    exec(compile(RUNTIME_SOURCE, module.__file__, "exec"), module.__dict__)
    return module


def test_runtime_dispatches_verified_capability_through_generated_adapter(tmp_path, monkeypatch):
    runtime = _load_runtime(tmp_path)
    capability = {
        "id": "apiop:orders:create",
        "kind": "openapi",
        "side_effecting": False,
    }

    result = runtime._invoke_contract_adapter(
        capability,
        {"id": "42", "body": {"amount": 10}},
    )

    assert result["capability_id"] == "apiop:orders:create"
    assert result["response"]["adapter"] is True
    assert result["response"]["echo"]["body"]["amount"] == 10


def test_runtime_rejects_verified_capability_without_generated_adapter(tmp_path):
    runtime = _load_runtime(tmp_path)
    capability = {
        "id": "apiop:missing:create",
        "kind": "openapi",
        "side_effecting": False,
    }

    try:
        runtime._invoke_contract_adapter(capability, {})
    except RuntimeError as exc:
        assert "no generated adapter" in str(exc)
    else:
        raise AssertionError("missing contract adapter should fail closed")
