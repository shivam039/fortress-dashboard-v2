"""
reit_invits/logic.py
====================
Data fetching, scoring, and risk-flag generation for Indian REITs & InvITs.

Conviction score (0-100) breakdown:
  - yield_score              (20%) — trailing 12-month distribution yield
                                      vs peers, computed from actual payout
                                      history (see _fetch_distribution_
                                      history), not yfinance's often-stale
                                      `info.dividendYield`
  - distribution_growth_score (15%) — is the per-unit distribution growing
                                      or shrinking vs 3 years ago, vs peers
  - return_score             (20%) — 1m / 1y price return vs peers
  - downside_protection      (15%) — max drawdown vs peers
  - volatility_score         (15%) — 30d annualised volatility vs peers
  - momentum_score           (15%) — 3m price momentum vs peers

Each instrument also gets a shared Conviction Label (STRONG BUY / BUY /
HOLD / UNDERPERFORMER / AVOID — from utils.conviction_engine, the same
label vocabulary used everywhere else in this app) plus a plain-language
valuation note describing where the unit trades relative to its NAV, since
"is there any upside left" for a REIT/InvIT is largely a valuation question
that a pure momentum/return score doesn't capture on its own.
"""

import concurrent.futures
import logging
import math
import time
from datetime import date, datetime, timezone
from typing import Any, Optional

import pandas as pd
import yfinance as yf
from utils.conviction_engine import _label as _conviction_label

from reit_invits.universe import REIT_INVIT_UNIVERSE

logger = logging.getLogger("fortress.reit_invits")

# How long a single yfinance call (.dividends, .info) is allowed to run
# before this module gives up on it and moves on. yf.download() takes an
# explicit `timeout` argument (see _fetch_history below), but Ticker.info
# and Ticker.dividends don't expose one — internally they can retry cookie/
# crumb negotiation with Yahoo before even reaching the actual data request,
# so on a slow or rate-limited connection (yfinance from cloud-provider IPs,
# including Render, is frequently throttled) a single .info call has been
# observed taking most of a minute. Left unbounded, 2-3 such calls per
# symbol easily blow past the whole batch's _BATCH_TIMEOUT_S before even one
# symbol finishes — which is exactly what "N/N symbols still pending"
# in that batch-timeout warning means: not that every symbol failed, but
# that not even one had time to complete all its calls.
_PER_CALL_TIMEOUT_S = 12


def _call_with_timeout(fn, timeout_s: float = _PER_CALL_TIMEOUT_S, default=None):
    """Run fn() with a hard wall-clock deadline. yfinance gives no timeout
    knob for Ticker.info/.dividends, and a stalled TCP connection inside fn
    can't be cancelled from the outside in pure Python — so, same tradeoff
    build_reit_frame already makes at the batch level, the worker thread is
    abandoned (not joined) rather than blocked on if it doesn't finish in
    time."""
    pool = concurrent.futures.ThreadPoolExecutor(max_workers=1)
    try:
        return pool.submit(fn).result(timeout=timeout_s)
    except Exception:
        return default
    finally:
        pool.shutdown(wait=False)

# ── Weight config ─────────────────────────────────────────────────────────────
WEIGHTS = {
    "yield_score": 0.20,
    "distribution_growth_score": 0.15,
    "return_score": 0.20,
    "downside_protection": 0.15,
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
                timeout=_PER_CALL_TIMEOUT_S,
            )
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = df.columns.get_level_values(0)
            if not df.empty:
                return df
        except Exception as exc:
            logger.debug("fetch_history %s attempt %d: %s", symbol, attempt, exc)
            time.sleep(0.5)
    return pd.DataFrame()


def _fetch_distribution_history(symbol: str) -> dict[str, Any]:
    """Fetch actual historical per-unit distributions (dividends/payouts)
    from yfinance's corporate-actions feed, and derive trailing 1y/3y
    totals plus a growth signal.

    This is the real record of what a unit-holder was actually paid —
    more trustworthy than yfinance's `info.dividendYield` field, which for
    REITs/InvITs is frequently stale, missing, or computed off a single
    most-recent payout rather than the trailing-12-month total.
    """
    out: dict[str, Any] = {
        "distributions_1y": None,
        "distributions_3y": None,
        "distributions_3y_avg": None,
        "distribution_count_1y": None,
        "distribution_growth_3y_pct": None,
    }
    divs = _call_with_timeout(lambda: yf.Ticker(symbol).dividends)
    if divs is None or divs.empty:
        return out

    # yfinance's dividend index is tz-aware (Asia/Kolkata); strip the tz so
    # it compares cleanly against naive Timestamps below.
    if getattr(divs.index, "tz", None) is not None:
        divs = divs.copy()
        divs.index = divs.index.tz_localize(None)

    today = pd.Timestamp(date.today())
    one_year_ago = today - pd.Timedelta(days=365)
    three_years_ago = today - pd.Timedelta(days=3 * 365)

    last_1y = divs[divs.index >= one_year_ago]
    last_3y = divs[divs.index >= three_years_ago]

    if not last_1y.empty:
        out["distributions_1y"] = _safe(last_1y.sum())
        out["distribution_count_1y"] = int(len(last_1y))
    if not last_3y.empty:
        total_3y = _safe(last_3y.sum())
        out["distributions_3y"] = total_3y
        out["distributions_3y_avg"] = round(total_3y / 3, 4) if total_3y is not None else None

    # Growth signal: the most recent 12 months of payouts vs. the 12 months
    # ending ~3 years ago — i.e. is the distribution trending up or down
    # over the trust's history, not just noisy quarter-to-quarter movement.
    baseline_start = today - pd.Timedelta(days=3 * 365)
    baseline_end = today - pd.Timedelta(days=2 * 365)
    baseline = divs[(divs.index >= baseline_start) & (divs.index < baseline_end)]
    if not baseline.empty and out["distributions_1y"]:
        baseline_sum = _safe(baseline.sum())
        if baseline_sum and baseline_sum > 0:
            out["distribution_growth_3y_pct"] = round(
                (out["distributions_1y"] - baseline_sum) / baseline_sum * 100, 1
            )

    return out


# ── Per-symbol raw metrics ────────────────────────────────────────────────────

def _compute_raw_metrics(symbol: str, meta: dict[str, Any]) -> dict[str, Any]:
    hist = _fetch_history(symbol, "1y")

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
        "distributions_1y": None,
        "distributions_3y": None,
        "distributions_3y_avg": None,
        "distribution_count_1y": None,
        "distribution_growth_3y_pct": None,
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

    # ── Distribution history (real payouts, past 1y/3y) ───────────────────
    dist = _fetch_distribution_history(symbol)
    result.update(dist)

    # ── Yield ────────────────────────────────────────────────────────────
    # Prefer the trailing-12-month yield computed from actual distribution
    # history above — it's a real, auditable number ("this trust paid
    # ₹X/unit over the last year, price is ₹Y, so yield is X/Y"). Only fall
    # back to yfinance's `info.dividendYield` when a trust doesn't have a
    # full year of listed history yet (e.g. a fund that IPO'd recently) and
    # so `distributions_1y` is None.
    if dist.get("distributions_1y") and result["price"]:
        result["yield_pct"] = round(dist["distributions_1y"] / result["price"] * 100, 2)

    info = _call_with_timeout(lambda: yf.Ticker(symbol).info, default={}) or {}
    if info:
        if result["yield_pct"] is None:
            div_yield = _safe(info.get("dividendYield") or info.get("yield"))
            if div_yield:
                result["yield_pct"] = round(div_yield * 100, 2) if div_yield < 1 else div_yield
        # NAV / book value proxy
        nav = _safe(info.get("bookValue"))
        if nav and result["price"]:
            result["nav_per_unit"] = nav
            result["nav_premium_pct"] = round((result["price"] - nav) / nav * 100, 2)

    # ── Staleness check ───────────────────────────────────────────────────
    last_date = hist.index[-1]
    if hasattr(last_date, "date"):
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
    growth_rates = [
        r.get("distribution_growth_3y_pct") for r in valid if r.get("distribution_growth_3y_pct") is not None
    ]

    for r in records:
        if not r.get("price"):
            r.update({
                "conviction_score": None,
                "confidence_score": 0,
                "score_breakdown": {},
                "score_version": "v2",
                "conviction_label": None,
                "conviction_emoji": None,
                "valuation_note": None,
            })
            continue

        # ── Sub-scores (each 0-100) ────────────────────────────────────────
        breakdown: dict[str, float] = {}

        # yield_score — higher trailing distribution yield rank = better
        breakdown["yield_score"] = _pct_rank(r.get("yield_pct"), yields)

        # distribution_growth_score — is the per-unit payout growing vs 3
        # years ago? Funds without 3y of listed history get a neutral 50
        # here (via _pct_rank's None handling) rather than being penalised
        # for simply being newer listings.
        breakdown["distribution_growth_score"] = _pct_rank(
            r.get("distribution_growth_3y_pct"), growth_rates
        )

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
        # `distribution_growth_3y_pct` is deliberately excluded here: most
        # listed Indian REITs/InvITs are under 3 years old, so it's
        # legitimately absent for otherwise well-covered, high-quality
        # funds — penalising confidence for that would just be penalising
        # newness.
        fields = [
            "yield_pct", "returns_1y", "returns_1m", "volatility_30d",
            "max_drawdown_1y", "returns_3m", "distributions_1y",
        ]
        filled = sum(1 for f in fields if r.get(f) is not None)
        confidence = round((filled / len(fields)) * 100)

        # Penalise stale data
        if r.get("data_quality") == "stale":
            confidence = max(0, confidence - 30)
            conviction = round(conviction * 0.85, 1)

        label, emoji = _conviction_label(conviction)

        # ── Valuation note ───────────────────────────────────────────────
        # "Any steam left?" for a REIT/InvIT is largely a valuation
        # question — a unit trading well above its own NAV has already
        # priced in a lot of the good news; one trading at a discount has
        # more room, all else equal. This doesn't get folded into the
        # numeric score (NAV-per-unit data from yfinance is inconsistent
        # across trusts), but it's surfaced as plain-language context next
        # to the score.
        nav_premium = r.get("nav_premium_pct")
        if nav_premium is None:
            valuation_note = None
        elif nav_premium <= -5:
            valuation_note = f"Trading {abs(nav_premium):.1f}% below NAV — potential value entry if fundamentals hold"
        elif nav_premium <= 5:
            valuation_note = f"Trading close to NAV ({nav_premium:+.1f}%) — fairly valued"
        elif nav_premium <= 15:
            valuation_note = f"Trading {nav_premium:.1f}% above NAV — a moderate premium"
        else:
            valuation_note = f"Trading {nav_premium:.1f}% above NAV — a rich premium, limited margin of safety"

        r.update({
            "conviction_score": conviction,
            "confidence_score": confidence,
            "score_breakdown": breakdown,
            "score_version": "v2",
            "conviction_label": label,
            "conviction_emoji": emoji,
            "valuation_note": valuation_note,
            "extras": {
                "sponsor": r.pop("sponsor", None),
                "nav_per_unit": r.pop("nav_per_unit", None),
                "nav_premium_pct": r.pop("nav_premium_pct", None),
            },
        })

    return records


# ── Public API ────────────────────────────────────────────────────────────────

def _placeholder_record(symbol: str, meta: dict, flag: str) -> dict[str, Any]:
    """Fallback record for a symbol whose fetch errored or never finished."""
    return {
        "symbol": symbol,
        "name": meta.get("name", symbol),
        "asset_class": meta.get("type", "REIT"),
        "sub_type": meta.get("sub_type", ""),
        "sector": meta.get("sector", "Real Estate"),
        "sponsor": meta.get("sponsor", ""),
        "currency": "INR",
        "price": None,
        "returns_1m": None, "returns_3m": None,
        "returns_6m": None, "returns_1y": None,
        "volatility_30d": None, "max_drawdown_1y": None,
        "yield_pct": None,
        "distributions_1y": None, "distributions_3y": None,
        "distributions_3y_avg": None, "distribution_count_1y": None,
        "distribution_growth_3y_pct": None,
        "data_quality": "stale",
        "last_updated": datetime.now(timezone.utc).isoformat(),
        "risk_flags": [flag],
    }


# How long the whole batch fetch is allowed to run before giving up on
# whichever symbols haven't finished yet. yfinance's `.info`/`.dividends`
# calls don't expose a reliable per-call timeout in the installed version,
# and a genuinely hung network call inside a worker thread can't be forced
# to stop from the outside in pure Python — so this bounds the *request*,
# not the individual call. Without this, one stuck symbol could hang the
# entire /api/reit-invits response indefinitely (and, since the route
# itself must stay synchronous, tie up a request-handling thread the whole
# time) rather than degrading gracefully to "most instruments loaded, one
# timed out".
_BATCH_TIMEOUT_S = 45


def build_reit_frame() -> list[dict[str, Any]]:
    """
    Fetch data for all REIT/InvIT universe symbols and return a list
    of scored InvestmentInstrument dicts.
    """
    import concurrent.futures

    def _fetch(symbol: str, meta: dict) -> dict:
        try:
            return _compute_raw_metrics(symbol, meta)
        except Exception as exc:
            logger.warning("REIT fetch failed for %s: %s", symbol, exc)
            return _placeholder_record(symbol, meta, "fetch_error")

    pool = concurrent.futures.ThreadPoolExecutor(max_workers=6)
    futures = {
        pool.submit(_fetch, sym, meta): sym
        for sym, meta in REIT_INVIT_UNIVERSE.items()
        if meta is not None
    }

    raw_records: list[dict[str, Any]] = []
    done_syms: set[str] = set()
    try:
        for fut in concurrent.futures.as_completed(futures, timeout=_BATCH_TIMEOUT_S):
            sym = futures[fut]
            raw_records.append(fut.result())
            done_syms.add(sym)
    except concurrent.futures.TimeoutError:
        missing = [sym for sym in futures.values() if sym not in done_syms]
        logger.warning(
            "REIT/InvIT batch fetch hit its %ds overall timeout with %d/%d "
            "symbols still pending: %s",
            _BATCH_TIMEOUT_S, len(missing), len(futures), missing,
        )
        for sym in missing:
            raw_records.append(_placeholder_record(sym, REIT_INVIT_UNIVERSE.get(sym, {}) or {}, "fetch_timeout"))
    finally:
        # Don't block the caller waiting for stragglers that may never
        # finish — let them run out in the background instead.
        pool.shutdown(wait=False)

    return _score_universe(raw_records)


def get_reit_detail(symbol: str) -> Optional[dict[str, Any]]:
    """Fetch and score a single REIT/InvIT symbol."""
    meta = REIT_INVIT_UNIVERSE.get(symbol)
    if meta is None:
        return None
    raw = _compute_raw_metrics(symbol, meta)
    scored = _score_universe([raw])
    return scored[0] if scored else None
