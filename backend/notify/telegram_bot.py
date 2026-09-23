"""Telegram-first workflows: /new builds a workflow from plain English, then /list, /pause, /resume, /run.

Only the configured chat (SPECL00M_TELEGRAM_CHAT_ID) is obeyed. A built workflow stays paused until
the owner taps Create, so nothing runs on a schedule without an explicit yes.
"""
from __future__ import annotations

import logging
import re
import uuid
from typing import Any

from backend.notify import telegram

logger = logging.getLogger(__name__)
SESSION_KEY = ("telegram-session", "current")
HELP = (
    "Specloom commands:\n"
    "/new <what it should do> - build a workflow, e.g. /new every day 8am check these pages and summarize prices\n"
    "/list - your workflows\n"
    "/run <n> - run one now\n"
    "/pause <n> and /resume <n> - stop or restart its schedule\n"
    "<n> is the number from /list, or the project id."
)


def _jobs():
    from backend.storage.build_jobs import build_jobs
    return build_jobs


def _session() -> dict[str, Any]:
    return _jobs().get(*SESSION_KEY) or {}


def _save_session(**values: Any) -> None:
    current = _session()
    current.update(values)
    current.update({"project_id": SESSION_KEY[0], "run_id": SESSION_KEY[1]})
    _jobs().put(current)


def _say(text: str, buttons: list[list[dict[str, str]]] | None = None) -> None:
    payload: dict[str, Any] = {"chat_id": telegram.chat_id(), "text": text[:4000], "disable_web_page_preview": True}
    if buttons:
        payload["reply_markup"] = {"inline_keyboard": buttons}
    telegram._safe_call("sendMessage", payload)  # noqa: SLF001


_SLUG_SKIP = {
    "every", "day", "daily", "the", "and", "me", "a", "an", "to", "of", "at", "these", "this", "that", "on", "in",
    "for", "from", "with", "it", "its", "my", "read", "check", "tell", "then", "each", "am", "pm", "morning",
    "evening", "night", "hour", "hours", "minute", "minutes", "weekday", "weekdays", "ask", "before", "after",
    "send", "give", "show", "please", "page", "pages", "site", "website", "url", "is", "are", "be", "i", "if",
    "monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday", "summarize", "summary",
}


def _slug(goal: str) -> str:
    text = re.sub(r"https?://\S+", " ", goal.lower())
    words = [w for w in re.findall(r"[a-z]+", text) if w not in _SLUG_SKIP and len(w) > 2]
    base = "-".join(dict.fromkeys(words))
    base = "-".join(base.split("-")[:3])[:28].strip("-")
    return f"{base or 'workflow'}-{uuid.uuid4().hex[:4]}"


def _start_build(project_id: str, goal: str, gap_answers: dict[str, str]) -> str:
    from backend.api.build import AsyncBuildRequest, start_async_build

    result = start_async_build(project_id, AsyncBuildRequest(goal=goal, gap_answers=gap_answers))
    return str(result["run_id"])


_DAYS = {"sunday": 0, "monday": 1, "tuesday": 2, "wednesday": 3, "thursday": 4, "friday": 5, "saturday": 6}


def parse_schedule(text: str) -> str | None:
    """Plain-English schedule to a 5-field cron (IST). "manual" for on-demand, None if unclear."""
    t = text.lower()
    if re.search(r"\b(manual|on demand|only when i ask|when i run it|no schedule)\b", t):
        return "manual"
    m = re.search(r"every\s+(\d+)\s*(?:min|minute)s?\b", t)
    if m:
        return f"*/{max(5, int(m.group(1)))} * * * *"
    m = re.search(r"every\s+(\d+)\s*(?:h|hr|hour)s?\b", t)
    if m:
        return f"0 */{max(1, int(m.group(1)))} * * *"
    if re.search(r"\b(every hour|hourly)\b", t):
        return "0 * * * *"
    time_match = re.search(r"\b(\d{1,2})(?::(\d{2}))?\s*(am|pm)\b", t) or re.search(r"\b(?:at\s+)(\d{1,2}):(\d{2})\b()", t)
    if not time_match:
        return None
    hour, minute = int(time_match.group(1)), int(time_match.group(2) or 0)
    meridiem = time_match.group(3)
    if meridiem == "pm" and hour < 12:
        hour += 12
    if meridiem == "am" and hour == 12:
        hour = 0
    if hour > 23 or minute > 59:
        return None
    days = [str(v) for k, v in _DAYS.items() if re.search(rf"\b{k}s?\b", t)]
    if days:
        return f"{minute} {hour} * * {','.join(days)}"
    if re.search(r"\b(weekday|weekdays)\b", t):
        return f"{minute} {hour} * * 1-5"
    if re.search(r"\b(every ?day|daily|each day|every morning|every evening|every night|tomorrow|at)\b", t):
        return f"{minute} {hour} * * *"
    return None


def _apply_schedule(project_id: str, cron: str) -> None:
    from backend.context.store import store

    store.forget(project_id)
    project = store.get(project_id)
    if project.workflow is None:
        return
    workflow = project.workflow.model_copy(deep=True)
    config = dict(workflow.trigger.config or {})
    if cron == "manual":
        config.update({"mode": "manual"})
    else:
        config.update({"mode": "schedule", "cron": cron, "timezone": "Asia/Kolkata", "schedule_enabled": False})
    workflow.trigger.config = config
    store.set_workflow(project_id, workflow)


def human_schedule(config: dict[str, Any]) -> str:
    if config.get("mode") != "schedule" or not config.get("cron"):
        return "runs when you start it (/run)"
    parts = str(config["cron"]).split()
    if len(parts) == 5 and parts[0].isdigit() and parts[1].isdigit() and parts[2:] == ["*", "*", "*"]:
        return f"every day at {int(parts[1]):02d}:{int(parts[0]):02d} IST"
    if len(parts) == 5 and parts[0].isdigit() and parts[1].isdigit() and parts[2:4] == ["*", "*"]:
        names = {str(v): k.title() for k, v in _DAYS.items()}
        days = "weekdays" if parts[4] == "1-5" else ", ".join(names.get(d, d) for d in parts[4].split(","))
        return f"every {days} at {int(parts[1]):02d}:{int(parts[0]):02d} IST"
    if parts[0].startswith("*/"):
        return f"every {parts[0][2:]} minutes"
    if parts[:2] == ["0", "*"]:
        return "every hour"
    if parts[0] == "0" and parts[1].startswith("*/"):
        return f"every {parts[1][2:]} hours"
    return f"cron {config['cron']} (IST)"


def plan_text(build: dict[str, Any]) -> str:
    workflow = build.get("workflow") or {}
    trigger = workflow.get("trigger") or {}
    lines = [f"Plan: {workflow.get('name') or workflow.get('id')}", f"When: {human_schedule(trigger.get('config') or {})}", "Steps:"]
    for index, node in enumerate(workflow.get("nodes") or [], 1):
        kind = node.get("type")
        tools = (node.get("config") or {}).get("tools") or []
        label = {
            "agent": "AI step" + (f" (reads with {', '.join(tools)})" if tools else ""),
            "tool": "Tool",
            "human_approval": "Waits for your approval here (Telegram buttons)",
            "output": "Returns the result",
        }.get(kind, kind)
        lines.append(f"{index}. {node.get('name') or node.get('id')} - {label}")
    evaluation = build.get("evaluation") or {}
    if evaluation:
        lines.append(f"Checks: {evaluation.get('passed', 0)}/{len(evaluation.get('tests') or [])} tests passed, structure and permissions validated")
    approvals = sum(1 for n in workflow.get("nodes") or [] if n.get("type") == "human_approval")
    lines.append(f"Safety: {approvals} approval gate(s); AI steps answer only from pages they actually read, with sources")
    if build.get("degraded_architecture"):
        lines.append("Note: AI quota was out, so this uses the built-in template design.")
    return "\n".join(lines)


def on_build_finished(project_id: str, run_id: str, result: dict[str, Any] | None, error: str | None) -> None:
    """Called by the async build worker; only acts on builds started from Telegram."""
    if not telegram.enabled():
        return
    session = _session()
    if session.get("target_project") != project_id or session.get("state") != "building" or session.get("build_run_id") not in (None, run_id):
        return
    if error:
        _save_session(state="idle")
        _say(f"The build failed: {error[:500]}\nTry /new again with a bit more detail.")
        return
    result = result or {}
    if not result.get("ready", True) and result.get("gaps"):
        blocking = [g for g in result["gaps"] if g.get("severity") == "blocking"] or result["gaps"]
        gap = blocking[0]
        _save_session(state="awaiting_answer", gap_id=gap.get("id"))
        _say(f"One question before I build it:\n{gap.get('question')}\n\nJust reply with your answer.")
        return
    _apply_schedule(project_id, str(session.get("cron") or "manual"))  # saved paused
    from backend.context.store import store

    store.forget(project_id)
    project = store.get(project_id)
    if project.workflow is not None:
        result = {**result, "workflow": project.workflow.model_dump(mode="json")}
    _save_session(state="awaiting_create")
    _say(plan_text(result), [[{"text": "Create", "callback_data": f"c:{project_id}"},
                              {"text": "Cancel", "callback_data": f"x:{project_id}"}]])


def _workflow_projects() -> list[tuple[str, Any]]:
    from backend.context.store import store

    items = []
    for project_id in sorted(store.list_project_ids(limit=100)):
        store.forget(project_id)
        project = store.get(project_id)
        if project.workflow is not None and project_id != "telegram-session":
            items.append((project_id, project))
    return items


def _resolve(arg: str) -> str | None:
    arg = arg.strip()
    projects = [pid for pid, _ in _workflow_projects()]
    if arg.isdigit() and 1 <= int(arg) <= len(projects):
        return projects[int(arg) - 1]
    return arg if arg in projects else None


def _set_enabled(project_id: str, enabled: bool) -> bool:
    from backend.context.store import store

    store.forget(project_id)
    project = store.get(project_id)
    if project.workflow is None:
        return False
    config = dict(project.workflow.trigger.config or {})
    if config.get("mode") != "schedule":
        return False
    config["schedule_enabled"] = enabled
    workflow = project.workflow.model_copy(deep=True)
    workflow.trigger.config = config
    store.set_workflow(project_id, workflow)
    return True


def _pause(project_id: str, quiet: bool = False) -> None:
    changed = _set_enabled(project_id, False)
    if not quiet:
        _say(f"Paused {project_id}." if changed else f"{project_id} has no schedule to pause.")


def _begin(project_id: str, goal: str, cron: str) -> None:
    _save_session(state="building", target_project=project_id, goal=goal, gap_answers={}, cron=cron, build_run_id=None)
    when = f"It will run {human_schedule({'mode': 'schedule', 'cron': cron})}" if cron != "manual" else "It will run only when you use /run"
    _say(f"Building it now (about 2 minutes). {when}, once you tap Create.")
    run_id = _start_build(project_id, goal, {})
    _save_session(build_run_id=run_id)


def handle_message(text: str) -> dict[str, Any]:
    text = (text or "").strip()
    command, _, arg = text.partition(" ")
    command = command.split("@", 1)[0].lower()
    if command in {"/start", "/help"}:
        _say(HELP)
    elif command == "/new":
        goal = arg.strip()
        if len(goal) < 10:
            _say("Tell me what it should do, e.g. /new every day 8am read these 3 pages and summarize the prices")
            return {"handled": True}
        project_id = _slug(goal)
        cron = parse_schedule(goal)
        if cron is None:
            _save_session(state="awaiting_schedule", target_project=project_id, goal=goal, gap_answers={}, cron=None, build_run_id=None)
            _say("When should it run? For example: every day 8am, every Monday 9:30am, every 2 hours, or manual.")
            return {"handled": True}
        _begin(project_id, goal, cron)
    elif command == "/list":
        items = _workflow_projects()
        if not items:
            _say("No workflows yet. Try /new")
        else:
            lines = []
            for index, (pid, project) in enumerate(items, 1):
                config = project.workflow.trigger.config or {}
                state = "paused" if config.get("schedule_enabled") is False else "active"
                last = next((r.get("status") for r in project.runs if r.get("kind") == "runtime"), "no runs")
                schedule = human_schedule(config)
                lines.append(f"{index}. {project.workflow.name} ({pid})\n   {schedule}" + (f" - {state}" if config.get("mode") == "schedule" else "") + f" - last run: {last}")
            _say("\n".join(lines))
    elif command in {"/pause", "/resume", "/run"}:
        project_id = _resolve(arg)
        if not project_id:
            _say("Which one? Use the number from /list.")
        elif command == "/pause":
            _pause(project_id)
        elif command == "/resume":
            _say(f"Resumed {project_id}." if _set_enabled(project_id, True) else f"{project_id} has no schedule.")
        else:
            from backend.api.runtime import _run_and_record
            from backend.context.store import store

            store.forget(project_id)
            workflow = store.get(project_id).workflow
            result = _run_and_record(project_id, workflow, {}, trigger="telegram")
            _say(f"Started {project_id} ({result.get('run_id')}). If it has an approval step, the buttons will show up here.")
    elif not text.startswith("/"):
        session = _session()
        if session.get("state") == "awaiting_schedule":
            cron = parse_schedule(text)
            if cron is None:
                _say("Sorry, I didn't get the timing. Try: every day 8am, every Friday 6pm, every 30 minutes, or manual.")
            else:
                _begin(str(session["target_project"]), str(session["goal"]), cron)
        elif session.get("state") == "awaiting_answer" and session.get("gap_id"):
            answers = dict(session.get("gap_answers") or {})
            answers[str(session["gap_id"])] = text
            run_id = _start_build(str(session["target_project"]), str(session["goal"]), answers)
            _save_session(state="building", gap_answers=answers, build_run_id=run_id, gap_id=None)
            _say("Got it. Building now (about 2 minutes).")
        else:
            _say(HELP)
    else:
        _say(HELP)
    return {"handled": True}


def handle_callback(action: str, project_id: str) -> str:
    if action == "c":
        from backend.context.store import store

        store.forget(project_id)
        project = store.get(project_id)
        if project.workflow is None:
            return "That workflow is gone"
        config = project.workflow.trigger.config or {}
        if config.get("mode") == "schedule":
            _set_enabled(project_id, True)
        _save_session(state="idle")
        when = f"It will run {human_schedule(config)}" if config.get("mode") == "schedule" else "It runs only when you use /run"
        _say(f"Created {project.workflow.name}. {when}.\nUse /list to see it, /run to run it now.")
        return "Created"
    _pause(project_id, quiet=True)
    _save_session(state="idle")
    _say(f"Cancelled. {project_id} stays paused and won't run.")
    return "Cancelled"
