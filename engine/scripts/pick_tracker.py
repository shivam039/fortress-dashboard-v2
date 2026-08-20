"""
Fortress Pick Tracker
=====================
Evaluates open stock picks against current market prices to determine
Hit (target reached), Miss (stop loss hit), or Trailing (still active).

This module is called:
  1. By the scheduler at 4 PM IST daily (post-market evaluation)
  2. On-demand from the Streamlit UI
"""

import logging
import os
import sys
from datetime import datetime

import pandas as pd
import pytz

# Ensure engine root is on path
_engine_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _engine_dir not in sys.path:
    sys.path.insert(0, _engine_dir)

logger = logging.getLogger("fortress.pick_tracker")
logger.setLevel(logging.INFO)
if not logger.handlers:
    _h = logging.StreamHandler()
    _h.setFormatter(
        logging.Formatter("[%(asctime)s] %(name)s %(levelname)s: %(message)s")
    )
    logger.addHandler(_h)

IST = pytz.timezone("Asia/Kolkata")
MAX_TRADING_DAYS = 10  # Outcome window


def _fetch_current_prices(symbols: list) -> dict:
    """Bulk-fetch latest closing prices for a list of symbols using yfinance."""
    import yfinance as yf

    if not symbols:
        return {}

    prices = {}
    # Add .NS suffix for NSE tickers
    yf_symbols = [f"{s}.NS" for s in symbols]
    try:
        data = yf.download(yf_symbols, period="5d", progress=False, auto_adjust=False)
        if isinstance(data.columns, pd.MultiIndex):
            for sym, yf_sym in zip(symbols, yf_symbols):
                try:
                    close_series = data["Close"][yf_sym].dropna()
                    if not close_series.empty:
                        prices[sym] = float(close_series.iloc[-1])
                except (KeyError, IndexError):
                    pass
        else:
            # Single symbol case
            if "Close" in data.columns and not data["Close"].dropna().empty:
                prices[symbols[0]] = float(data["Close"].dropna().iloc[-1])
    except Exception as e:
        logger.warning(f"Bulk price fetch failed, trying individual: {e}")
        for sym in symbols:
            try:
                d = yf.download(
                    f"{sym}.NS", period="5d", progress=False, auto_adjust=False
                )
                if isinstance(d.columns, pd.MultiIndex):
                    d.columns = d.columns.get_level_values(0)
                if not d.empty and "Close" in d.columns:
                    prices[sym] = float(d["Close"].dropna().iloc[-1])
            except Exception:
                pass

    return prices


def _trading_days_between(start_date, end_date) -> int:
    """Approximate trading days between two dates (excludes weekends)."""
    if isinstance(start_date, str):
        start_date = pd.to_datetime(start_date)
    if isinstance(end_date, str):
        end_date = pd.to_datetime(end_date)
    # Make timezone-naive for comparison
    if hasattr(start_date, "tzinfo") and start_date.tzinfo:
        start_date = start_date.replace(tzinfo=None)
    if hasattr(end_date, "tzinfo") and end_date.tzinfo:
        end_date = end_date.replace(tzinfo=None)
    business_days = pd.bdate_range(start=start_date, end=end_date)
    return max(len(business_days) - 1, 0)  # Exclude the start day itself


def evaluate_open_picks():
    """
    Evaluate all TRAILING picks across all users.
    Called by the scheduler daily at 4 PM IST.
    """
    from utils.db import (
        get_all_trailing_picks,
        update_pick_outcome,
        update_pick_trailing,
    )

    trailing_df = get_all_trailing_picks()
    if trailing_df.empty:
        logger.info("No trailing picks to evaluate.")
        return {"evaluated": 0, "hits": 0, "misses": 0, "expired": 0}

    # Get unique symbols and fetch prices in bulk
    symbols = trailing_df["symbol"].unique().tolist()
    logger.info(
        f"Evaluating {len(trailing_df)} trailing picks across {len(symbols)} symbols..."
    )
    current_prices = _fetch_current_prices(symbols)

    now = datetime.now(IST)
    stats = {"evaluated": 0, "hits": 0, "misses": 0, "expired": 0}

    for _, pick in trailing_df.iterrows():
        symbol = pick["symbol"]
        pick_id = int(pick["id"])
        entry_price = float(pick["entry_price"])
        target_price = float(pick["target_price"])
        target_2 = (
            float(pick["target_2_price"])
            if pd.notna(pick.get("target_2_price"))
            else None
        )
        stop_loss = float(pick["stop_loss"])
        pick_date = pd.to_datetime(pick["pick_date"])
        prev_max = (
            float(pick["max_price"]) if pd.notna(pick.get("max_price")) else entry_price
        )
        prev_min = (
            float(pick["min_price"]) if pd.notna(pick.get("min_price")) else entry_price
        )

        current_price = current_prices.get(symbol)
        if current_price is None:
            logger.warning(f"  Could not fetch price for {symbol}, skipping.")
            continue

        stats["evaluated"] += 1
        trading_days = _trading_days_between(pick_date, now)
        new_max = max(prev_max, current_price)
        new_min = min(prev_min, current_price)
        pnl_pct = round(((current_price - entry_price) / entry_price) * 100, 2)

        # Check outcomes in priority order
        if target_2 and current_price >= target_2:
            # Hit Target 2 (higher target)
            update_pick_outcome(
                pick_id=pick_id,
                outcome="HIT_T2",
                outcome_price=current_price,
                outcome_date=now,
                pnl_pct=pnl_pct,
                days_to_resolve=trading_days,
                max_price=new_max,
                min_price=new_min,
            )
            logger.info(
                f"  🎯🎯 HIT_T2: {symbol} @ ₹{current_price:.2f} (T2=₹{target_2:.2f}, +{pnl_pct:.1f}%)"
            )
            stats["hits"] += 1

        elif current_price >= target_price:
            # Hit Target 1
            update_pick_outcome(
                pick_id=pick_id,
                outcome="HIT_T1",
                outcome_price=current_price,
                outcome_date=now,
                pnl_pct=pnl_pct,
                days_to_resolve=trading_days,
                max_price=new_max,
                min_price=new_min,
            )
            logger.info(
                f"  🎯 HIT_T1: {symbol} @ ₹{current_price:.2f} (T1=₹{target_price:.2f}, +{pnl_pct:.1f}%)"
            )
            stats["hits"] += 1

        elif current_price <= stop_loss:
            # Hit Stop Loss
            update_pick_outcome(
                pick_id=pick_id,
                outcome="MISS",
                outcome_price=current_price,
                outcome_date=now,
                pnl_pct=pnl_pct,
                days_to_resolve=trading_days,
                max_price=new_max,
                min_price=new_min,
            )
            logger.info(
                f"  🛑 MISS: {symbol} @ ₹{current_price:.2f} (SL=₹{stop_loss:.2f}, {pnl_pct:.1f}%)"
            )
            stats["misses"] += 1

        elif trading_days >= MAX_TRADING_DAYS:
            # Expired — window closed without hitting target or SL
            update_pick_outcome(
                pick_id=pick_id,
                outcome="EXPIRED",
                outcome_price=current_price,
                outcome_date=now,
                pnl_pct=pnl_pct,
                days_to_resolve=trading_days,
                max_price=new_max,
                min_price=new_min,
            )
            logger.info(
                f"  ⏰ EXPIRED: {symbol} @ ₹{current_price:.2f} after {trading_days}d ({pnl_pct:+.1f}%)"
            )
            stats["expired"] += 1

        else:
            # Still trailing — update max/min prices
            update_pick_trailing(
                pick_id=pick_id,
                max_price=new_max,
                min_price=new_min,
                pnl_pct=pnl_pct,
            )
            logger.debug(
                f"  📈 TRAILING: {symbol} @ ₹{current_price:.2f} (day {trading_days}/{MAX_TRADING_DAYS})"
            )

    logger.info(
        f"Pick evaluation complete: {stats['evaluated']} evaluated, "
        f"{stats['hits']} hits, {stats['misses']} misses, {stats['expired']} expired"
    )
    return stats


def record_pick(user_id: int, row_data: dict, pick_date=None, universe: str = None):
    """
    Record a stock pick for a user from scan results.
    Called when user clicks '📌 Track' or sends a Telegram tip.
    """
    from utils.db import upsert_pick_outcome

    if pick_date is None:
        pick_date = datetime.now(IST)

    symbol = row_data.get("Symbol", "")
    entry_price = float(row_data.get("Price", 0))
    target_price = float(row_data.get("Target_10D", 0))
    stop_loss = float(row_data.get("Stop_Loss", 0))
    score = float(row_data.get("Score", 0))
    strategy = row_data.get("Strategy", "")
    sector = row_data.get("Sector", "")

    # Compute Target 2
    tgt_mean = row_data.get("Tgt_Mean", None)
    if tgt_mean and not pd.isna(tgt_mean) and float(tgt_mean) > 0:
        target_2 = float(tgt_mean)
    elif target_price > 0:
        target_2 = round(target_price * 1.05, 2)
    else:
        target_2 = None

    if entry_price <= 0 or target_price <= 0 or stop_loss <= 0:
        logger.warning(
            f"Invalid pick data for {symbol}: entry={entry_price}, target={target_price}, sl={stop_loss}"
        )
        return False

    upsert_pick_outcome(
        user_id=user_id,
        symbol=symbol,
        pick_date=pick_date,
        entry_price=entry_price,
        target_price=target_price,
        target_2_price=target_2,
        stop_loss=stop_loss,
        score=score,
        strategy=strategy,
        sector=sector,
        universe=universe,
    )
    logger.info(f"📌 Recorded pick: {symbol} for user {user_id} @ ₹{entry_price:.2f}")
    return True
