from backend.notify import telegram, telegram_bot
from backend.notify.telegram_bot import parse_schedule, human_schedule


def _setup(monkeypatch):
    monkeypatch.setenv("SPECL00M_TELEGRAM_BOT_TOKEN", "123:abc")
    monkeypatch.setenv("SPECL00M_TELEGRAM_CHAT_ID", "42")
    calls = []
    monkeypatch.setattr(telegram, "_call", lambda method, payload: calls.append((method, payload)) or {"ok": True})
    from backend.storage.build_jobs import build_jobs
    build_jobs._memory.pop(telegram_bot.SESSION_KEY, None)
    return calls


def _msg(text, sender=42):
    return {"message": {"text": text, "chat": {"id": sender}, "from": {"id": sender}}}


def _noop(*a):
    raise AssertionError("not an approval")


def test_parse_schedule():
    assert parse_schedule("every day at 8am check prices") == "0 8 * * *"
    assert parse_schedule("daily 7:30 pm") == "30 19 * * *"
    assert parse_schedule("every monday 9am") == "0 9 * * 1"
    assert parse_schedule("weekdays at 6pm") == "0 18 * * 1-5"
    assert parse_schedule("every 2 hours") == "0 */2 * * *"
    assert parse_schedule("every 1 minute") == "*/5 * * * *"
    assert parse_schedule("manual") == "manual"
    assert parse_schedule("summarize these pages") is None
    assert human_schedule({"mode": "schedule", "cron": "0 8 * * *"}) == "every day at 08:00 IST"
    assert human_schedule({"mode": "schedule", "cron": "0 9 * * 1"}) == "every Monday at 09:00 IST"


def test_other_chats_are_ignored(monkeypatch):
    calls = _setup(monkeypatch)
    result = telegram.handle_update(_msg("/list", sender=7), approve=_noop, reject=_noop)
    assert result["handled"] is False and calls == []


def test_new_asks_when_then_builds_and_creates(monkeypatch):
    calls = _setup(monkeypatch)
    started = []
    monkeypatch.setattr(telegram_bot, "_start_build", lambda pid, goal, answers: started.append((pid, goal, answers)) or "job1")
    telegram.handle_update(_msg("/new read https://books.toscrape.com and summarize prices"), approve=_noop, reject=_noop)
    assert "When should it run" in calls[-1][1]["text"] and not started
    telegram.handle_update(_msg("every day 8am"), approve=_noop, reject=_noop)
    assert started and "08:00 IST" in calls[-1][1]["text"] or "08:00 IST" in calls[-2][1]["text"]
    project_id = started[0][0]

    from backend.context.store import store
    from backend.api.build import build, BuildRequestBody
    result = build(project_id, BuildRequestBody(goal=started[0][1], gap_answers={}))
    telegram_bot.on_build_finished(project_id, "job1", result, None)
    plan = calls[-1][1]
    assert "Plan:" in plan["text"] and "every day at 08:00 IST" in plan["text"] and "Checks:" in plan["text"]
    assert plan["reply_markup"]["inline_keyboard"][0][0]["callback_data"] == f"c:{project_id}"
    store.forget(project_id)
    config = store.get(project_id).workflow.trigger.config
    assert config["cron"] == "0 8 * * *" and config["schedule_enabled"] is False

    telegram.handle_update({"callback_query": {"id": "q", "data": f"c:{project_id}", "from": {"id": 42}, "message": {"chat": {"id": 42}}}}, approve=_noop, reject=_noop)
    store.forget(project_id)
    assert store.get(project_id).workflow.trigger.config["schedule_enabled"] is True

    telegram.handle_update(_msg("/list"), approve=_noop, reject=_noop)
    listing = calls[-1][1]["text"]
    assert project_id in listing and "active" in listing
    number = next(line.split(".")[0] for line in listing.splitlines() if project_id in line)
    telegram.handle_update(_msg(f"/pause {number}"), approve=_noop, reject=_noop)
    assert calls[-1][1]["text"] == f"Paused {project_id}."
    telegram.handle_update(_msg(f"/resume {project_id}"), approve=_noop, reject=_noop)
    assert calls[-1][1]["text"] == f"Resumed {project_id}."


def test_gap_question_uses_reply(monkeypatch):
    calls = _setup(monkeypatch)
    started = []
    monkeypatch.setattr(telegram_bot, "_start_build", lambda pid, goal, answers: started.append(answers) or f"job{len(started)}")
    telegram.handle_update(_msg("/new every day 8am email me the prices"), approve=_noop, reject=_noop)
    pid = telegram_bot._session()["target_project"]
    telegram_bot.on_build_finished(pid, "job1", {"ready": False, "gaps": [{"id": "g1", "severity": "blocking", "question": "Which pages?"}]}, None)
    assert "Which pages?" in calls[-1][1]["text"]
    telegram.handle_update(_msg("books.toscrape.com"), approve=_noop, reject=_noop)
    assert started[-1] == {"g1": "books.toscrape.com"}
