from backend.notify import telegram


def _setup(monkeypatch):
    monkeypatch.setenv("SPECL00M_TELEGRAM_BOT_TOKEN", "123:abc")
    monkeypatch.setenv("SPECL00M_TELEGRAM_CHAT_ID", "42")
    calls = []
    monkeypatch.setattr(telegram, "_call", lambda method, payload: calls.append((method, payload)) or {"ok": True})
    monkeypatch.setattr(telegram, "_project_for", lambda approval_id: "proj")
    return calls


def test_approval_request_has_buttons(monkeypatch):
    calls = _setup(monkeypatch)
    telegram.send_approval_request(approval_id="run_1:approve", project_id="proj", node_id="approve",
                                   input_data={"output": [{"text": "Price: 10"}]})
    method, payload = calls[0]
    assert method == "sendMessage" and "Price: 10" in payload["text"]
    assert payload["reply_markup"]["inline_keyboard"][0][0]["callback_data"] == "a:run_1:approve"


def test_only_the_configured_chat_can_approve(monkeypatch):
    _setup(monkeypatch)
    seen = []
    approve = lambda p, r, n: seen.append((p, r, n))
    stranger = {"callback_query": {"id": "q", "data": "a:run_1:approve", "from": {"id": 7}, "message": {"chat": {"id": 7}}}}
    assert telegram.handle_update(stranger, approve=approve, reject=approve)["handled"] is False
    owner = {"callback_query": {"id": "q", "data": "a:run_1:approve", "from": {"id": 42}, "message": {"chat": {"id": 42}, "message_id": 5, "text": "x"}}}
    assert telegram.handle_update(owner, approve=approve, reject=approve)["result"] == "Approved"
    assert seen == [("proj", "run_1", "approve")]


def test_webhook_rejects_wrong_secret(monkeypatch):
    _setup(monkeypatch)
    assert telegram.secret_ok(telegram.webhook_secret())
    assert not telegram.secret_ok("nope")


def test_disabled_without_config(monkeypatch):
    monkeypatch.delenv("SPECL00M_TELEGRAM_BOT_TOKEN", raising=False)
    calls = []
    monkeypatch.setattr(telegram, "_call", lambda *a: calls.append(a))
    telegram.send_change_alert(project_id="p", run_id="r", output="x", note="changed")
    assert calls == []
