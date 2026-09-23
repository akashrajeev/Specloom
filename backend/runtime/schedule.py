"""Per-workflow schedules: a 5-minute sweep starts every workflow whose cron came due.

Change-only alerts: when a scheduled run finishes, its output is compared with the last
finished scheduled run, so the UI (and later a notifier) only flags real changes.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

logger = logging.getLogger(__name__)

_RANGES = [(0, 59), (0, 23), (1, 31), (1, 12), (0, 7)]
_NAMES = {
    3: {m: i + 1 for i, m in enumerate("jan feb mar apr may jun jul aug sep oct nov dec".split())},
    4: {d: i for i, d in enumerate("sun mon tue wed thu fri sat".split())},
}


def _field(spec: str, index: int) -> set[int]:
    low, high = _RANGES[index]
    values: set[int] = set()
    for part in spec.lower().split(","):
        step = 1
        if "/" in part:
            part, step_text = part.split("/", 1)
            step = int(step_text)
            if step < 1:
                raise ValueError("cron step must be positive")
        if part in {"*", "?"}:
            start, end = low, high
        elif "-" in part:
            a, b = part.split("-", 1)
            start, end = _value(a, index), _value(b, index)
        else:
            start = _value(part, index)
            end = high if step > 1 else start
        if start < low or end > high or start > end:
            raise ValueError(f"cron value out of range: {spec}")
        values.update(range(start, end + 1, step))
    if index == 4 and 7 in values:
        values.add(0)
    return values


def _value(text: str, index: int) -> int:
    return _NAMES.get(index, {}).get(text) if text in _NAMES.get(index, {}) else int(text)


def parse_cron(expr: str) -> list[set[int]]:
    parts = expr.split()
    if len(parts) != 5:
        raise ValueError("cron needs 5 fields: minute hour day month weekday")
    return [_field(part, i) for i, part in enumerate(parts)]


def cron_matches(fields: list[set[int]], moment: datetime) -> bool:
    minute, hour, dom, month, dow = fields
    if moment.minute not in minute or moment.hour not in hour or moment.month not in month:
        return False
    weekday = (moment.weekday() + 1) % 7  # cron: Sunday = 0
    dom_any = len(dom) == 31
    dow_any = len(dow) >= 7
    if dom_any or dow_any:
        return moment.day in dom and weekday in dow
    return moment.day in dom or weekday in dow


def due_time(expr: str, after: datetime, until: datetime, tz: str) -> datetime | None:
    """Latest cron minute in (after, until], evaluated in the workflow's timezone."""
    fields = parse_cron(expr)
    zone = ZoneInfo(tz)
    cursor = until.astimezone(zone).replace(second=0, microsecond=0)
    floor = max(after, until - timedelta(days=1)).astimezone(zone)
    while cursor > floor:
        if cron_matches(fields, cursor):
            return cursor.astimezone(timezone.utc)
        cursor -= timedelta(minutes=1)
    return None


def _parse_time(value: Any) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def output_fingerprint(output: Any) -> str:
    text = json.dumps(output, sort_keys=True, default=str)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def change_marker(runs: list[dict], run_id: str, output: Any) -> dict:
    """Compare a finished scheduled run with the previous finished scheduled run."""
    fingerprint = output_fingerprint(output)
    previous = next(
        (
            run for run in runs
            if run.get("run_id") != run_id
            and run.get("trigger") == "schedule"
            and run.get("status") == "completed"
            and run.get("output_fingerprint")
        ),
        None,
    )
    if previous is None:
        return {"output_fingerprint": fingerprint, "changed": True, "change_note": "first scheduled result"}
    changed = previous["output_fingerprint"] != fingerprint
    return {
        "output_fingerprint": fingerprint,
        "changed": changed,
        "change_note": "output changed since the last scheduled run" if changed else "same as the last scheduled run",
        "compared_with": previous.get("run_id"),
    }


def sweep(now: datetime | None = None) -> dict:
    from backend.api.runtime import _run_and_record, get_run
    from backend.context.store import store

    now = now or datetime.now(timezone.utc)
    window = timedelta(minutes=int(os.getenv("SPECL00M_SCHEDULE_SWEEP_MINUTES", "5")))
    default_tz = os.getenv("SPECL00M_SCHEDULE_TIMEZONE", "Asia/Kolkata")
    skip = {p.strip() for p in os.getenv("SPECL00M_SCHEDULE_SKIP_PROJECTS", "researchhunter").split(",") if p.strip()}
    started: list[dict] = []
    refreshed: list[str] = []
    errors: list[str] = []

    for project_id in store.list_project_ids(limit=100):
        try:
            store.forget(project_id)
            project = store.get(project_id)
            # Finish bookkeeping for scheduled runs still in flight (status + change marker).
            for run in list(project.runs):
                if run.get("trigger") == "schedule" and run.get("status") == "running":
                    get_run(project_id, str(run["run_id"]))
                    refreshed.append(str(run["run_id"]))
            workflow = project.workflow
            if project_id in skip or workflow is None:
                continue
            config = workflow.trigger.config or {}
            cron = str(config.get("cron") or "").strip()
            if config.get("mode") != "schedule" or not cron or config.get("schedule_enabled") is False:
                continue
            last = max(
                (t for t in (_parse_time(r.get("created_at")) for r in project.runs if r.get("trigger") == "schedule") if t),
                default=now - window,
            )
            due = due_time(cron, max(last, now - window), now, str(config.get("timezone") or default_tz))
            if due is None:
                continue
            result = _run_and_record(project_id, workflow, {"scheduled_for": due.isoformat()}, trigger="schedule")
            started.append({"project_id": project_id, "run_id": result.get("run_id"), "scheduled_for": due.isoformat()})
        except Exception as exc:  # noqa: BLE001 - one bad project must not stop the sweep
            logger.warning("schedule sweep failed for %s: %s", project_id, exc)
            errors.append(f"{project_id}: {type(exc).__name__}: {exc}"[:300])
    return {"started": started, "refreshed": refreshed, "errors": errors, "at": now.isoformat()}
