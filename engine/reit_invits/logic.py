"""
reit_invits/logic.py
====================
Data fetching, scoring, and risk-flag generation for Indian REITs & InvITs.

Conviction score (0-100) breakdown:
  - yield_score          (25%) — distribution yield vs peer median
  - return_score         (25%) — 1m / 1y price return vs Nifty 50
  - downside_protection  (20%) — max drawdown vs peers
  - volatility_score     (15%) — 30d annualised volatility vs peers
  - momentum_score       (15%) — 3m price momentum
"""

import logging
import math
import time
from datetime import datetime, timezone
from typing import Any, Optional

import pandas as pd
import yfinance as yf

from reit_invits.universe import REIT_INVIT_UNIVERSE

logger = logging.getLogger("fortress.reit_invits")

# ── Weight config ─────────────────────────────────────────────────────────────
WEIGHTS = {
    "yield_score": 0.25,
    "return_score": 0.25,
    "downside_protection": 0.20,
    "volatility_score": 0.15,
    "momentum_score": 0.15,
}

# ── Helpers ───────────────────────────────────────────────────────────────────

def _safe(val: Any) -> Optional[float]:
    """Return None for NaN/inf, otherwise return float."""
    if val is None:
        return None
    try:
        f = float(val)
        if math.isnan(f) or math.isinf(f):
            return None
        return f
    except (TypeError, ValueError):
        return None


def _pct_rank(value: Optional[float], peer_values: list[float]) -> float:
    """Return percentile rank of value within peers (0-100). 100 = best."""
    if value is None or not peer_values:
        return 50.0
    peers = [v for v in peer_values if v is not None]
    if not peers:
        return 50.0
    rank = sum(1 for p in peers if p <= value) / len(peers)
    return round(rank * 100, 1)


def _fetch_history(symbol: str, period: str = "1y") -> pd.DataFrame:
    """Download OHLCV via yfinance with minimal retries."""
    for attempt in range(2):
        try:
            df = yf.download(
                symbol,
                period=period,
                interval="1d",
                progress=False,
                auto_adjust=True,
            )
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = df.columns.get_level_values(0)
            if not df.empty:
                return df
        except Exception as exc:
            logger.debug("fetch_history %s attempt %d: %s", symbol, attempt, exc)
            time.sleep(0.5)
    return pd.DataFrame()


# ── Per-symbol raw metrics ────────────────────────────────────────────────────

def _compute_raw_metrics(symbol: str, meta: dict[str, Any]) -> dict[str, Any]:
    hist = _fetch_history(symbol, "1y")
    universe_meta = REIT_INVIT_UNIVERSE.get(symbol, {}) or {}

    result: dict[str, Any] = {
        "symbol": symbol,
        "name": meta.get("name", symbol),
        "asset_class": meta.get("type", "REIT"),
        "sub_type": meta.get("sub_type", ""),
        "sector": meta.get("sector", "Real Estate"),
        "sponsor": meta.get("sponsor", ""),
        "currency": "INR",
        "price": None,
        "returns_1m": None,
        "returns_3m": None,
        "returns_6m": None,
        "returns_1y": None,
        "volatility_30d": None,
        "max_drawdown_1y": None,
        "yield_pct": None,
        "data_quality": "stale",
        "last_updated": datetime.now(timezone.utc).isoformat(),
        "risk_flags": [],
    }

    if hist.empty or "Close" not in hist.columns:
        result["risk_flags"].append("no_price_data")
        return result

    close = hist["Close"].dropna()
    if len(close) < 5:
        result["risk_flags"].append("insufficient_history")
        return result

    result["price"] = _safe(close.iloc[-1])
    result["data_quality"] = "complete"

    # ── Returns ───────────────────────────────────────────────────────────────
    def _ret(days: int) -> Optional[float]:
        if len(close) <= days:
            return None
        past = close.iloc[-(days + 1)]
        curr = close.iloc[-1]
        if _safe(past) and past != 0:
            return _safe((curr - past) / past * 100)
        return None

    result["returns_1m"] = _ret(21)
    result["returns_3m"] = _ret(63)
    result["returns_6m"] = _ret(126)
    result["returns_1y"] = _ret(252)

    # ── Volatility (30d annualised) ────────────────────────────────────────
    if len(close) >= 30:
        rets = close.pct_change().dropna()
        vol = _safe(rets.tail(30).std() * (252 ** 0.5) * 100)
        result["volatility_30d"] = vol
        if vol is not None and vol > 40:
            result["risk_flags"].append("high_volatility")

    # ── Max drawdown (1y) ──────────────────────────────────────────────────
    rolling_max = close.cummax()
    dd_series = (close - rolling_max) / rolling_max * 100
    mdd = _safe(dd_series.min())
    result["max_drawdown_1y"] = mdd
    if mdd is not None and mdd < -30:
        result["risk_flags"].append("high_drawdown")

    # ── Yield from yfinance info ───────────────────────────────────────────
    try:
        info = yf.Ticker(symbol).info
        div_yield = _safe(info.get("dividendYield") or info.get("yield"))
        if div_yield:
            result["yield_pct"] = round(div_yield * 100, 2) if div_yield < 1 else div_yield
        # NAV / book value proxy
        nav = _safe(info.get("bookValue"))
        if nav and result["price"]:
            result["nav_per_unit"] = nav
            result["nav_premium_pct"] = round((result["price"] - nav) / nav * 100, 2)
    except Exception:
        pass

    # ── Staleness check ───────────────────────────────────────────────────
    last_date = hist.index[-1]
    if hasattr(last_date, "date"):
        from datetime import date
        age_days = (date.today() - last_date.date()).days
        if age_days > 3:
            result["data_quality"] = "stale"
            result["risk_flags"].append("stale_data")

    return result


# ── Universe scoring ──────────────────────────────────────────────────────────

def _score_universe(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Assign conviction + confidence scores after all raw metrics are computed."""
    valid = [r for r in records if r.get("price")]

    # Build peer arrays for normalisation
    yields = [r.get("yield_pct") for r in valid if r.get("yield_pct") is not None]
    returns_1y = [r.get("returns_1y") for r in valid if r.get("returns_1y") is not None]
    returns_1m = [r.get("returns_1m") for r in valid if r.get("returns_1m") is not None]
    vols = [r.get("volatility_30d") for r in valid if r.get("volatility_30d") is not None]
    drawdowns = [r.get("max_drawdown_1y") for r in valid if r.get("max_drawdown_1y") is not None]
    returns_3m = [r.get("returns_3m") for r in valid if r.get("returns_3m") is not None]

    for r in records:
        if not r.get("price"):
            r.update({
                "conviction_score": None,
                "confidence_score": 0,
                "score_breakdown": {},
                "score_version": "v2",
            })
            continue

        # ── Sub-scores (each 0-100) ────────────────────────────────────────
        breakdown: dict[str, float] = {}

        # yield_score — higher yield rank = better
        breakdown["yield_score"] = _pct_rank(r.get("yield_pct"), yields)

        # return_score — blend 1m (30%) + 1y (70%)
        ret_1m_rank = _pct_rank(r.get("returns_1m"), returns_1m)
        ret_1y_rank = _pct_rank(r.get("returns_1y"), returns_1y)
        breakdown["return_score"] = round(ret_1m_rank * 0.3 + ret_1y_rank * 0.7, 1)

        # downside_protection — lower drawdown = better (invert rank)
        dd_rank = _pct_rank(r.get("max_drawdown_1y"), drawdowns)
        breakdown["downside_protection"] = round(100 - dd_rank, 1)  # inverted

        # volatility_score — lower vol = better (invert rank)
        vol_rank = _pct_rank(r.get("volatility_30d"), vols)
        breakdown["volatility_score"] = round(100 - vol_rank, 1)

        # momentum_score — 3m return rank
        breakdown["momentum_score"] = _pct_rank(r.get("returns_3m"), returns_3m)

        # ── Weighted composite ─────────────────────────────────────────────
        raw_score = sum(
            breakdown.get(k, 50) * w
            for k, w in WEIGHTS.items()
        )
        conviction = max(0.0, min(100.0, round(raw_score, 1)))

        # ── Confidence — based on data completeness ────────────────────────
        fields = ["yield_pct", "returns_1y", "returns_1m", "volatility_30d", "max_drawdown_1y", "returns_3m"]
        filled = sum(1 for f in fields if r.get(f) is not None)
        confidence = round((filled / len(fields)) * 100)

        # Penalise stale data
        if r.get("data_quality") == "stale":
            confidence = max(0, confidence - 30)
            conviction = round(conviction * 0.85, 1)

        r.update({
            "conviction_score": conviction,
            "confidence_score": confidence,
            "score_breakdown": breakdown,
            "score_version": "v2",
            "extras": {
                "sponsor": r.pop("sponsor", None),
                "nav_per_unit": r.pop("nav_per_unit", None),
                "nav_premium_pct": r.pop("nav_premium_pct", None),
            },
        })

    return records


# ── Public API ────────────────────────────────────────────────────────────────

def build_reit_frame() -> list[dict[str, Any]]:
    """
    Fetch data for all REIT/InvIT universe symbols and return a list
    of scored InvestmentInstrument dicts.
    """
    import concurrent.futures

    raw_records: list[dict[str, Any]] = []

    def _fetch(symbol: str, meta: dict) -> dict:
        try:
            return _compute_raw_metrics(symbol, meta)
        except Exception as exc:
            logger.warning("REIT fetch failed for %s: %s", symbol, exc)
            return {
                "symbol": symbol,
                "name": meta.get("name", symbol),
                "asset_class": meta.get("type", "REIT"),
                "sub_type": meta.get("sub_type", ""),
                "sector": meta.get("sector", "Real Estate"),
                "currency": "INR",
                "price": None,
                "returns_1m": None, "returns_3m": None,
                "returns_6m": None, "returns_1y": None,
                "volatility_30d": None, "max_drawdown_1y": None,
                "yield_pct": None, "data_quality": "stale",
                "last_updated": datetime.now(timezone.utc).isoformat(),
                "risk_flags": ["fetch_error"],
            }

    with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
        futures = {
            pool.submit(_fetch, sym, meta): sym
            for sym, meta in REIT_INVIT_UNIVERSE.items()
            if meta is not None
        }
        for fut in concurrent.futures.as_completed(futures):
            raw_records.append(fut.result())

    return _score_universe(raw_records)


def get_reit_detail(symbol: str) -> Optional[dict[str, Any]]:
    """Fetch and score a single REIT/InvIT symbol."""
    meta = REIT_INVIT_UNIVERSE.get(symbol)
    if meta is None:
        return None
    raw = _compute_raw_metrics(symbol, meta)
    scored = _score_universe([raw])
    return scored[0] if scored else None
