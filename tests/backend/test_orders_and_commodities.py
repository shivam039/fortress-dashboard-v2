"""Tests for two gaps found reviewing the Orders and Commodities sections.

1. GET /api/orders/stats never counted "Cancelled" orders even though the
   frontend's status filter (frontend/src/app/orders/page.tsx) offers it
   as an option — a cancelled order silently vanished from every stat
   while still appearing in the separately-fetched orders list.

2. GET /api/commodities never persisted its scan results, unlike every
   other scan type (stock screener, MF) — the legacy Streamlit UI
   (commodities/ui.py) called register_scan + save_scan_results after
   every commodity scan; the Next.js-facing endpoint never picked that up,
   so commodity scans vanished the moment the response was returned, with
   no way to see historical trend via the existing Scan History page.

Router functions are called directly rather than through FastAPI's
TestClient + Depends() override — this repo's dual bare-import
("utils.db") vs engine-prefixed-import ("engine.utils.db") module identity
split (see tests/backend/test_reit_distributions.py's note on this) makes
matching the exact object reference app.dependency_overrides needs a
recurring footgun; calling the function directly with a plain dict sidesteps
it entirely, same as this session's reit_invits/us_investing router tests.
"""

import asyncio

import pandas as pd
import pytest
from fastapi import HTTPException

import main as main_mod
from routers import orders as orders_router_mod


def test_create_order_rejects_guest():
    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(orders_router_mod.create_order(
            order=orders_router_mod.OrderCreate(symbol="RELIANCE"),
            user={"sub": "guest_user"},
        ))
    assert exc_info.value.status_code == 403


def test_create_order_persists_via_db(monkeypatch):
    """The new Add-Order form on the Orders page relies on this endpoint
    actually calling through to create_fortress_order with the fields it
    submits."""
    import utils.db as db_mod

    calls = []
    monkeypatch.setattr(
        db_mod,
        "create_fortress_order",
        lambda **kwargs: calls.append(kwargs),
    )

    body = asyncio.run(orders_router_mod.create_order(
        order=orders_router_mod.OrderCreate(
            symbol="RELIANCE", order_type="Buy", quantity=10, price=2500, status="Pending",
        ),
        user={"sub": "test_user"},
    ))

    assert body["symbol"] == "RELIANCE"
    assert len(calls) == 1
    assert calls[0]["username"] == "test_user"
    assert calls[0]["symbol"] == "RELIANCE"
    assert calls[0]["quantity"] == 10


def test_order_stats_counts_cancelled(monkeypatch):
    df = pd.DataFrame(
        [
            {"status": "Executed"},
            {"status": "Pending"},
            {"status": "Rejected"},
            {"status": "Cancelled"},
            {"status": "Cancelled"},
        ]
    )
    # order_stats() imports fetch_fortress_orders locally inside the
    # function body (`from utils.db import fetch_fortress_orders`), so the
    # patch target is the actual utils.db module, not orders_router_mod.
    import utils.db as db_mod

    monkeypatch.setattr(db_mod, "fetch_fortress_orders", lambda **kwargs: df)

    body = asyncio.run(orders_router_mod.order_stats(user={"sub": "test_user"}))

    assert body["cancelled"] == 2
    assert body["total"] == 5
    assert body["executed"] == 1
    assert body["pending"] == 1
    assert body["rejected"] == 1


def test_get_commodities_persists_scan_history(monkeypatch):
    """GET /api/commodities must call register_scan + save_scan_results,
    same as /api/scan and /api/mf-analysis already do, so commodity scans
    show up in the existing Scan History page."""
    fake_df = pd.DataFrame(
        [
            {"Commodity": "Gold", "Price (₹)": 131.32, "Conviction Score": 87.5},
            {"Commodity": "Silver", "Price (₹)": 232.92, "Conviction Score": 92.0},
        ]
    )
    monkeypatch.setattr(main_mod, "build_commodities_frame", lambda force_refresh=False: fake_df)

    register_calls = []
    save_calls = []
    monkeypatch.setattr(
        main_mod,
        "register_scan",
        lambda timestamp, universe, scan_type, status: (
            register_calls.append((universe, scan_type, status)) or 999
        ),
    )
    monkeypatch.setattr(
        main_mod,
        "save_scan_results",
        lambda scan_id, df, scan_timestamp=None: save_calls.append((scan_id, len(df))),
    )

    result = main_mod.get_commodities()

    assert len(result) == 2
    assert register_calls == [("Commodities", "COMMODITY", "Completed")]
    assert save_calls == [(999, 2)]


def test_get_commodities_empty_frame_skips_persist(monkeypatch):
    """An empty scan (e.g. every commodity's live fetch failed) must not
    call register_scan/save_scan_results at all — matching
    save_scan_results' own no-op-on-empty behavior, and avoiding a bare
    scan row with zero detail rows cluttering Scan History."""
    monkeypatch.setattr(main_mod, "build_commodities_frame", lambda force_refresh=False: pd.DataFrame())

    register_calls = []
    monkeypatch.setattr(
        main_mod,
        "register_scan",
        lambda *args, **kwargs: register_calls.append(1) or 999,
    )

    result = main_mod.get_commodities()

    assert result == []
    assert register_calls == []
