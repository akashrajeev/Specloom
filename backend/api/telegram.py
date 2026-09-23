from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

from backend.notify import telegram

router = APIRouter(prefix="/api/v1/telegram", tags=["telegram"])


def _webhook_url(request: Request) -> str:
    event = request.scope.get("aws.event") or {}
    ctx = event.get("requestContext") or {}
    host = (event.get("headers") or {}).get("Host") or request.headers.get("host", "")
    stage = ctx.get("stage")
    if host and stage:
        return f"https://{host}/{stage}/api/v1/telegram/webhook"
    return str(request.url).replace("/setup", "/webhook")


@router.get("/status")
def status() -> dict:
    return {"configured": telegram.enabled()}


@router.post("/setup")
def setup(request: Request) -> dict:
    try:
        result = telegram.set_webhook(_webhook_url(request))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=type(exc).__name__) from exc
    return {"ok": bool(result.get("ok")), "description": result.get("description")}


@router.post("/webhook")
async def webhook(request: Request) -> dict:
    if not telegram.secret_ok(request.headers.get("x-telegram-bot-api-secret-token")):
        raise HTTPException(status_code=403, detail="forbidden")
    from backend.api.runtime import approve_durable, reject_durable

    update = await request.json()
    return telegram.handle_update(
        update,
        approve=lambda p, r, n: approve_durable(p, r, n),
        reject=lambda p, r, n: reject_durable(p, r, n, reason="Rejected in Telegram"),
    )
