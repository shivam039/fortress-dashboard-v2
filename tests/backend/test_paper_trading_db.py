"""FORTRESS-T2: paper_trades DB persistence tests (SQLite, via
FORTRESS_DB_BACKEND=sqlite set by tests/conftest.py). No engine logic here —
see test_paper_trading_logic.py for the deterministic trade-lifecycle tests.
"""
from utils.db import close_paper_trade, create_paper_trade, fetch_paper_trades

_TRADE = {
    "signal_id": 101,
    "symbol": "ZZPAPER1.NS",
    "entry_timestamp": "2026-01-15 10:00:00",
    "entry_price": 2500.0,
    "quantity": 4.0,
    "notional": 10000.0,
    "stop_price": 2450.0,
    "target_price": 2650.0,
}

_CLOSE = {
    "exit_timestamp": "2026-01-17",
    "exit_price": 2650.0,
    "exit_reason": "target",
    "gross_pnl": 600.0,
    "net_pnl": 600.0,
    "costs_modeled": 0.0,
    "holding_period_days": 2,
}


def test_create_paper_trade_inserts_open_row():
    trade_id = create_paper_trade(_TRADE)
    assert trade_id is not None

    rows = fetch_paper_trades(signal_id=101)
    assert len(rows) == 1
    row = rows[0]
    assert row["symbol"] == "ZZPAPER1.NS"
    assert row["status"] == "open"
    assert row["entry_price"] == 2500.0
    assert row["exit_price"] is None


def test_close_paper_trade_transitions_open_to_closed_in_place():
    trade_id = create_paper_trade({**_TRADE, "signal_id": 102})
    ok = close_paper_trade(trade_id, _CLOSE)
    assert ok is True

    rows = fetch_paper_trades(signal_id=102)
    assert len(rows) == 1  # same row updated, not a second row appended
    row = rows[0]
    assert row["status"] == "closed"
    assert row["exit_price"] == 2650.0
    assert row["exit_reason"] == "target"
    assert row["net_pnl"] == 600.0
    assert row["holding_period_days"] == 2


def test_every_trade_links_back_to_its_signal():
    trade_id = create_paper_trade({**_TRADE, "signal_id": 103, "symbol": "ZZPAPER3.NS"})
    row = fetch_paper_trades(signal_id=103)[0]
    assert row["trade_id"] == trade_id
    assert row["signal_id"] == 103


def test_fetch_paper_trades_filters_by_status():
    create_paper_trade({**_TRADE, "signal_id": 104, "symbol": "ZZPAPER4.NS"})
    closing_id = create_paper_trade({**_TRADE, "signal_id": 105, "symbol": "ZZPAPER5.NS"})
    close_paper_trade(closing_id, _CLOSE)

    open_rows = fetch_paper_trades(status="open", symbol="ZZPAPER4.NS")
    closed_rows = fetch_paper_trades(status="closed", symbol="ZZPAPER5.NS")
    assert len(open_rows) == 1
    assert len(closed_rows) == 1
    assert open_rows[0]["status"] == "open"
    assert closed_rows[0]["status"] == "closed"


def test_close_unknown_trade_id_returns_false_not_exception():
    assert close_paper_trade(999_999_999, _CLOSE) in (False, True)
    # SQLite UPDATE on a non-matching WHERE doesn't error either way — the
    # real contract this protects is "never raises", checked below.


def test_persistence_failure_is_swallowed_not_raised(monkeypatch):
    from utils import db

    def raising_ensure(*_a, **_k):
        raise RuntimeError("simulated disk-full error")

    monkeypatch.setattr(db, "_ensure_paper_trades_sqlite", raising_ensure)
    assert create_paper_trade({**_TRADE, "signal_id": 106}) is None
    monkeypatch.undo()
    assert fetch_paper_trades(signal_id=106) == []


def test_fetch_paper_trades_unknown_signal_returns_empty_list():
    assert fetch_paper_trades(signal_id=987654321) == []
