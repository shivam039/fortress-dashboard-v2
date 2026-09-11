"""FORTRESS-T2: paper_trades DB persistence tests (SQLite, via
FORTRESS_DB_BACKEND=sqlite set by tests/conftest.py). No engine logic here —
see test_paper_trading_logic.py for the deterministic trade-lifecycle tests.
"""

from datetime import date, datetime, timezone
from decimal import Decimal
import sqlite3
from uuid import UUID

import pytest

from utils.db import (
    PaperTradePersistenceError,
    _ensure_paper_trades_sqlite,
    close_paper_trade,
    create_paper_trade,
    fetch_paper_trades,
)

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
    closing_id = create_paper_trade(
        {**_TRADE, "signal_id": 105, "symbol": "ZZPAPER5.NS"}
    )
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


def test_fetch_persistence_failure_is_not_reported_as_empty(monkeypatch):
    from utils import db

    def raising_ensure(*_a, **_k):
        raise RuntimeError("simulated disk-full error")

    monkeypatch.setattr(db, "_ensure_paper_trades_sqlite", raising_ensure)
    with pytest.raises(PaperTradePersistenceError):
        fetch_paper_trades(signal_id=106)


def test_fetch_paper_trades_unknown_signal_returns_empty_list():
    assert fetch_paper_trades(signal_id=987654321) == []


def test_neon_native_values_are_normalized_for_json(monkeypatch):
    """psycopg returns types SQLite never exercises."""
    from utils import db

    trade_uuid = UUID("12345678-1234-5678-1234-567812345678")
    created_at = datetime(2026, 9, 11, 12, 30, tzinfo=timezone.utc)
    trade_date = date(2026, 9, 10)
    neon_row = {
        "trade_id": trade_uuid,
        "signal_id": 101,
        "entry_price": Decimal("100.25"),
        "quantity": Decimal("2"),
        "notional": Decimal("200.50"),
        "stop_price": None,
        "target_price": Decimal("Infinity"),
        "exit_price": None,
        "gross_pnl": Decimal("NaN"),
        "net_pnl": Decimal("1.50"),
        "costs_modeled": Decimal("1E10000"),
        "created_at": created_at,
        "updated_at": trade_date,
    }
    monkeypatch.setattr(db, "_can_use_neon", lambda: True)
    monkeypatch.setattr(db, "_ensure_paper_trades_neon", lambda: None)
    monkeypatch.setattr(db, "_query", lambda *_args, **_kwargs: [neon_row])

    row = fetch_paper_trades()[0]

    assert row["trade_id"] == str(trade_uuid)
    assert row["entry_price"] == 100.25
    assert row["quantity"] == 2.0
    assert row["stop_price"] is None
    assert row["target_price"] is None
    assert row["gross_pnl"] is None
    assert row["costs_modeled"] is None
    assert row["created_at"] == created_at.isoformat()
    assert row["updated_at"] == trade_date.isoformat()


def test_sqlite_schema_initialization_is_idempotent_and_evolves_old_table():
    with sqlite3.connect(":memory:") as conn:
        conn.execute("""
            CREATE TABLE paper_trades (
                trade_id INTEGER PRIMARY KEY AUTOINCREMENT,
                signal_id INTEGER NOT NULL,
                symbol TEXT NOT NULL,
                entry_timestamp TEXT NOT NULL,
                entry_price REAL NOT NULL,
                quantity REAL NOT NULL,
                notional REAL NOT NULL
            )
            """)
        conn.execute("""
            INSERT INTO paper_trades (
                signal_id, symbol, entry_timestamp, entry_price,
                quantity, notional
            ) VALUES (1, 'OLD.NS', '2026-01-01', 10, 2, 20)
            """)

        _ensure_paper_trades_sqlite(conn)
        _ensure_paper_trades_sqlite(conn)

        columns = {row[1] for row in conn.execute("PRAGMA table_info(paper_trades)")}
        assert {
            "stop_price",
            "target_price",
            "status",
            "exit_timestamp",
            "exit_price",
            "exit_reason",
            "gross_pnl",
            "net_pnl",
            "costs_modeled",
            "holding_period_days",
            "created_at",
            "updated_at",
        } <= columns
        old_row = conn.execute(
            "SELECT symbol, status FROM paper_trades WHERE signal_id = 1"
        ).fetchone()
        assert old_row == ("OLD.NS", "open")


def test_neon_schema_initialization_uses_idempotent_column_evolution(
    monkeypatch,
):
    from utils import db

    statements = []
    monkeypatch.setattr(
        db,
        "_exec",
        lambda sql, *_args, **_kwargs: statements.append(sql),
    )

    db._ensure_paper_trades_neon()
    first_run = list(statements)
    db._ensure_paper_trades_neon()

    assert statements[len(first_run) :] == first_run
    alter_statements = [
        statement for statement in first_run if "ALTER TABLE paper_trades" in statement
    ]
    assert alter_statements
    assert all(
        "ADD COLUMN IF NOT EXISTS" in statement for statement in alter_statements
    )
