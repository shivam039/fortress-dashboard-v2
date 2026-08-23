"""Tests for the Picks tracker endpoints, newly surfaced on the frontend
at /picks. Router functions are called directly (same pattern as
tests/backend/test_orders_and_commodities.py) to sidestep the bare vs
engine-prefixed import identity split when using TestClient's
dependency_overrides.
"""

import asyncio

from routers import picks as picks_router_mod


def test_pick_summary_guest_matches_full_shape(monkeypatch):
    """The guest and no-user-found shortcuts previously returned a
    truncated dict (missing total/expired/trailing/worst_pnl) while
    get_pick_outcome_summary's own empty-data default returned the full
    10-key shape — a real user with zero picks and a guest saw
    differently-shaped responses from the same endpoint, which would
    break a frontend that reads e.g. summary.total unconditionally."""
    body = asyncio.run(picks_router_mod.pick_summary(user={"sub": "guest_user"}))

    assert body == {
        "total": 0,
        "hits": 0,
        "misses": 0,
        "expired": 0,
        "trailing": 0,
        "hit_rate": 0,
        "avg_pnl": 0,
        "avg_days": 0,
        "best_pnl": 0,
        "worst_pnl": 0,
    }


def test_pick_summary_unknown_user_matches_full_shape(monkeypatch):
    import utils.db as db_mod

    monkeypatch.setattr(db_mod, "get_user_id_by_username", lambda username: None)

    body = asyncio.run(picks_router_mod.pick_summary(user={"sub": "someone"}))

    assert body["total"] == 0
    assert set(body.keys()) == {
        "total", "hits", "misses", "expired", "trailing",
        "hit_rate", "avg_pnl", "avg_days", "best_pnl", "worst_pnl",
    }


def test_list_picks_guest_returns_empty():
    result = asyncio.run(picks_router_mod.list_picks(user={"sub": "guest_user"}))
    assert result == []


def test_record_pick_rejects_guest():
    from fastapi import HTTPException
    import pytest

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(picks_router_mod.record_pick(
            pick=picks_router_mod.PickRecord(symbol="RELIANCE", entry_price=100, target_price=110, stop_loss=95),
            user={"sub": "guest_user"},
        ))
    assert exc_info.value.status_code == 403
