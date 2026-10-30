import time

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from backend.api import stock_demo as sd


def q(symbol, price, chg, age=5):
    return {"symbol": symbol, "name": symbol, "price": price, "currency": "USD", "previous_close": price,
            "change_pct": chg, "market_time": int(time.time()) - age, "age_seconds": age, "fresh": True, "exchange": "X"}


def test_proposal_picks_biggest_dip_and_sizes_to_budget():
    p = sd.build_proposal([q("A", 100, 1.0), q("B", 250, -3.2), q("C", 10, 0.1)])
    assert p["symbol"] == "B" and p["qty"] == 40 and p["est_cost"] == 10000


def test_fill_requires_valid_unexpired_token():
    p = sd.build_proposal([q("B", 250, -3.2)])
    fill = sd.simulate_fill(p["token"], q("B", 251.5, -3))
    assert fill["fill_price"] == 251.5 and fill["total"] == 40 * 251.5 and "PAPER" in fill["mode"]
    with pytest.raises(HTTPException) as bad:
        sd.simulate_fill(p["token"][:-2] + "00", q("B", 1, 0))
    assert bad.value.status_code == 400
    old = sd.build_proposal([q("B", 250, -3)], now=time.time() - 3600)
    with pytest.raises(HTTPException) as gone:
        sd.simulate_fill(old["token"], q("B", 1, 0))
    assert gone.value.status_code == 410


def test_endpoints(monkeypatch):
    from backend.main import app
    monkeypatch.setattr(sd, "fetch_quote", lambda s, now=None: q(s, 100, -1.0 if s == "MSFT" else 1.0))
    c = TestClient(app)
    r = c.post("/api/v1/demo/stock/request").json()
    assert r["proposal"]["symbol"] == "MSFT"
    o = c.post("/api/v1/demo/stock/approve", json={"token": r["proposal"]["token"]}).json()["order"]
    assert o["symbol"] == "MSFT" and o["side"] == "BUY"


def test_replay_is_refused():
    p = sd.build_proposal([q("B", 250, -3.2)])
    sd.simulate_fill(p["token"], q("B", 250, -3))
    with pytest.raises(HTTPException) as again:
        sd.simulate_fill(p["token"], q("B", 250, -3))
    assert again.value.status_code == 409


def test_price_jump_refused_and_not_consumed():
    p = sd.build_proposal([q("B", 250, -3.2)])
    with pytest.raises(HTTPException) as moved:
        sd.simulate_fill(p["token"], q("B", 260, 1))  # +4% > limit
    assert moved.value.status_code == 409
    assert sd.simulate_fill(p["token"], q("B", 251, 1))["fill_price"] == 251  # token still usable


def test_prefers_fresh_quotes_and_refuses_fill_if_market_closed_after_approval():
    stale = dict(q("US", 100, -9.0), fresh=False)
    p = sd.build_proposal([stale, q("IN", 100, -1.0)])
    assert p["symbol"] == "IN" and not p["stale"]
    with pytest.raises(HTTPException) as closed:
        sd.simulate_fill(p["token"], dict(q("IN", 100, -1), fresh=False))
    assert closed.value.status_code == 409
    only_stale = sd.build_proposal([stale])
    assert only_stale["stale"] and sd.simulate_fill(only_stale["token"], dict(stale))["fresh"] is False
