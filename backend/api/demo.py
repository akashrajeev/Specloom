from __future__ import annotations

import json
from pathlib import Path

from fastapi import APIRouter, HTTPException

from backend.context.store import store
from backend.workflow.models import WorkflowIR

router = APIRouter(prefix="/api/v1/demo", tags=["demo"])

DEMO_PROJECT = "demo-price-watch"
_FIXTURE = Path(__file__).resolve().parents[2] / "examples" / "demo-price-watch.json"


def _expire_stale_demo_approvals(max_age_minutes: int = 10) -> int:
    """Visitors often leave a demo run waiting at approval. Reject those after a while so the
    demo project doesn't show an old pending approval to the next visitor."""
    import re
    from datetime import datetime, timedelta, timezone

    try:
        from backend.runtime.durable import DurableApprovalBroker

        broker = DurableApprovalBroker()
        pending = broker.list_pending(project_id=DEMO_PROJECT)
    except Exception:  # noqa: BLE001 - cleanup must never block the demo
        return 0
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=max_age_minutes)
    expired = 0
    for item in pending:
        match = re.match(r"run_(\d{14})", str(item.get("approval_id", "")))
        if not match:
            continue
        started = datetime.strptime(match.group(1), "%Y%m%d%H%M%S").replace(tzinfo=timezone.utc)
        if started >= cutoff:
            continue
        try:
            broker.reject(project_id=DEMO_PROJECT, approval_id=item["approval_id"], reason="Demo expired")
            expired += 1
        except Exception:  # noqa: BLE001
            continue
    return expired


@router.post("/phone-approval")
def start_phone_approval_demo() -> dict:
    """One click: a prebuilt, verified workflow reads 3 live pages and waits for a phone approval."""
    from backend.api.runtime import _run_and_record
    from backend.notify import telegram

    _expire_stale_demo_approvals()
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
