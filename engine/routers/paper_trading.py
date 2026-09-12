# engine/routers/paper_trading.py — FORTRESS-V4 / Blocker C: the smallest
# usable product surface for FORTRESS-T2's paper-trading engine.
"""
- GET  /api/paper-trades          → list paper trades (open/closed)
- POST /api/paper-trades          → open a position FROM AN EXISTING T1 signal
- POST /api/paper-trades/{id}/close → close using the deterministic T2 engine
- GET  /api/paper-trades/metrics  → portfolio metrics over closed trades

PAPER TRADING ONLY. No broker execution exists in this module or anywhere
it calls into — engine/paper_trading/logic.py is pure simulation. All
trading math (entry sizing, stop/target, exposure limits, exit rules,
metrics) is T2's existing, tested logic; this router only wires it to
signal_ledger/paper_trades persistence and HTTP.
"""

from datetime import datetime, timezone
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from auth_utils import get_current_user
from paper_trading.logic import (
    PaperTradingConfig,
    compute_metrics,
    open_position_from_signal,
    simulate_exit,
)

router = APIRouter(prefix="/api/paper-trades", tags=["paper-trading"])


@router.get("")
async def list_paper_trades(
    status: Optional[str] = Query(None, description="'open' or 'closed'"),
    user: dict = Depends(get_current_user),
):
    """PAPER TRADE records only — never a real broker order."""
    from utils.db import (
        PaperTradePersistenceError,
        fetch_paper_trades,
        normalize_paper_trade_for_json,
    )

    try:
        trades = fetch_paper_trades(status=status)
    except PaperTradePersistenceError as exc:
        raise HTTPException(
            status_code=503,
            detail="Paper trade data is temporarily unavailable",
        ) from exc
    return [normalize_paper_trade_for_json(trade) for trade in trades]


@router.get("/metrics")
async def paper_trade_metrics(user: dict = Depends(get_current_user)):
    """Portfolio metrics computed by T2's own compute_metrics() over closed
    PAPER trades — not a claim about real trading performance."""
    from utils.db import PaperTradePersistenceError, fetch_paper_trades

    try:
        closed_trades = fetch_paper_trades(status="closed")
    except PaperTradePersistenceError as exc:
        raise HTTPException(
            status_code=503,
            detail="Paper trade data is temporarily unavailable",
        ) from exc
    return compute_metrics(closed_trades)
@router.get("/open/valuation")
async def open_position_valuation(user: dict = Depends(get_current_user)):
    """Return open trades enriched with non-persistent latest valuation data."""
    from utils.db import (
        fetch_paper_trades,
        fetch_policy_decisions,
        fetch_signal_ledger,
        normalize_paper_trade_for_json,
    )
    from utils.market_data_provider import get_batch_ltp

    trades = fetch_paper_trades(status="open")
    prices = get_batch_ltp([t["symbol"] for t in trades if t.get("symbol")]) if trades else {}
    policies = {p.get("trade_id"): p for p in fetch_policy_decisions(limit=500)}
    result = []
    for trade in trades:
        item = normalize_paper_trade_for_json(trade)
        current = prices.get(trade.get("symbol"))
        entry = float(trade.get("entry_price") or 0)
        quantity = float(trade.get("quantity") or 0)
        item["current_price"] = current
        item["unrealized_pnl"] = round((current - entry) * quantity, 2) if current is not None and entry else None
        item["unrealized_return_pct"] = round(((current / entry) - 1) * 100, 2) if current is not None and entry else None
        stop = trade.get("stop_price")
        target = trade.get("target_price")
        item["distance_to_stop_pct"] = round(((current - float(stop)) / current) * 100, 2) if current and stop else None
        item["distance_to_target_pct"] = round(((float(target) - current) / current) * 100, 2) if current and target else None
        try:
            started = datetime.fromisoformat(str(trade.get("entry_timestamp")).replace("Z", "+00:00"))
            if started.tzinfo is None:
                started = started.replace(tzinfo=timezone.utc)
            item["holding_period_days"] = max(0, (datetime.now(timezone.utc) - started).days)
        except (TypeError, ValueError):
            item["holding_period_days"] = None
        signal_rows = fetch_signal_ledger(signal_id=trade.get("signal_id"), limit=1)
        item["signal"] = normalize_paper_trade_for_json(signal_rows[0]) if signal_rows else None
        item["policy_version"] = policies.get(trade.get("trade_id"), {}).get("policy_version")
        result.append(item)
    return result

@router.get("/signals")
async def eligible_signals(
    limit: int = Query(20, le=100), user: dict = Depends(get_current_user)
):
    """Recent FORTRESS-T1 signal_ledger rows — lets the UI both (a) pick a
    real signal to open a paper trade from, and (b) show the originating
    signal's own detail (score, regime, sector, entry/stop/target) next to
    a paper trade that references its id."""
    from utils.db import fetch_signal_ledger

    return fetch_signal_ledger(limit=limit)


@router.post("", status_code=201)
async def open_paper_trade(
    body: Dict[str, Any], user: dict = Depends(get_current_user)
):
    """Open a PAPER position from an existing FORTRESS-T1 signal_ledger
    row. `signal_id` must reference a real, persisted signal — this never
    accepts arbitrary/fabricated signal fields from the request body."""
    from utils.db import create_paper_trade, fetch_paper_trades, fetch_signal_ledger

    signal_id = body.get("signal_id")
    if not isinstance(signal_id, int):
        raise HTTPException(status_code=422, detail="signal_id (integer) is required")

    matches = fetch_signal_ledger(signal_id=signal_id, limit=1)
    if not matches:
        raise HTTPException(
            status_code=404, detail=f"No signal found with id={signal_id}"
        )
    signal = matches[0]
    from oracle_decision.service import build_decision
    oracle = build_decision(signal)

    config = PaperTradingConfig()
    open_positions = fetch_paper_trades(status="open")
    result = open_position_from_signal(signal, config, open_positions)
    if not result.accepted:
        raise HTTPException(status_code=400, detail=result.reason)

    trade = {
        **result.trade,
        "source_type": "ORACLE_SIGNAL",
        "oracle_version": "oracle-v1",
        "oracle_decision": oracle.get("decision", "UNAVAILABLE"),
        "source_scan_id": signal.get("scan_id"),
    }
    trade_id = create_paper_trade(trade)
    if trade_id is None:
        raise HTTPException(status_code=500, detail="Failed to persist paper trade")

    return {**trade, "trade_id": trade_id, "label": "PAPER TRADE"}


@router.post("/{trade_id}/close")
async def close_paper_trade_route(
    trade_id: int, user: dict = Depends(get_current_user)
):
    """Close using T2's deterministic simulate_exit() against real price
    data since entry — never a broker fill, never an invented outcome
    when price data isn't available yet."""
    from utils.db import close_paper_trade, fetch_paper_trades
    from utils.market_data_provider import get_ohlcv

    open_trades = fetch_paper_trades(status="open")
    trade = next((t for t in open_trades if t.get("trade_id") == trade_id), None)
    if trade is None:
        raise HTTPException(
            status_code=404, detail=f"No open paper trade with id={trade_id}"
        )

    hist = get_ohlcv(trade["symbol"], "1y")
    price_path = []
    if hist is not None and not hist.empty:
        entry_date = str(trade["entry_timestamp"])[:10]
        for ts, row in hist.iterrows():
            date_str = ts.strftime("%Y-%m-%d") if hasattr(ts, "strftime") else str(ts)
            if date_str > entry_date:
                price_path.append(
                    {
                        "date": date_str,
                        "high": float(row["High"]),
                        "low": float(row["Low"]),
                        "close": float(row["Close"]),
                    }
                )

    config = PaperTradingConfig()
    closed = simulate_exit(trade, price_path, config)
    if closed is None:
        return {
            "status": "not_ready",
            "reason": "No price data available yet since entry",
            "trade_id": trade_id,
        }

    if not close_paper_trade(trade_id, closed):
        raise HTTPException(
            status_code=500, detail="Failed to persist paper trade close"
        )

    return {**closed, "trade_id": trade_id, "label": "PAPER TRADE"}
