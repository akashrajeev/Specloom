"""Telegram bot: approval requests with Approve/Reject buttons, and change alerts.

Configured by SPECL00M_TELEGRAM_BOT_TOKEN and SPECL00M_TELEGRAM_CHAT_ID. Only the
configured chat can press buttons, and Telegram must present the webhook secret.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import urllib.request
from typing import Any

logger = logging.getLogger(__name__)
_MAX_TEXT = 3500


def _token() -> str:
    return os.getenv("SPECL00M_TELEGRAM_BOT_TOKEN", "").strip()


def chat_id() -> str:
    return os.getenv("SPECL00M_TELEGRAM_CHAT_ID", "").strip()


def enabled() -> bool:
    return bool(_token() and chat_id())


def webhook_secret() -> str:
    # Derived from the bot token, so there is no extra secret to manage.
    return hashlib.sha256(("specloom-webhook:" + _token()).encode()).hexdigest()[:48]


def secret_ok(header_value: str | None) -> bool:
    return bool(_token()) and hmac.compare_digest(str(header_value or ""), webhook_secret())


def _call(method: str, payload: dict[str, Any]) -> dict[str, Any]:
    request = urllib.request.Request(
        f"https://api.telegram.org/bot{_token()}/{method}",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=10) as response:  # noqa: S310 - fixed Telegram host
        return json.loads(response.read().decode("utf-8"))


def _safe_call(method: str, payload: dict[str, Any]) -> dict[str, Any] | None:
    if not enabled():
        return None
    try:
        return _call(method, payload)
    except Exception as exc:  # noqa: BLE001 - a notifier failure must never break a run
        logger.warning("telegram %s failed: %s", method, type(exc).__name__)
        return None


def _app_link(project_id: str) -> str:
    base = os.getenv("SPECL00M_APP_URL", "").rstrip("/")
    return f"\n\nOpen: {base}/?project={project_id}" if base else ""


def preview(value: Any) -> str:
    if isinstance(value, dict):
        for key in ("output", "text", "summary"):
            if key in value:
                return preview(value[key])
    if isinstance(value, list):
        return "\n\n".join(preview(item) for item in value[:3])
    text = value if isinstance(value, str) else json.dumps(value, indent=1, default=str)
    return text if len(text) <= _MAX_TEXT else text[: _MAX_TEXT - 1] + "…"


def send_approval_request(*, approval_id: str, project_id: str, node_id: str, input_data: Any) -> None:
    text = f"Specloom needs approval\nProject: {project_id}\nStep: {node_id}\n\n{preview(input_data)}{_app_link(project_id)}"
    payload: dict[str, Any] = {"chat_id": chat_id(), "text": text, "disable_web_page_preview": True}
    if len("a:" + approval_id) <= 64:
        payload["reply_markup"] = {"inline_keyboard": [[
            {"text": "Approve", "callback_data": "a:" + approval_id},
            {"text": "Reject", "callback_data": "r:" + approval_id},
        ]]}
    _safe_call("sendMessage", payload)


def send_change_alert(*, project_id: str, run_id: str, output: Any, note: str) -> None:
    text = f"Specloom: {note}\nProject: {project_id}\nRun: {run_id}\n\n{preview(output)}{_app_link(project_id)}"
    _safe_call("sendMessage", {"chat_id": chat_id(), "text": text, "disable_web_page_preview": True})


def handle_update(update: dict[str, Any], *, approve, reject) -> dict[str, Any]:
    """approve/reject are callables taking (project_id, run_id, node_id)."""
    query = update.get("callback_query") or {}
    if not query:
        message = update.get("message") or {}
        sender = str((message.get("from") or {}).get("id", ""))
        chat = str((message.get("chat") or {}).get("id", ""))
        if not chat_id() or chat != chat_id() or sender != chat_id() or not message.get("text"):
            return {"handled": False, "reason": "chat not allowed"}
        from backend.notify import telegram_bot
        return telegram_bot.handle_message(str(message["text"]))
    from_id = str((query.get("from") or {}).get("id", ""))
    chat = str(((query.get("message") or {}).get("chat") or {}).get("id", ""))
    if not chat_id() or chat != chat_id() or from_id != chat_id():
        _safe_call("answerCallbackQuery", {"callback_query_id": query.get("id"), "text": "Not allowed"})
        return {"handled": False, "reason": "chat not allowed"}
    data = str(query.get("data") or "")
    action, _, approval_id = data.partition(":")
    if action in {"c", "x"} and approval_id:
        from backend.notify import telegram_bot
        result = telegram_bot.handle_callback(action, approval_id)
        _safe_call("answerCallbackQuery", {"callback_query_id": query.get("id"), "text": result})
        return {"handled": True, "result": result}
    run_id, _, node_id = approval_id.rpartition(":")
    if action not in {"a", "r"} or not run_id or not node_id:
        return {"handled": False, "reason": "bad callback"}
    project_id = _project_for(approval_id)
    try:
        (approve if action == "a" else reject)(project_id, run_id, node_id)
        result = "Approved" if action == "a" else "Rejected"
    except Exception as exc:  # noqa: BLE001
        result = f"Could not update: {str(getattr(exc, 'detail', exc))[:150]}"
    _safe_call("answerCallbackQuery", {"callback_query_id": query.get("id"), "text": result})
    message = query.get("message") or {}
    if message.get("message_id"):
        _safe_call("editMessageText", {
            "chat_id": chat_id(),
            "message_id": message["message_id"],
            "text": (message.get("text") or "")[: _MAX_TEXT] + f"\n\n{result}",
            "disable_web_page_preview": True,
        })
    return {"handled": True, "result": result}


def _project_for(approval_id: str) -> str:
    import boto3

    table = boto3.resource("dynamodb").Table(os.getenv("SPECL00M_APPROVALS_TABLE", ""))
    item = table.get_item(Key={"approval_id": approval_id}).get("Item") or {}
    if not item.get("project_id"):
        raise ValueError("approval not found")
    return str(item["project_id"])


def set_webhook(url: str) -> dict[str, Any]:
    if not enabled():
        raise ValueError("Telegram is not configured")
    result = _call("setWebhook", {
        "url": url,
        "secret_token": webhook_secret(),
        "allowed_updates": ["callback_query", "message"],
        "drop_pending_updates": True,
    })
    _safe_call("setMyCommands", {"commands": [
        {"command": "new", "description": "Build a workflow from plain English"},
        {"command": "list", "description": "Your workflows"},
        {"command": "run", "description": "Run one now: /run <n>"},
        {"command": "pause", "description": "Pause a schedule: /pause <n>"},
        {"command": "resume", "description": "Resume a schedule: /resume <n>"},
    ]})
    return result
