"""
mf_lab/logic.py — Fortress MF Consistency Engine
Speed improvements:
  1. NAV history cached in Neon (mf_nav_cache, 20h TTL) — no repeat HTTP hits
  2. Benchmark OHLCV cached in Neon (ohlcv_cache, 20h TTL)
  3. 30-worker ThreadPoolExecutor — true parallelism
  4. mfapi.in discovery response cached in-process for the session
  5. Per-fund timeout guard (10 s) prevents straggler funds blocking the pool
"""

import logging
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd
import requests
from functools import lru_cache
import yfinance as yf
from fortress_config import INDEX_BENCHMARKS, MF_SCHEMES

try:
    from mftool import Mftool
except Exception:
    Mftool = None

logger = logging.getLogger(__name__)

# ── In-process caches ────────────────────────────────────────────────────────
_BENCH_CACHE: Dict[str, pd.Series] = {}
_DISCOVERY_CACHE: Optional[Dict[str, str]] = None  # refreshed once per process


# ────────────────────────────────────────────────────────────────────────────
#  Utilities
# ────────────────────────────────────────────────────────────────────────────


def _retry(op, name: str, retries: int = 2, base_delay: float = 0.5):
    last = None
    for attempt in range(retries):
        try:
            return op()
        except Exception as e:
            last = e
            logger.debug("%s attempt %d: %s", name, attempt + 1, e)
            time.sleep(base_delay * (2**attempt))
    raise RuntimeError(f"{name} failed") from last


def classify_category(name: str) -> tuple[str, str]:
    # Real AMC scheme names frequently use hyphens where the keywords below
    # use a space ("Multi-Asset Allocation Fund", "Flexi-Cap Fund",
    # "Small-Cap Fund") — normalizing hyphens to spaces lets every keyword
    # match both forms instead of silently missing the hyphenated one.
    nm = (name or "").lower().replace("-", " ")

    # Debt Subcategories
    if any(k in nm for k in ["liquid"]):
        sub = "Liquid"
    elif any(k in nm for k in ["money market"]):
        sub = "Money Market"
    elif any(k in nm for k in ["overnight", "1 d"]):
        sub = "Overnight"
    elif any(k in nm for k in ["gilt"]):
        sub = "Gilt"
    elif any(k in nm for k in ["credit risk"]):
        sub = "Credit Risk"
    elif any(k in nm for k in ["duration", "short term", "ultra short"]):
        sub = "Duration/Short Term"
    elif any(k in nm for k in ["bond", "debt", "income"]):
        sub = "Corporate/Dynamic Bond"
    else:
        sub = "General Debt"

    # Equity Subcategories
    if any(k in nm for k in ["elss", "tax saver"]):
        eq_sub = "ELSS (Tax Saver)"
    elif any(k in nm for k in ["small cap", "smallcap"]):
        eq_sub = "Small Cap"
    elif any(k in nm for k in ["mid cap", "midcap"]):
        eq_sub = "Mid Cap"
    elif any(k in nm for k in ["large cap", "largecap", "bluechip", "top 100"]):
        eq_sub = "Large Cap"
    # Flexi Cap (min 65% equity, no cap-size mandate) and Multi Cap (min 25%
    # each across large/mid/small) are distinct SEBI categories with
    # different mandates — they were previously lumped into one bucket.
    elif any(k in nm for k in ["flexi cap", "flexicap", "flexi"]):
        eq_sub = "Flexi Cap"
    elif any(k in nm for k in ["multi cap", "multicap"]):
        eq_sub = "Multi Cap"
    elif any(k in nm for k in ["focused"]):
        eq_sub = "Focused"
    elif any(k in nm for k in ["value", "contra"]):
        eq_sub = "Value/Contra"
    elif any(k in nm for k in ["dividend yield"]):
        eq_sub = "Dividend Yield"
    elif any(k in nm for k in ["index", "nifty"]):
        eq_sub = "Index Fund"
    else:
        eq_sub = "Sectoral/General Equity"

    # Hybrid Subcategories — SEBI defines several distinct hybrid categories
    # by equity allocation band; these were previously collapsed into
    # "General Hybrid" whenever a scheme name didn't literally contain
    # "aggressive hybrid" or "conservative hybrid", which most real AMC
    # names don't spell out verbatim (e.g. "Equity & Debt Fund", "Balanced
    # Fund", "Multi-Asset Allocation Fund").
    if any(k in nm for k in ["arbitrage"]):
        hy_sub = "Arbitrage"
    elif any(k in nm for k in ["equity savings"]):
        hy_sub = "Equity Savings"
    elif any(k in nm for k in ["balanced advantage", "dynamic asset", "baa"]):
        hy_sub = "Balanced Advantage"
    elif any(k in nm for k in ["balanced hybrid"]):
        hy_sub = "Balanced Hybrid"
    elif any(k in nm for k in ["conservative hybrid", "debt hybrid", "conservative"]):
        hy_sub = "Conservative Hybrid"
    elif any(k in nm for k in ["multi asset"]):
        hy_sub = "Multi Asset"
    elif any(
        k in nm
        for k in [
            "aggressive hybrid",
            "equity hybrid",
            "equity & debt",
            "equity and debt",
            "balanced",
        ]
    ):
        # SEBI's 2018 recategorization folded plain "Balanced Fund" naming
        # into Aggressive Hybrid (65-80% equity) — most surviving schemes
        # with just "Balanced" in the name are legacy holdovers of that.
        hy_sub = "Aggressive Hybrid"
    else:
        hy_sub = "General Hybrid"

    # Determine Primary Cat. Hybrid signals are checked first: a name like
    # "XYZ Debt Hybrid Fund" or "XYZ Conservative Hybrid Fund" contains
    # "debt" too, and would otherwise get short-circuited into Debt before
    # its (unambiguous) "hybrid" signal is ever considered. No pure debt or
    # equity fund name contains these hybrid keywords, so checking them
    # first cannot misclassify a real debt/equity fund as Hybrid.
    if any(
        k in nm
        for k in [
            "hybrid",
            "balanced",
            "conservative",
            "asset allocation",
            "arbitrage",
            "advantage",
            "equity savings",
            "equity & debt",
            "equity and debt",
        ]
    ):
        return ("Hybrid", hy_sub)
    if any(
        k in nm
        for k in [
            "liquid",
            "bond",
            "gilt",
            "debt",
            "duration",
            "overnight",
            "money market",
            "credit risk",
            "income",
        ]
    ):
        return ("Debt", sub)

    return ("Equity", eq_sub)


# ────────────────────────────────────────────────────────────────────────────
#  Benchmark helpers
# ────────────────────────────────────────────────────────────────────────────


def _get_benchmark_series(ticker: str) -> pd.Series:
    if ticker in _BENCH_CACHE:
        return _BENCH_CACHE[ticker]
    # 1. Neon OHLCV cache
    try:
        from utils.db import fetch_ohlcv_cache

        cached = fetch_ohlcv_cache(ticker, period="5y", max_age_hours=20)
        if cached is not None and not cached.empty and "Close" in cached.columns:
            s = cached["Close"].pct_change().dropna()
            _BENCH_CACHE[ticker] = s
            return s
    except Exception:
        pass

    # 2. Live yfinance
    def _dl():
        d = yf.download(
            ticker, period="5y", interval="1d", progress=False, auto_adjust=True
        )
        if d.empty:
            return pd.Series(dtype=float)
        if isinstance(d.columns, pd.MultiIndex):
            d.columns = d.columns.get_level_values(0)
        try:
            from utils.db import upsert_ohlcv_cache

            upsert_ohlcv_cache(ticker, "5y", d)
        except Exception:
            pass
        close_series = d.get("Close")
        if close_series is None or close_series.empty:
            close_series = d.iloc[:, 0]
        return close_series.pct_change().dropna()

    s = _retry(_dl, f"bench_{ticker}")
    _BENCH_CACHE[ticker] = s
    return s


@lru_cache(maxsize=32)
def fetch_benchmark_returns(
    ticker: str = INDEX_BENCHMARKS.get("Nifty 50", "^NSEI")
) -> pd.Series:
    return _get_benchmark_series(ticker)


# ────────────────────────────────────────────────────────────────────────────
#  NAV History — Neon-cached with graceful fallback
# ────────────────────────────────────────────────────────────────────────────


def fetch_nav_history(scheme_code: str, max_age_hours: int = 20) -> pd.DataFrame:
    """
    Priority: Neon mf_nav_cache → mfapi.in live + UPSERT back to Neon.
    """
    code = str(scheme_code)

    # 1. Neon cache
    try:
        from utils.db import fetch_mf_nav_cache, upsert_mf_nav_cache

        cached = fetch_mf_nav_cache(code, max_age_hours=max_age_hours)
        if cached is not None and not cached.empty:
            return cached
    except Exception:
        pass

    # 2. Live mfapi.in
    def _load():
        resp = requests.get(f"https://api.mfapi.in/mf/{code}", timeout=10)
        resp.raise_for_status()
        rows = resp.json().get("data", [])
        if not rows:
            return pd.DataFrame()
        df = pd.DataFrame(rows)
        df["date"] = pd.to_datetime(df["date"], format="%d-%m-%Y", errors="coerce")
        df["nav"] = pd.to_numeric(df["nav"], errors="coerce")
        df = df.dropna(subset=["date", "nav"]).sort_values("date").set_index("date")
        df = df.asfreq("B").ffill()
        df["ret"] = df["nav"].pct_change()
        return df.dropna()

    try:
        df = _retry(_load, f"nav_{code}", retries=2, base_delay=0.3)
        # Back-fill Neon cache
        try:
            from utils.db import upsert_mf_nav_cache

            upsert_mf_nav_cache(code, df)
        except Exception:
            pass
        return df
    except Exception as e:
        logger.debug("fetch_nav_history %s: %s", code, e)
        return pd.DataFrame()


def backtest_vs_benchmark(scheme_code: str) -> pd.DataFrame:
    fund = fetch_nav_history(scheme_code)
    bench = fetch_benchmark_returns()
    if fund.empty or bench.empty:
        return pd.DataFrame()
    merged = pd.DataFrame({"fund": fund["ret"], "bench": bench}).dropna()
    if merged.empty:
        return pd.DataFrame()
    out = (1 + merged).cumprod()
    out.columns = ["Fund", "Nifty 50"]
    return out


# ────────────────────────────────────────────────────────────────────────────
#  Per-fund scorer (runs inside thread)
# ────────────────────────────────────────────────────────────────────────────


def _score_fund(code: str, bench_default: pd.Series) -> Optional[Dict[str, Any]]:
    try:
        history = fetch_nav_history(str(code))
        if history.empty:
            return None

        nav = float(history["nav"].iloc[-1])
        scheme_name = f"Scheme {code}"

        bench_ticker = INDEX_BENCHMARKS.get("Nifty 50", "^NSEI")
        nm = scheme_name.lower()
        if "small cap" in nm or "smallcap" in nm:
            bench_ticker = INDEX_BENCHMARKS.get("Nifty Smallcap 250", "^CNXSC")
        elif "mid cap" in nm or "midcap" in nm:
            bench_ticker = INDEX_BENCHMARKS.get("Nifty Midcap 150", "^NSMIDCP")

        bench = (
            bench_default
            if bench_ticker == INDEX_BENCHMARKS.get("Nifty 50")
            else _get_benchmark_series(bench_ticker)
        )
        ret = history["ret"].dropna()

        alpha = beta = np.nan
        if not bench.empty and not ret.empty:
            combined = pd.concat([ret, bench], axis=1, join="inner").dropna()
            if len(combined) > 60:
                cov = np.cov(combined.iloc[:, 0], combined.iloc[:, 1])
                var = np.var(combined.iloc[:, 1])
                beta = cov[0, 1] / var if var else 1.0
                rp = combined.iloc[:, 0].mean() * 252
                rm = combined.iloc[:, 1].mean() * 252
                alpha = ((rp - 0.06) - beta * (rm - 0.06)) * 100

        n = len(history)
        ret_1y = history["nav"].pct_change(252).iloc[-1] * 100 if n > 252 else np.nan
        ret_3y = (
            (
                (history["nav"].iloc[-1] / history["nav"].iloc[-min(756, n)])
                ** (252 / min(756, n))
                - 1
            )
            * 100
            if n > 252
            else np.nan
        )
        ret_5y = (
            (
                (history["nav"].iloc[-1] / history["nav"].iloc[-min(1260, n)])
                ** (252 / min(1260, n))
                - 1
            )
            * 100
            if n > 252
            else np.nan
        )

        vol = ret.std() * np.sqrt(252) * 100
        downside = ret[ret < 0].std() * np.sqrt(252) * 100
        sharpe = ((ret.mean() * 252) - 0.06) / (ret.std() * np.sqrt(252) + 1e-9)
        sortino = ((ret.mean() * 252) - 0.06) / (
            (ret[ret < 0].std() * np.sqrt(252)) + 1e-9
        )
        roll_std = ret.rolling(21).std().mean() * np.sqrt(252) * 100

        return {
            "Scheme Code": code,
            "Scheme": scheme_name,
            "NAV": nav,
            "1Y Return": ret_1y,
            "3Y Return": ret_3y,
            "5Y Return": ret_5y,
            "Volatility": vol,
            "Downside Deviation": downside,
            "Sharpe": sharpe,
            "Sortino": sortino,
            "Rolling Std": roll_std,
            "Alpha": alpha,
            "Beta": beta,
            "Benchmark": bench_ticker,
        }
    except Exception as e:
        logger.debug("_score_fund %s: %s", code, e)
        return None


# ────────────────────────────────────────────────────────────────────────────
#  Fund Discovery
# ────────────────────────────────────────────────────────────────────────────


def discover_all_funds(limit: Optional[int] = None) -> List[str]:
    global _DISCOVERY_CACHE
    if _DISCOVERY_CACHE is not None:
        codes = list(_DISCOVERY_CACHE.keys())
        return codes[:limit] if limit else codes

    try:
        resp = requests.get("https://api.mfapi.in/mf", timeout=20)
        resp.raise_for_status()
        schemes = resp.json()

        equity_kw = [
            "flexi",
            "multi",
            "large",
            "mid",
            "small",
            "focused",
            "value",
            "contra",
            "elss",
        ]
        debt_kw = ["liquid", "gilt", "bond", "duration", "overnight", "corporate"]
        all_kw = equity_kw + debt_kw

        codes_map = {}
        for s in schemes:
            name = s["schemeName"].lower()
            if not all(r in name for r in ["direct", "growth"]):
                continue
            if not any(k in name for k in all_kw):
                continue
            if any(e in name for e in ["regular", "idcw"]):
                continue
            if "etf" in name and not any(k in name for k in debt_kw):
                continue
            codes_map[str(s["schemeCode"])] = s["schemeName"]

        _DISCOVERY_CACHE = codes_map
        logger.info("discover_all_funds: found %d schemes", len(codes_map))
        codes = list(codes_map.keys())
        return codes[:limit] if limit else codes

    except Exception as e:
        logger.error("discover_all_funds failed: %s", e)
        return [str(c) for c in MF_SCHEMES]


# ────────────────────────────────────────────────────────────────────────────
#  Pre-seed NAV cache from Neon  (warm up before parallel scoring)
# ────────────────────────────────────────────────────────────────────────────


def _bulk_preseed_nav_cache(codes: List[str]) -> Dict[str, pd.DataFrame]:
    """
    Single SQL query to pull ALL non-stale NAV rows in one shot, instead of
    one SELECT per fund inside the thread pool. Avoids N×SELECT and cuts
    cold-start latency dramatically.

    Works on both backends. This previously returned `{}` immediately on
    SQLite (`if not _can_use_neon(): return {}`) — meaning on local dev
    (FORTRESS_DB_BACKEND=sqlite) this pre-seed step was a complete no-op,
    and combined with `fetch_mf_nav_cache`/`upsert_mf_nav_cache` also being
    Neon-only until now, every single MF scan re-downloaded NAV history from
    mfapi.in live for every discovered fund — the main reason MF scans are
    slow, since `run_full_mf_scan()` with no `limit` discovers essentially
    the whole direct-growth fund universe, not just a handful.
    """
    if not codes:
        return {}
    try:
        import io
        import json as _json

        from utils.db import _can_use_neon

        cache: Dict[str, pd.DataFrame] = {}

        if _can_use_neon():
            from sqlalchemy import text as sa_text
            from utils.db import get_db_engine

            engine = get_db_engine()
            placeholders = ", ".join([f":c{i}" for i in range(len(codes))])
            params = {f"c{i}": c for i, c in enumerate(codes)}

            with engine.connect() as conn:
                rows = conn.execute(
                    sa_text(f"""
                        SELECT scheme_code, nav_json
                        FROM mf_nav_cache
                        WHERE scheme_code IN ({placeholders})
                          AND updated_at >= NOW() - INTERVAL '20 hours'
                    """),
                    params,
                ).fetchall()

            for r in rows:
                try:
                    df = pd.read_json(io.StringIO(_json.dumps(r[1])), orient="split")
                    df.index = pd.to_datetime(df.index)
                    cache[r[0]] = df
                except Exception:
                    pass
        else:
            from utils.db import _ensure_mf_nav_cache_sqlite, _sqlite_connection

            placeholders = ", ".join([f":c{i}" for i in range(len(codes))])
            params = {f"c{i}": c for i, c in enumerate(codes)}

            with _sqlite_connection() as conn:
                _ensure_mf_nav_cache_sqlite(conn)
                rows = conn.execute(
                    f"""
                    SELECT scheme_code, nav_json
                    FROM mf_nav_cache
                    WHERE scheme_code IN ({placeholders})
                      AND updated_at >= datetime('now', '-20 hours')
                    """,
                    params,
                ).fetchall()

            for scheme_code, nav_json in rows:
                if not nav_json:
                    continue
                try:
                    df = pd.read_json(io.StringIO(nav_json), orient="split")
                    df.index = pd.to_datetime(df.index)
                    cache[scheme_code] = df
                except Exception:
                    pass

        logger.info(
            "_bulk_preseed_nav_cache: preloaded %d/%d funds from cache",
            len(cache),
            len(codes),
        )
        return cache
    except Exception as e:
        logger.error("_bulk_preseed_nav_cache error: %s", e)
        return {}


# ────────────────────────────────────────────────────────────────────────────
#  Full Parallel MF Scan
# ────────────────────────────────────────────────────────────────────────────

# Thread-local NAV cache (populated once per session key)
_NAV_MEM_CACHE: Dict[str, pd.DataFrame] = {}


def _score_fund_fast(code: str, bench_default: pd.Series) -> Optional[Dict[str, Any]]:
    """Same as _score_fund but reads nav from the in-memory cache first."""
    global _NAV_MEM_CACHE
    try:
        # Use pre-seeded memory cache if available
        if code in _NAV_MEM_CACHE:
            history = _NAV_MEM_CACHE[code]
        else:
            history = fetch_nav_history(code)  # Neon → mfapi
            _NAV_MEM_CACHE[code] = history

        if history is None or history.empty:
            return None

        nav = float(history["nav"].iloc[-1])
        scheme_name = (
            _DISCOVERY_CACHE.get(code, f"Scheme {code}")
            if _DISCOVERY_CACHE
            else f"Scheme {code}"
        )
        bench_ticker = INDEX_BENCHMARKS.get("Nifty 50", "^NSEI")
        nm = scheme_name.lower()
        if "small cap" in nm or "smallcap" in nm:
            bench_ticker = INDEX_BENCHMARKS.get("Nifty Smallcap 250", "^CNXSC")
        elif "mid cap" in nm or "midcap" in nm:
            bench_ticker = INDEX_BENCHMARKS.get("Nifty Midcap 150", "^NSMIDCP")

        bench = (
            bench_default
            if bench_ticker == INDEX_BENCHMARKS.get("Nifty 50")
            else _get_benchmark_series(bench_ticker)
        )
        ret = history["ret"].dropna()

        alpha = beta = np.nan
        if not bench.empty and not ret.empty:
            combined = pd.concat([ret, bench], axis=1, join="inner").dropna()
            if len(combined) > 60:
                cov = np.cov(combined.iloc[:, 0], combined.iloc[:, 1])
                var = np.var(combined.iloc[:, 1])
                beta = cov[0, 1] / var if var else 1.0
                rp = combined.iloc[:, 0].mean() * 252
                rm = combined.iloc[:, 1].mean() * 252
                alpha = ((rp - 0.06) - beta * (rm - 0.06)) * 100

        n = len(history)
        nav_s = history["nav"]
        ret_1y = nav_s.pct_change(252).iloc[-1] * 100 if n > 252 else np.nan
        ret_3y = (
            ((nav_s.iloc[-1] / nav_s.iloc[-min(756, n)]) ** (252 / min(756, n)) - 1)
            * 100
            if n > 252
            else np.nan
        )
        ret_5y = (
            ((nav_s.iloc[-1] / nav_s.iloc[-min(1260, n)]) ** (252 / min(1260, n)) - 1)
            * 100
            if n > 252
            else np.nan
        )

        vol = ret.std() * np.sqrt(252) * 100
        downside = ret[ret < 0].std() * np.sqrt(252) * 100
        sharpe = ((ret.mean() * 252) - 0.06) / (ret.std() * np.sqrt(252) + 1e-9)
        sortino = ((ret.mean() * 252) - 0.06) / (
            ret[ret < 0].std() * np.sqrt(252) + 1e-9
        )
        roll_std = ret.rolling(21).std().mean() * np.sqrt(252) * 100

        primary_cat, sub_cat = classify_category(scheme_name)

        return {
            "Scheme Code": code,
            "Scheme": scheme_name,
            "NAV": nav,
            "Category": primary_cat,
            "Sub Category": sub_cat,
            "1Y Return": ret_1y,
            "3Y Return": ret_3y,
            "5Y Return": ret_5y,
            "Volatility": vol,
            "Downside Deviation": downside,
            "Sharpe": sharpe,
            "Sortino": sortino,
            "Rolling Std": roll_std,
            "Alpha": alpha,
            "Beta": beta,
            "Benchmark": bench_ticker,
        }
    except Exception as e:
        logger.debug("_score_fund_fast %s: %s", code, e)
        return None


def run_full_mf_scan(
    progress_callback=None,
    max_workers: int = 30,
    limit: Optional[int] = None,
) -> pd.DataFrame:
    """
    Full parallel MF scan with:
      - Bulk NAV pre-seed from Neon (single SELECT for all codes)
      - 30-worker ThreadPoolExecutor
      - Per-fund 10-second timeout guard
      - Automatic UPSERT to Neon at completion
    """
    global _NAV_MEM_CACHE
    codes = discover_all_funds(limit=limit)
    total = len(codes)
    logger.info("run_full_mf_scan: %d funds, %d workers", total, max_workers)

    # 1. Warm benchmarks first (blocking, but tiny — only 1-3 tickers)
    bench_default = _get_benchmark_series(INDEX_BENCHMARKS.get("Nifty 50", "^NSEI"))

    # 2. Bulk pre-seed NAV cache from Neon (ONE query for all funds)
    seeded = _bulk_preseed_nav_cache(codes)
    _NAV_MEM_CACHE.update(seeded)
    logger.info("Pre-seeded %d navs from Neon", len(seeded))

    rows: List[Dict[str, Any]] = []
    done = 0

    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = {pool.submit(_score_fund_fast, c, bench_default): c for c in codes}
        for future in as_completed(futures):
            done += 1
            try:
                result = future.result(timeout=10)
                if result:
                    rows.append(result)
            except Exception:
                pass
            if progress_callback:
                progress_callback(done, total)

    if not rows:
        return pd.DataFrame()

    df = pd.DataFrame(rows).fillna(0)

    # We already have Primary Cat and Sub Cat inside the dict, drop legacy assignment
    vol_penalty = (
        df["Volatility"] + df["Downside Deviation"] + df["Rolling Std"]
    ).clip(lower=0)
    raw = (df["Sharpe"] + df["Sortino"] - vol_penalty / 100).fillna(0)
    mn, mx = raw.min(), raw.max()
    df["Consistency Score"] = (
        50.0 if mx == mn else ((raw - mn) / (mx - mn) * 100).clip(0, 100)
    )

    # ── Conviction Enrichment (Decision Quality) ─────────────────────
    try:
        from utils.conviction_engine import enrich_mf_dataframe

        df = enrich_mf_dataframe(df)
        logger.info("run_full_mf_scan: enriched with conviction scores")
    except Exception as e:
        logger.error(f"Conviction enrichment failed: {e}")

    df = df.sort_values("Conviction Score", ascending=False).reset_index(drop=True)

    # Only a genuine, unlimited full-universe scan may overwrite the shared
    # monthly cache (mf_scan_results) that /api/mf-analysis checks before
    # deciding whether a fresh scan is even needed. upsert_mf_scan_results()
    # has no way to tell "this is the whole universe" apart from "this is a
    # `limit=N`/scheme_codes-targeted subset" — both just look like a normal
    # UPSERT keyed on (scheme_code, scan_date). Persisting a limited scan
    # here previously stamped today's date on only those few funds, which
    # then made /api/mf-analysis treat that partial result as a fresh
    # complete scan for up to max_age_days (31) — every other real fund
    # silently disappeared from the UI until the cache aged out or someone
    # noticed and force-refreshed. Confirmed live: a single `?limit=5` test
    # request left exactly 5 funds cached in production, masking the entire
    # rest of the universe on every subsequent page load.
    if limit is None:
        try:
            from utils.db import upsert_mf_scan_results

            upsert_mf_scan_results(df)
            logger.info("run_full_mf_scan: persisted %d funds", len(df))
        except Exception as e:
            logger.error("Neon persist failed: %s", e)
    else:
        logger.info(
            "run_full_mf_scan: limit=%d set, skipping mf_scan_results persist "
            "(a partial scan must never masquerade as a fresh full-universe cache)",
            limit,
        )

    return df


# ── Legacy aliases ────────────────────────────────────────────────────────────


def fetch_mf_snapshot(scheme_codes: List[str]) -> pd.DataFrame:
    bench = _get_benchmark_series(INDEX_BENCHMARKS.get("Nifty 50", "^NSEI"))
    rows = [r for c in scheme_codes if (r := _score_fund(str(c), bench)) is not None]
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows).fillna(0)
    vol_p = (df["Volatility"] + df["Downside Deviation"] + df["Rolling Std"]).clip(
        lower=0
    )
    raw = (df["Sharpe"] + df["Sortino"] - vol_p / 100).fillna(0)
    mn, mx = raw.min(), raw.max()
    df["Consistency Score"] = (
        50.0 if mx == mn else ((raw - mn) / (mx - mn) * 100).clip(0, 100)
    )
    return df.sort_values("Consistency Score", ascending=False).reset_index(drop=True)


_score_fund = _score_fund_fast  # alias
DEFAULT_SCHEMES = MF_SCHEMES


def detect_integrity_issues(fund_df, benchmark_df, category):
    """
    Core calculation engine for integrity metrics (Alpha, Beta, Sortino),
    drift detection, and data normalization.
    """
    from mf_lab.services.alerts import check_integrity_rules
    from mf_lab.services.metrics import calculate_metrics

    # Ensure date is the index for alignment in calculate_metrics
    if "date" in fund_df.columns:
        fund_df = fund_df.set_index("date")
    if "date" in benchmark_df.columns:
        benchmark_df = benchmark_df.set_index("date")

    metrics = calculate_metrics(fund_df, benchmark_df)
    if not metrics:
        return None

    label, severity, msg = check_integrity_rules(metrics, category)

    result = metrics.copy()
    result["drift"] = f"{label} {severity}"
    return result


# ═══════════════════════════════════════════════════════════════════════════════
#  Phase 5: Transparent MF Conviction Scoring (v2)
#  Added alongside existing Score/AI_Score — backward compatible.
# ═══════════════════════════════════════════════════════════════════════════════

_MF_CONVICTION_WEIGHTS = {
    "performance_consistency": 0.20,
    "alpha": 0.20,
    "downside_protection": 0.20,
    "volatility": 0.15,
    "momentum": 0.15,
    "efficiency": 0.10,
}


def _safe_float(val) -> Optional[float]:
    import math
    if val is None:
        return None
    try:
        f = float(val)
        return None if (math.isnan(f) or math.isinf(f)) else f
    except (TypeError, ValueError):
        return None


def _pct_rank_mf(value: Optional[float], peers: List[float], higher_is_better: bool = True) -> float:
    """Percentile rank within peer group (0-100). Returns 50 on insufficient data."""
    if value is None or not peers:
        return 50.0
    clean = [v for v in peers if v is not None]
    if len(clean) <= 1:
        return 50.0
    rank = sum(1 for p in clean if p <= value) / len(clean)
    score = rank * 100 if higher_is_better else (1 - rank) * 100
    return round(score, 1)


def compute_mf_conviction(fund_stats: dict, peer_stats: List[dict]) -> dict:
    """
    Compute a transparent, explainable conviction score for a mutual fund.

    Parameters
    ----------
    fund_stats  : dict with keys like Sharpe, Sortino, Alpha, Volatility,
                  Downside Deviation, 3M_Return, Expense Ratio, etc.
                  These are the same fields produced by _score_fund_fast().
    peer_stats  : list of similar dicts for peer funds in the same category.

    Returns
    -------
    dict with:
        conviction_score  — 0-100 composite
        confidence_score  — 0-100 (data completeness)
        sub_scores        — per-pillar breakdown
        risk_flags        — list of string flags
        data_quality      — "complete" | "partial" | "stale"
        score_version     — "v2"
    """
    risk_flags: List[str] = []
    sub_scores: Dict[str, float] = {}

    # ── Collect peer arrays ────────────────────────────────────────────────────
    def _peers(key: str) -> List[float]:
        return [_safe_float(p.get(key)) for p in peer_stats if p.get(key) is not None]

    sharpes = _peers("Sharpe")
    sortinos = _peers("Sortino")
    alphas = _peers("Alpha")
    vols = _peers("Volatility")
    dds = _peers("Downside Deviation")
    ret_3m = _peers("3M Return") or _peers("3M_Return")
    expense_ratios = _peers("Expense Ratio") or _peers("expense_ratio")

    # ── Single-fund universe guard ─────────────────────────────────────────────
    single_universe = len(peer_stats) <= 1
    if single_universe:
        risk_flags.append("single_fund_universe")

    # ── 1. Performance consistency — Sharpe + win-rate proxy ──────────────────
    sharpe = _safe_float(fund_stats.get("Sharpe"))
    sortino = _safe_float(fund_stats.get("Sortino"))
    if sharpe is None and sortino is None:
        sub_scores["performance_consistency"] = 50.0
        risk_flags.append("missing_sharpe")
    else:
        sharpe_rank = _pct_rank_mf(sharpe, sharpes)
        sortino_rank = _pct_rank_mf(sortino, sortinos)
        sub_scores["performance_consistency"] = round(
            (sharpe_rank * 0.5 + sortino_rank * 0.5) if sharpe is not None and sortino is not None
            else (sharpe_rank if sharpe is not None else sortino_rank),
            1,
        )

    # ── 2. Alpha vs benchmark ──────────────────────────────────────────────────
    alpha = _safe_float(fund_stats.get("Alpha"))
    if alpha is None:
        sub_scores["alpha"] = 50.0
        risk_flags.append("missing_alpha")
    else:
        sub_scores["alpha"] = _pct_rank_mf(alpha, alphas)
        if alpha < -3:
            risk_flags.append("negative_alpha")

    # ── 3. Downside protection — Sortino + Downside Deviation ─────────────────
    dd = _safe_float(fund_stats.get("Downside Deviation"))
    dd_rank = _pct_rank_mf(dd, dds, higher_is_better=False)  # lower = better
    sortino_rank2 = _pct_rank_mf(sortino, sortinos)
    sub_scores["downside_protection"] = round((dd_rank * 0.5 + sortino_rank2 * 0.5) if dd is not None else sortino_rank2, 1)

    # ── 4. Volatility — lower is better (inverted rank) ───────────────────────
    vol = _safe_float(fund_stats.get("Volatility"))
    if vol is None:
        sub_scores["volatility"] = 50.0
        risk_flags.append("missing_volatility")
    else:
        sub_scores["volatility"] = _pct_rank_mf(vol, vols, higher_is_better=False)
        if vol > 30:
            risk_flags.append("high_volatility")

    # ── 5. Momentum — 3m return rank ──────────────────────────────────────────
    ret3 = _safe_float(fund_stats.get("3M Return") or fund_stats.get("3M_Return"))
    sub_scores["momentum"] = _pct_rank_mf(ret3, ret_3m) if ret3 is not None else 50.0

    # ── 6. Efficiency — expense ratio (lower = better) ────────────────────────
    er = _safe_float(fund_stats.get("Expense Ratio") or fund_stats.get("expense_ratio"))
    if er is None:
        sub_scores["efficiency"] = 50.0
    else:
        sub_scores["efficiency"] = _pct_rank_mf(er, expense_ratios, higher_is_better=False)
        if er > 2.0:
            risk_flags.append("high_expense_ratio")

    # ── Weighted composite ─────────────────────────────────────────────────────
    raw_score = sum(
        sub_scores.get(k, 50) * w
        for k, w in _MF_CONVICTION_WEIGHTS.items()
    )
    conviction_score = max(0.0, min(100.0, round(raw_score, 1)))

    # ── Confidence — based on data completeness ────────────────────────────────
    key_fields = ["Sharpe", "Sortino", "Alpha", "Volatility", "Downside Deviation"]
    filled = sum(1 for f in key_fields if _safe_float(fund_stats.get(f)) is not None)
    confidence_score = round((filled / len(key_fields)) * 100)

    # Insufficient history check
    nav_pts = _safe_float(fund_stats.get("NAV Points") or fund_stats.get("nav_points"))
    if nav_pts is not None and nav_pts < 90:
        risk_flags.append("insufficient_history")
        confidence_score = max(confidence_score - 30, 10)

    # Data quality
    stale = "stale_data" in (fund_stats.get("risk_flags") or [])
    if stale:
        risk_flags.append("stale_data")
        confidence_score = max(0, confidence_score - 20)
        conviction_score = round(conviction_score * 0.85, 1)

    data_quality: str
    if len(risk_flags) == 0:
        data_quality = "complete"
    elif "stale_data" in risk_flags:
        data_quality = "stale"
    else:
        data_quality = "partial"

    return {
        "conviction_score": conviction_score,
        "confidence_score": confidence_score,
        "sub_scores": sub_scores,
        "risk_flags": list(set(risk_flags)),
        "data_quality": data_quality,
        "score_version": "v2",
    }


def enrich_mf_records_with_conviction(records: List[dict]) -> List[dict]:
    """
    Apply compute_mf_conviction() to each fund record in-place.
    Preserves all existing fields — only adds new v2 conviction fields.
    Safe for single-fund and empty universes.

    Also aliases the v1 conviction fields (already present on `r` from
    conviction_engine.score_mf_fund(), applied earlier in run_full_mf_scan())
    under unambiguous `_v1`-suffixed names: `conviction_score_v1`,
    `conviction_label_v1`, `conviction_emoji_v1`. This is purely additive —
    the original `Conviction Score`/`Conviction Label`/`Conviction Emoji`
    keys are untouched, for any existing consumer depending on them — but it
    gives a new consumer of the raw API an unambiguous way to ask for "the
    v1 score" without needing to know that `Conviction Score` (spaced,
    title-cased) means v1 while `conviction_score_v2` (snake_case) means v2.
    See MF_SCORING.md §2/§10: the API returning two different numbers under
    confusingly similar names was flagged as a trust hazard even after the
    frontend table's *display* mismatch was fixed — this doesn't consolidate
    the two scores (still an open question), it just makes both explicitly
    self-describing at the API layer too.
    """
    if not records:
        return records

    peer_stats = [r for r in records if r.get("Sharpe") is not None or r.get("sharpe") is not None]

    for r in records:
        r["conviction_score_v1"] = r.get("Conviction Score")
        r["conviction_label_v1"] = r.get("Conviction Label")
        r["conviction_emoji_v1"] = r.get("Conviction Emoji")

        try:
            result = compute_mf_conviction(r, peer_stats)
            r["conviction_score_v2"] = result["conviction_score"]
            r["confidence_score"] = result["confidence_score"]
            r["score_breakdown"] = result["sub_scores"]
            r["risk_flags_v2"] = result["risk_flags"]
            r["data_quality"] = result["data_quality"]
            r["score_version"] = result["score_version"]
        except Exception as exc:
            logger.warning("compute_mf_conviction failed for %s: %s", r.get("Scheme", "?"), exc)
            r["conviction_score_v2"] = None
            r["confidence_score"] = 0
            r["score_breakdown"] = {}
            r["risk_flags_v2"] = ["scoring_error"]
            r["data_quality"] = "partial"
            r["score_version"] = "v2"

    return records
