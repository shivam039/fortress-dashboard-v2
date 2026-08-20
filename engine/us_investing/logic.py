"""
us_investing/logic.py
=====================
Data processing, scoring, and risk-flag generation for US stocks & ETFs.

Conviction score (0-100) breakdown:
  - return_score         (25%) — 1m/1y return vs S&P 500
  - momentum_score       (20%) — 3m price momentum vs peers
  - downside_protection  (20%) — max drawdown vs peers (inverted)
  - volatility_score     (15%) — 30d vol vs peers (inverted)
  - valuation            (10%) — P/E vs sector median (lower = better)
  - liquidity            (10%) — average volume rank
"""

import logging
import math
from datetime import datetime, timezone
from typing import Any, Optional

import pandas as pd

from us_investing.service import get_service
from us_investing.universe import FULL_UNIVERSE

logger = logging.getLogger("fortress.us_investing")

WEIGHTS = {
    "return_score": 0.25,
    "momentum_score": 0.20,
    "downside_protection": 0.20,
    "volatility_score": 0.15,
    "valuation": 0.10,
    "liquidity": 0.10,
}


def _safe(val: Any) -> Optional[float]:
    if val is None:
        return None
    try:
        f = float(val)
        if math.isnan(f) or math.isinf(f):
            return None
        return f
    except (TypeError, ValueError):
        return None


def _pct_rank(value: Optional[float], peers: list[float]) -> float:
    if value is None or not peers:
        return 50.0
    clean = [v for v in peers if v is not None]
    if not clean:
        return 50.0
    return round(sum(1 for p in clean if p <= value) / len(clean) * 100, 1)


def _compute_raw_metrics(
    symbol: str,
    meta: dict[str, Any],
    raw_data: Optional[dict[str, Any]],
    usd_inr: float,
    include_inr: bool,
) -> dict[str, Any]:
    instrument_type = meta.get("type", "stock")
    result: dict[str, Any] = {
        "symbol": symbol,
        "name": meta.get("name", symbol),
        "asset_class": "US_ETF" if instrument_type == "etf" else "US_STOCK",
        "sub_type": instrument_type,
        "sector": meta.get("sector", ""),
        "currency": "USD",
        "price": None,
        "price_inr": None,
        "returns_1m": None, "returns_3m": None,
        "returns_6m": None, "returns_1y": None,
        "volatility_30d": None,
        "max_drawdown_1y": None,
        "yield_pct": None,
        "data_quality": "stale",
        "last_updated": datetime.now(timezone.utc).isoformat(),
        "risk_flags": [],
        # extras for richer detail
        "pe_ratio": None, "pb_ratio": None,
        "revenue_growth_yoy": None, "earnings_growth_yoy": None,
        "avg_volume": None, "market_cap_usd": None,
        "expense_ratio": None, "aum_usd": None, "beta": None,
        "usd_inr_rate": usd_inr if include_inr else None,
    }

    if not raw_data:
        result["risk_flags"].append("no_price_data")
        return result

    info = raw_data.get("info", {})
    hist: pd.DataFrame = raw_data.get("history", pd.DataFrame())

    if hist.empty or "Close" not in hist.columns:
        result["risk_flags"].append("no_price_data")
        return result

    close = hist["Close"].dropna()
    if len(close) < 5:
        result["risk_flags"].append("insufficient_history")
        return result

    result["data_quality"] = "complete"
    price = _safe(close.iloc[-1])
    result["price"] = price
    if include_inr and price:
        result["price_inr"] = round(price * usd_inr, 2)

    # ── Returns ───────────────────────────────────────────────────────────────
    def _ret(days: int) -> Optional[float]:
        if len(close) <= days:
            return None
        p = close.iloc[-(days + 1)]
        c = close.iloc[-1]
        if _safe(p) and p != 0:
            return round((c - p) / p * 100, 2)
        return None

    result["returns_1m"] = _ret(21)
    result["returns_3m"] = _ret(63)
    result["returns_6m"] = _ret(126)
    result["returns_1y"] = _ret(252)

    # ── Volatility ─────────────────────────────────────────────────────────
    if len(close) >= 30:
        vol = _safe(close.pct_change().dropna().tail(30).std() * (252 ** 0.5) * 100)
        result["volatility_30d"] = vol
        if vol and vol > 50:
            result["risk_flags"].append("high_volatility")

    # ── Max drawdown ───────────────────────────────────────────────────────
    rolling_max = close.cummax()
    mdd = _safe(((close - rolling_max) / rolling_max * 100).min())
    result["max_drawdown_1y"] = mdd
    if mdd and mdd < -35:
        result["risk_flags"].append("high_drawdown")

    # ── From info dict ─────────────────────────────────────────────────────
    dy = _safe(info.get("dividendYield") or info.get("yield", 0))
    result["yield_pct"] = round(dy * 100, 2) if dy and dy < 1 else dy

    result["pe_ratio"] = _safe(info.get("trailingPE") or info.get("forwardPE"))
    result["pb_ratio"] = _safe(info.get("priceToBook"))
    result["beta"] = _safe(info.get("beta"))
    result["avg_volume"] = _safe(info.get("averageVolume"))
    result["market_cap_usd"] = _safe(info.get("marketCap"))
    result["expense_ratio"] = _safe(info.get("annualReportExpenseRatio"))
    result["aum_usd"] = _safe(info.get("totalAssets"))
    result["revenue_growth_yoy"] = _safe(info.get("revenueGrowth"))
    result["earnings_growth_yoy"] = _safe(info.get("earningsGrowth"))

    # ── Risk flags ─────────────────────────────────────────────────────────
    pe = result["pe_ratio"]
    if pe and pe > 60:
        result["risk_flags"].append("high_pe")
    vol_30 = result["avg_volume"]
    if vol_30 and vol_30 < 100_000:
        result["risk_flags"].append("low_liquidity")
    beta = result["beta"]
    if beta and beta > 2.0:
        result["risk_flags"].append("high_beta")

    # ── Staleness ─────────────────────────────────────────────────────────
    last_date = hist.index[-1]
    if hasattr(last_date, "date"):
        from datetime import date
        age_days = (date.today() - last_date.date()).days
        if age_days > 3:
            result["data_quality"] = "stale"
            result["risk_flags"].append("stale_data")

    return result


def _score_universe(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    valid = [r for r in records if r.get("price")]

    returns_1y = [r.get("returns_1y") for r in valid if r.get("returns_1y") is not None]
    returns_1m = [r.get("returns_1m") for r in valid if r.get("returns_1m") is not None]
    returns_3m = [r.get("returns_3m") for r in valid if r.get("returns_3m") is not None]
    vols = [r.get("volatility_30d") for r in valid if r.get("volatility_30d") is not None]
    drawdowns = [r.get("max_drawdown_1y") for r in valid if r.get("max_drawdown_1y") is not None]
    pes = [r.get("pe_ratio") for r in valid if r.get("pe_ratio") is not None and r.get("pe_ratio") > 0]
    volumes = [r.get("avg_volume") for r in valid if r.get("avg_volume") is not None]

    for r in records:
        if not r.get("price"):
            r.update({
                "conviction_score": None,
                "confidence_score": 0,
                "score_breakdown": {},
                "score_version": "v2",
                "extras": {k: r.pop(k, None) for k in [
                    "pe_ratio", "pb_ratio", "revenue_growth_yoy", "earnings_growth_yoy",
                    "avg_volume", "market_cap_usd", "expense_ratio", "aum_usd",
                    "beta", "usd_inr_rate",
                ]},
            })
            continue

        bd: dict[str, float] = {}

        r1m = _pct_rank(r.get("returns_1m"), returns_1m)
        r1y = _pct_rank(r.get("returns_1y"), returns_1y)
        bd["return_score"] = round(r1m * 0.3 + r1y * 0.7, 1)

        bd["momentum_score"] = _pct_rank(r.get("returns_3m"), returns_3m)
        bd["downside_protection"] = round(100 - _pct_rank(r.get("max_drawdown_1y"), drawdowns), 1)
        bd["volatility_score"] = round(100 - _pct_rank(r.get("volatility_30d"), vols), 1)

        # valuation: lower PE = better (inverted)
        if r.get("pe_ratio") and r["pe_ratio"] > 0:
            bd["valuation"] = round(100 - _pct_rank(r["pe_ratio"], pes), 1)
        else:
            bd["valuation"] = 50.0  # neutral for ETFs / no PE

        bd["liquidity"] = _pct_rank(r.get("avg_volume"), volumes)

        raw_score = sum(bd.get(k, 50) * w for k, w in WEIGHTS.items())
        conviction = max(0.0, min(100.0, round(raw_score, 1)))

        fields = ["returns_1y", "returns_1m", "volatility_30d", "max_drawdown_1y", "returns_3m"]
        filled = sum(1 for f in fields if r.get(f) is not None)
        confidence = round((filled / len(fields)) * 100)
        if r.get("data_quality") == "stale":
            confidence = max(0, confidence - 30)
            conviction = round(conviction * 0.85, 1)

        extras = {k: r.pop(k, None) for k in [
            "pe_ratio", "pb_ratio", "revenue_growth_yoy", "earnings_growth_yoy",
            "avg_volume", "market_cap_usd", "expense_ratio", "aum_usd",
            "beta", "usd_inr_rate",
        ]}

        r.update({
            "conviction_score": conviction,
            "confidence_score": confidence,
            "score_breakdown": bd,
            "score_version": "v2",
            "extras": extras,
        })

    return records


def build_us_frame(include_inr: bool = True) -> list[dict[str, Any]]:
    """
    Fetch data for all US universe symbols and return scored records.
    """
    import concurrent.futures

    svc = get_service()
    usd_inr = svc.get_usd_inr_rate() if include_inr else 84.0
    symbols = list(FULL_UNIVERSE.keys())

    raw_map: dict[str, Any] = {}

    def _fetch(sym: str) -> tuple:
        data = svc.fetch_single(sym)
        return sym, data

    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
        futures = [pool.submit(_fetch, sym) for sym in symbols]
        for fut in concurrent.futures.as_completed(futures):
            sym, data = fut.result()
            raw_map[sym] = data

    records = [
        _compute_raw_metrics(sym, FULL_UNIVERSE[sym], raw_map.get(sym), usd_inr, include_inr)
        for sym in symbols
    ]

    return _score_universe(records)


def get_us_detail(symbol: str, include_inr: bool = True) -> Optional[dict[str, Any]]:
    meta = FULL_UNIVERSE.get(symbol)
    if meta is None:
        return None
    svc = get_service()
    usd_inr = svc.get_usd_inr_rate() if include_inr else 84.0
    raw_data = svc.fetch_single(symbol)
    raw = _compute_raw_metrics(symbol, meta, raw_data, usd_inr, include_inr)
    scored = _score_universe([raw])
    return scored[0] if scored else None


def search_us_universe(query: str) -> list[dict[str, Any]]:
    """Search by symbol or name prefix (returns static universe metadata, no price fetch)."""
    q = query.strip().lower()
    if not q:
        return []
    results = []
    for sym, meta in FULL_UNIVERSE.items():
        if q in sym.lower() or q in meta.get("name", "").lower():
            results.append({
                "symbol": sym,
                "name": meta.get("name", sym),
                "sector": meta.get("sector", ""),
                "type": meta.get("type", "stock"),
            })
    return results[:20]
