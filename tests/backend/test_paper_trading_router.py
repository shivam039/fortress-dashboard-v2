"""FORTRESS-V4 / Blocker C: paper trading is now reachable through an
authenticated API. Exercises the real router against the real T2 engine
(engine/paper_trading/logic.py) and real DB persistence — no mocking of
T2's own logic, only auth (main.app's dependency override, the same
pattern FastAPI recommends and this repo doesn't otherwise need a fixture
for). No live network access: /close's price lookup is exercised with a
monkeypatched market_data_provider.get_ohlcv.
"""

import pandas as pd
from datetime import datetime, timezone
from decimal import Decimal
from auth_utils import get_current_user
from fastapi.testclient import TestClient
from main import app
from utils.db import fetch_signal_ledger, record_signal_ledger_entries

app.dependency_overrides[get_current_user] = lambda: {"sub": "test_user"}
client = TestClient(app)


def _make_signal(symbol="ZZPAPER1.NS", **overrides):
    entry = {
        "generated_at": "2025-03-03 16:00:00",
        "symbol": symbol,
        "score": 82.0,
        "suggested_entry": 100.0,
        "stop_loss": 95.0,
        "target": 120.0,
        "feature_snapshot": {"Symbol": symbol},
    }
    entry.update(overrides)
    record_signal_ledger_entries([entry])
    return fetch_signal_ledger(symbol=symbol, limit=1)[0]


# ── 12. opens from a valid T1 signal ────────────────────────────────────────


def test_open_paper_trade_from_valid_signal():
    signal = _make_signal("ZZPAPER1.NS")
    response = client.post("/api/paper-trades", json={"signal_id": signal["id"]})
    assert response.status_code == 201
    body = response.json()
    assert body["label"] == "PAPER TRADE"
    assert body["symbol"] == "ZZPAPER1.NS"
    assert body["entry_price"] == 100.0
    assert body["signal_id"] == signal["id"]


# ── 13. invalid/nonexistent signal is rejected ──────────────────────────────


def test_open_paper_trade_rejects_nonexistent_signal_id():
    response = client.post("/api/paper-trades", json={"signal_id": 999_999_999})
    assert response.status_code == 404


def test_open_paper_trade_rejects_missing_signal_id():
    response = client.post("/api/paper-trades", json={})
    assert response.status_code == 422


def test_open_paper_trade_ignores_fabricated_signal_fields_in_the_body():
    """The router must look up the real signal by id, never trust
    caller-supplied entry/stop/target values in the request body."""
    signal = _make_signal("ZZPAPER2.NS")
    response = client.post(
        "/api/paper-trades",
        json={
            "signal_id": signal["id"],
            "suggested_entry": 1.0,
            "stop_loss": 0.5,
            "target": 999999,
        },
    )
    assert response.status_code == 201
    body = response.json()
    assert (
        body["entry_price"] == 100.0
    )  # from the real signal, not the fabricated body field


# ── 14. paper trades list correctly ─────────────────────────────────────────


def test_list_paper_trades_filters_by_status():
    signal = _make_signal("ZZPAPER3.NS")
    client.post("/api/paper-trades", json={"signal_id": signal["id"]})

    open_trades = client.get("/api/paper-trades", params={"status": "open"}).json()
    assert any(t["symbol"] == "ZZPAPER3.NS" for t in open_trades)
    closed_trades = client.get("/api/paper-trades", params={"status": "closed"}).json()
    assert all(t["status"] == "closed" for t in closed_trades)


def test_empty_paper_trades_table_returns_empty_json(monkeypatch):
    monkeypatch.setattr("utils.db.fetch_paper_trades", lambda **_kwargs: [])

    response = client.get("/api/paper-trades")

    assert response.status_code == 200
    assert response.json() == []


def test_neon_decimal_datetime_and_nullable_fields_are_valid_json(monkeypatch):
    created_at = datetime(2026, 9, 11, 12, 30, tzinfo=timezone.utc)
    monkeypatch.setattr(
        "utils.db.fetch_paper_trades",
        lambda **_kwargs: [
            {
                "trade_id": 1,
                "entry_price": Decimal("100.25"),
                "exit_price": None,
                "gross_pnl": Decimal("NaN"),
                "created_at": created_at,
            }
        ],
    )

    response = client.get("/api/paper-trades")

    assert response.status_code == 200
    assert response.json() == [
        {
            "trade_id": 1,
            "entry_price": 100.25,
            "exit_price": None,
            "gross_pnl": None,
            "created_at": created_at.isoformat(),
        }
    ]


def test_database_failure_returns_sanitized_service_unavailable(monkeypatch):
    from utils.db import PaperTradePersistenceError

    def fail_fetch(**_kwargs):
        raise PaperTradePersistenceError("internal database detail")

    monkeypatch.setattr("utils.db.fetch_paper_trades", fail_fetch)

    response = client.get("/api/paper-trades")

    assert response.status_code == 503
    assert response.json() == {"detail": "Paper trade data is temporarily unavailable"}


def test_paper_trade_metrics_still_works(monkeypatch):
    monkeypatch.setattr("utils.db.fetch_paper_trades", lambda **_kwargs: [])

    response = client.get("/api/paper-trades/metrics")

    assert response.status_code == 200
    assert response.json()["trade_count"] == 0


def test_open_position_valuation_is_read_only_and_enriched(monkeypatch):
    trade = {
        "trade_id": 41, "signal_id": 42, "symbol": "ZZVALUE.NS",
        "entry_timestamp": "2026-09-08 10:00:00", "entry_price": 100.0,
        "quantity": 2.0, "notional": 200.0, "stop_price": 90.0,
        "target_price": 120.0, "status": "open",
    }
    signal = {"id": 42, "symbol": "ZZVALUE.NS", "score": 91.0,
              "market_regime": "Bull", "sector": "Energy"}
    monkeypatch.setattr("utils.db.fetch_paper_trades", lambda **_: [trade])
    monkeypatch.setattr("utils.db.fetch_signal_ledger", lambda **_: [signal])
    monkeypatch.setattr("utils.db.fetch_policy_decisions", lambda **_: [])
    monkeypatch.setattr("utils.market_data_provider.get_batch_ltp", lambda _: {"ZZVALUE.NS": 110.0})

    response = client.get("/api/paper-trades/open/valuation")
    body = response.json()[0]
    assert response.status_code == 200
    assert body["current_price"] == 110.0
    assert body["unrealized_pnl"] == 20.0
    assert body["unrealized_return_pct"] == 10.0
    assert body["signal"]["score"] == 91.0


def test_invalid_auth_returns_401_not_500():
    app.dependency_overrides.pop(get_current_user, None)
    try:
        response = client.get("/api/paper-trades")
    finally:
        app.dependency_overrides[get_current_user] = lambda: {"sub": "test_user"}

    assert response.status_code == 401


# ── 15. close/outcome path uses the existing T2 logic ───────────────────────


def test_close_paper_trade_uses_t2_simulate_exit(monkeypatch):
    signal = _make_signal("ZZPAPER4.NS")
    opened = client.post("/api/paper-trades", json={"signal_id": signal["id"]}).json()

    # Price path after entry: hits the target (120) on day 2.
    dates = pd.date_range("2025-03-04", periods=5, freq="B")
    hist = pd.DataFrame(
        {
            "High": [105, 121, 122, 123, 124],
            "Low": [99, 119, 120, 121, 122],
            "Close": [104, 120, 121, 122, 123],
        },
        index=dates,
    )
    monkeypatch.setattr(
        "utils.market_data_provider.get_ohlcv", lambda symbol, period: hist
    )

    response = client.post(f"/api/paper-trades/{opened['trade_id']}/close")
    assert response.status_code == 200
    body = response.json()
    assert body["label"] == "PAPER TRADE"
    assert body["status"] == "closed"
    assert body["exit_reason"] == "target"
    assert body["exit_price"] == 120.0


def test_close_paper_trade_with_no_price_data_yet_is_not_ready(monkeypatch):
    signal = _make_signal("ZZPAPER5.NS")
    opened = client.post("/api/paper-trades", json={"signal_id": signal["id"]}).json()
    monkeypatch.setattr(
        "utils.market_data_provider.get_ohlcv", lambda symbol, period: pd.DataFrame()
    )

    response = client.post(f"/api/paper-trades/{opened['trade_id']}/close")
    assert response.status_code == 200
    assert response.json()["status"] == "not_ready"


def test_close_nonexistent_trade_returns_404():
    response = client.post("/api/paper-trades/999999999/close")
    assert response.status_code == 404


# ── 16. paper route cannot execute a real broker order ──────────────────────


def test_paper_trading_module_never_references_broker_execution():
    """Static check: the paper-trading router's source never imports or
    calls a real order-execution path (engine/utils/broker_mappings.py's
    generate_zerodha_url/generate_dhan_url, or routers/brokers.py) — PAPER
    TRADE only. Prose mentions of the word "broker" in comments/docstrings
    (explaining that none of this exists) are expected and fine."""
    import inspect

    import routers.paper_trading as paper_trading_module

    router_source = inspect.getsource(paper_trading_module)
    for term in (
        "generate_zerodha_url",
        "generate_dhan_url",
        "routers.brokers",
        "place_order",
        "kite",
    ):
        assert (
            term not in router_source
        ), f"paper trading router must never reference {term!r}"
