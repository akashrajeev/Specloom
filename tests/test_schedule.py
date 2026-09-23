from datetime import datetime, timezone

import pytest

from backend.runtime import schedule


def utc(*args):
    return datetime(*args, tzinfo=timezone.utc)


def test_daily_8am_ist_fires_once_in_its_window():
    # 08:00 IST = 02:30 UTC
    assert schedule.due_time("0 8 * * *", utc(2026, 9, 24, 2, 26), utc(2026, 9, 24, 2, 31), "Asia/Kolkata") == utc(2026, 9, 24, 2, 30)
    assert schedule.due_time("0 8 * * *", utc(2026, 9, 24, 2, 31), utc(2026, 9, 24, 2, 36), "Asia/Kolkata") is None


def test_cron_fields_steps_ranges_and_weekdays():
    fields = schedule.parse_cron("*/15 9-17 * * mon-fri")
    assert schedule.cron_matches(fields, datetime(2026, 9, 23, 9, 45))  # Wednesday
    assert not schedule.cron_matches(fields, datetime(2026, 9, 27, 9, 45))  # Sunday
    assert not schedule.cron_matches(fields, datetime(2026, 9, 23, 9, 50))
    with pytest.raises(ValueError):
        schedule.parse_cron("61 * * * *")


def test_change_marker_flags_only_real_changes():
    runs = [{"run_id": "old", "trigger": "schedule", "status": "completed",
             "output_fingerprint": schedule.output_fingerprint({"price": 10})}]
    assert schedule.change_marker(runs, "new", {"price": 10})["changed"] is False
    assert schedule.change_marker(runs, "new", {"price": 9})["changed"] is True
    assert schedule.change_marker([], "new", {"price": 9})["change_note"] == "first scheduled result"


def test_sweep_starts_due_workflow_and_skips_others(monkeypatch):
    from backend.api import runtime as runtime_api
    from backend.context.store import store
    from backend.workflow.models import WorkflowIR

    import json
    from pathlib import Path

    data = json.loads(Path("examples/support-triage.json").read_text())
    data["trigger"]["config"] = {"mode": "schedule", "cron": "*/5 * * * *"}
    wf = WorkflowIR.model_validate(data)
    store.set_workflow("sched-a", wf)
    store.set_workflow("researchhunter", wf)
    started = []
    monkeypatch.setattr(runtime_api, "_run_and_record", lambda pid, w, data, trigger: started.append((pid, trigger)) or {"run_id": "x"})
    result = schedule.sweep(utc(2026, 9, 24, 3, 0))
    assert ("sched-a", "schedule") in started
    assert all(pid != "researchhunter" for pid, _ in started)
    assert not result["errors"]
