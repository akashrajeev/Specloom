"""Paper-trading demo: live quotes -> approval request -> simulated buy after approval.

No brokerage, no real money. The approval is a signed, short-lived token, so the server keeps no state.
Quotes come from Yahoo Finance's public chart endpoint (unofficial, no key, may be delayed); every quote
carries its own market timestamp so stale data is never shown as real-time.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import time
from typing import Any
from urllib.parse import quote
from urllib.request import Request, urlopen

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

router = APIRouter(prefix="/api/v1/demo/stock", tags=["demo"])

WATCHLIST = ["AAPL", "MSFT", "NVDA", "RELIANCE.NS", "TCS.NS"]
PAPER_BUDGET = 10_000  # in the stock's own currency
TOKEN_TTL_SECONDS = 600
STALE_AFTER_SECONDS = 20 * 60
MAX_SLIPPAGE_PCT = 1.0  # fill is refused if the price moved more than this since approval was requested
_USED_NONCES: dict[str, float] = {}  # best-effort single use per server instance
SOURCE = "Yahoo Finance public chart endpoint (unofficial; can be delayed)"
_SECRET = (os.getenv("STOCK_DEMO_SECRET") or "specloom-paper-demo-not-a-secret").encode()


def fetch_quote(symbol: str, now: float | None = None) -> dict[str, Any]:
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{quote(symbol)}?interval=1m&range=1d"
    request = Request(url, headers={"User-Agent": "Mozilla/5.0 (Specloom paper-trading demo)"})
    with urlopen(request, timeout=10) as response:  # noqa: S310 - fixed https host
        payload = json.loads(response.read().decode())
    result = (payload.get("chart", {}).get("result") or [None])[0]
    if not result:
        raise ValueError(f"no quote for {symbol}")
    meta = result["meta"]
    price = float(meta["regularMarketPrice"])
    prev = float(meta.get("chartPreviousClose") or meta.get("previousClose") or price)
    traded_at = int(meta["regularMarketTime"])
    age = int((now if now is not None else time.time()) - traded_at)
    return {
        "symbol": symbol,
        "name": meta.get("shortName") or symbol,
        "price": round(price, 2),
        "currency": meta.get("currency", ""),
        "previous_close": round(prev, 2),
        "change_pct": round((price - prev) / prev * 100, 2) if prev else 0.0,
        "market_time": traded_at,
        "age_seconds": max(age, 0),
        "fresh": age <= STALE_AFTER_SECONDS,
        "exchange": meta.get("fullExchangeName", ""),
    }


def get_quotes(symbols: list[str]) -> tuple[list[dict], list[dict]]:
    quotes, errors = [], []
    for symbol in symbols:
        try:
            quotes.append(fetch_quote(symbol))
        except Exception as exc:  # noqa: BLE001 - one bad symbol must not hide the rest
            errors.append({"symbol": symbol, "error": f"{type(exc).__name__}: {exc}"[:200]})
    return quotes, errors


def _sign(body: dict) -> str:
    raw = base64.urlsafe_b64encode(json.dumps(body, sort_keys=True).encode()).decode()
    sig = hmac.new(_SECRET, raw.encode(), hashlib.sha256).hexdigest()
    return f"{raw}.{sig}"


def _verify(token: str, now: float | None = None) -> dict:
    try:
        raw, sig = token.rsplit(".", 1)
        expected = hmac.new(_SECRET, raw.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(sig, expected):
            raise ValueError("bad signature")
        body = json.loads(base64.urlsafe_b64decode(raw.encode()))
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail="Invalid approval token") from exc
    if (now if now is not None else time.time()) > body["expires_at"]:
        raise HTTPException(status_code=410, detail="This approval request expired. Start the demo again.")
    return body


def build_proposal(quotes: list[dict], now: float | None = None) -> dict:
    """Demo rule: ask to buy the watchlist stock with the biggest fall vs. yesterday's close. Not advice."""
    if not quotes:
        raise HTTPException(status_code=502, detail="No live quotes could be fetched right now.")
    live = [q for q in quotes if q["fresh"]]
    pick = min(live or quotes, key=lambda q: q["change_pct"])
    qty = max(1, int(PAPER_BUDGET // pick["price"]))
    issued = now if now is not None else time.time()
    body = {"symbol": pick["symbol"], "qty": qty, "quote_price": pick["price"], "currency": pick["currency"],
            "issued_at": int(issued), "expires_at": int(issued) + TOKEN_TTL_SECONDS,
            "fresh": pick["fresh"], "nonce": hashlib.sha256(f"{issued}{pick['symbol']}{os.urandom(8).hex()}".encode()).hexdigest()[:16]}
    return {
        "symbol": pick["symbol"], "name": pick["name"], "qty": qty, "quote_price": pick["price"],
        "currency": pick["currency"], "est_cost": round(qty * pick["price"], 2),
        "reason": f"Demo rule: largest fall vs. previous close ({pick['change_pct']}%) on the watchlist. Not investment advice.",
        "token": _sign(body), "expires_in_seconds": TOKEN_TTL_SECONDS,
        "stale": not pick["fresh"], "max_slippage_pct": MAX_SLIPPAGE_PCT,
    }


def simulate_fill(token: str, quote_now: dict | None = None) -> dict:
    body = _verify(token)
    now = time.time()
    for key in [k for k, exp in _USED_NONCES.items() if exp < now]:
        _USED_NONCES.pop(key, None)
    if body["nonce"] in _USED_NONCES:
        raise HTTPException(status_code=409, detail="This approval was already used. Start the demo again.")
    q = quote_now or fetch_quote(body["symbol"])
    if body.get("fresh", True) and not q["fresh"]:
        raise HTTPException(status_code=409, detail="The market stopped trading since you were asked. No paper order was placed.")
    move = abs(q["price"] - body["quote_price"]) / body["quote_price"] * 100
    if move > MAX_SLIPPAGE_PCT:
        raise HTTPException(status_code=409, detail=f"Price moved {move:.2f}% since the request (limit {MAX_SLIPPAGE_PCT}%). No paper order was placed; ask again.")
    _USED_NONCES[body["nonce"]] = body["expires_at"]
    return {
        "mode": "PAPER (simulated, no real order placed)",
        "side": "BUY", "symbol": body["symbol"], "qty": body["qty"],  # quantity is fixed by the approval
        "fill_price": q["price"], "currency": q["currency"],
        "total": round(body["qty"] * q["price"], 2),
        "quote_time": q["market_time"], "quote_age_seconds": q["age_seconds"], "fresh": q["fresh"],
        "price_when_requested": body["quote_price"],
    }


class ApproveBody(BaseModel):
    token: str


@router.get("/quotes")
def quotes() -> dict:
    data, errors = get_quotes(WATCHLIST)
    return {"source": SOURCE, "quotes": data, "errors": errors, "fetched_at": int(time.time())}


@router.post("/request")
def request_approval() -> dict:
    data, errors = get_quotes(WATCHLIST)
    return {"source": SOURCE, "quotes": data, "errors": errors, "fetched_at": int(time.time()),
            "proposal": build_proposal(data)}


@router.post("/approve")
def approve(body: ApproveBody) -> dict:
    try:
        return {"order": simulate_fill(body.token)}
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"Could not fetch a live price: {exc}"[:300]) from exc
