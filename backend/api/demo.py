from __future__ import annotations

import json
from pathlib import Path

from fastapi import APIRouter, HTTPException

from backend.context.store import store
from backend.workflow.models import WorkflowIR

router = APIRouter(prefix="/api/v1/demo", tags=["demo"])

DEMO_PROJECT = "demo-price-watch"
_FIXTURE = Path(__file__).resolve().parents[2] / "examples" / "demo-price-watch.json"


@router.post("/phone-approval")
def start_phone_approval_demo() -> dict:
    """One click: a prebuilt, verified workflow reads 3 live pages and waits for a phone approval."""
    from backend.api.runtime import _run_and_record
    from backend.notify import telegram

    workflow = WorkflowIR.model_validate(json.loads(_FIXTURE.read_text()))
    store.forget(DEMO_PROJECT)
    store.set_workflow(DEMO_PROJECT, workflow)
    try:
        result = _run_and_record(DEMO_PROJECT, workflow, {}, trigger="demo")
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"{type(exc).__name__}: {exc}"[:800]) from exc
    return {
        "project_id": DEMO_PROJECT,
        "run_id": result.get("run_id"),
        "status": result.get("status"),
        "telegram": telegram.enabled(),
    }
