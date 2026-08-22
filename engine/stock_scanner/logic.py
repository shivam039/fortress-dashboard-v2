import logging
import time
from datetime import datetime
from functools import lru_cache

import numpy as np
import pandas as pd
import pandas_ta as ta
import yfinance as yf
from fortress_config import (
    NIFTY_SYMBOL,
    SECTOR_MAP,
    SECTOR_ROTATION_BONUS_POINTS,
    SMALLCAP_LIQUIDITY_MIN_CR,
    TOP_SECTOR_COUNT,
)

_logger = logging.getLogger("fortress.scanner")

# From development-db: Neon compatibility
try:
    import io
    import json
    from threading import Lock

    from utils.db import _read_df, upsert_ticker_metadata_cache
except ImportError:
    # Fallback for local testing or if utils.db structure differs
    def _read_df(*args, **kwargs):
        return pd.DataFrame()


_BENCHMARK_CACHE = {}

DEFAULT_SCORING_CONFIG = {
    "weights": {
        "technical": 0.50,
        "fundamental": 0.25,
        "sentiment": 0.15,
        "context": 0.10,
    },
    "liquidity_cr_min": 8.0,
    "market_cap_cr_min": 1500.0,
    "price_min": 80.0,
    "max_debt_to_equity": 2.0,
    "min_interest_coverage": 3.0,
    "enable_regime": True,
}

REGIME_LABELS = {
    "Strong Bull": "🟢🟢 Strong Bull",
    "Bull": "🟢 Bull",
    "Range": "🟡 Range",
    "Caution": "🟠 Caution",
    "Bear": "🔴 Bear",
}


def _safe_float(value, default=0.0):
    try:
        val = float(value)
        return default if pd.isna(val) else val
    except (TypeError, ValueError):
        return default


def _normalize_ohlcv_index(df):
    """Strip tz and truncate to calendar date so OHLCV frames from different
    providers (INDstocks' tz-aware IST index vs yfinance's, which varies by
    version/period) align correctly when concatenated together by date."""
    if df is None or df.empty or not isinstance(df.index, pd.DatetimeIndex):
        return df
    idx = df.index
    if idx.tz is not None:
        idx = idx.tz_localize(None)
    df = df.copy()
    df.index = idx.normalize()
    return df


@lru_cache(maxsize=32)
def get_stock_data(symbol, period="1y", interval="1d", group_by="column"):
    """Cached market data fetch.

    Provider priority (single-symbol calls):
        Bhav Copy (if it's the active preference and has data) → INDstocks/
        INDmoney (if configured) → yfinance — see market_data_provider.get_ohlcv.

    Provider priority (batch calls, ``group_by='ticker'``, ``symbol`` a
    tuple/list, daily interval):
        market_data_provider.get_batch_ohlcv's own tiering (Bhav Copy DB read
        first when preferred, then INDstocks for whatever it didn't cover),
        gap-filled per-symbol from yfinance for whatever neither tier
        could cover → yfinance grouped download for the whole batch (only if
        the gap-fill itself fails)

    Bhav Copy's local table has every NSE equity for every backfilled day, so
    once the backfill has caught up it should cover most/all of a batch with
    no network call at all. INDstocks' ``/market/historical`` endpoint also
    accepts multiple scrip codes per call and is tried next for whatever
    Bhav Copy didn't have (a symbol not yet backfilled, an index/derivative —
    the instruments cache has no index coverage, etc.). Only the symbols
    neither tier covered are fetched from yfinance and merged in — this
    function used to discard the entire batch and re-fetch everyone from
    yfinance on any partial miss, which meant paying for every provider on
    every single scan. If the yfinance gap-fill itself fails, this falls
    through to the full yfinance grouped download as a last resort.
    """
    is_batch = group_by == "ticker" or (hasattr(symbol, "__len__") and not isinstance(symbol, str))

    if not is_batch:
        # ── Single-symbol path: try INDstocks first ──────────────────────
        try:
            from utils.market_data_provider import get_ohlcv as _get_ohlcv
            df = _get_ohlcv(symbol, period=period)
            if df is not None and not df.empty:
                # Ensure interval filtering for intraday (not supported by INDstocks
                # daily endpoint — fall through to yfinance for intraday intervals)
                if interval == "1d":
                    return df
        except Exception as _exc:
            _logger.debug("market_data_provider.get_ohlcv failed for %s: %s", symbol, _exc)
    elif interval == "1d":
        # ── Batch path, daily interval: try the tiered market_data_provider
        # batch fetch (Bhav Copy first when it's the active preference, then
        # INDstocks for whatever it didn't cover — see
        # market_data_provider.get_batch_ohlcv). This function used to only
        # ever talk to INDstocks, and the log lines below said so explicitly
        # ("INDstocks batch OHLCV covered..."); now that a batch can be
        # served by either tier (or both), that label is misleading on its
        # own, so it's paired with a per-tier breakdown read from the
        # call-count counters (see get_ohlcv_source_call_counts) — diffed
        # before/after this one call so it reflects only this batch, not
        # everything served since process start.
        symbols = list(symbol) if not isinstance(symbol, str) else [symbol]
        try:
            from utils.market_data_provider import get_batch_ohlcv as _get_batch_ohlcv
            from utils.market_data_provider import (
                get_ohlcv_source_call_counts as _get_source_counts,
            )

            counts_before = _get_source_counts()
            batch = _get_batch_ohlcv(symbols, period=period)
            counts_after = _get_source_counts()
            tier_breakdown = {
                src: counts_after[src] - counts_before.get(src, 0)
                for src in counts_after
                if counts_after[src] - counts_before.get(src, 0) > 0
            }
            if batch and len(batch) == len(symbols):
                combined = pd.concat(
                    {sym: batch[sym] for sym in symbols}, axis=1
                )
                if not combined.empty:
                    _logger.debug(
                        "Batch OHLCV covered all %d symbols (by source: %s)",
                        len(symbols),
                        tier_breakdown,
                    )
                    return combined
            elif batch:
                missing = [s for s in symbols if s not in batch]
                _logger.info(
                    "Batch OHLCV covered %d/%d symbols (by source: %s); gap-filling "
                    "the remaining %d from yfinance instead of re-fetching the whole "
                    "batch: %s",
                    len(batch),
                    len(symbols),
                    tier_breakdown,
                    len(missing),
                    missing,
                )
                try:
                    yf_missing = yf.download(
                        missing,
                        period=period,
                        interval=interval,
                        group_by="ticker",
                        progress=False,
                        auto_adjust=False,
                    )
                    # INDstocks candles carry a tz-aware IST DatetimeIndex
                    # (see market_data_provider._candles_to_df); yfinance's
                    # index tz varies by version/period and often isn't the
                    # same tz object. Concatenating tz-mismatched
                    # DatetimeIndexes along axis=1 doesn't raise — it just
                    # silently fails to align same-calendar-day rows, so every
                    # gap-filled column would come back all-NaN. Normalize
                    # both sides to a plain date index before merging.
                    frames = {sym: _normalize_ohlcv_index(batch[sym]) for sym in batch}
                    if isinstance(yf_missing.columns, pd.MultiIndex):
                        covered_by_yf = set(yf_missing.columns.get_level_values(0))
                        for sym in missing:
                            if sym in covered_by_yf:
                                col = _normalize_ohlcv_index(yf_missing[sym].dropna(how="all"))
                                if col is not None and not col.empty:
                                    frames[sym] = col
                    elif len(missing) == 1 and not yf_missing.empty:
                        # yfinance drops the MultiIndex level when given a
                        # single-symbol list.
                        frames[missing[0]] = _normalize_ohlcv_index(yf_missing.dropna(how="all"))
                    if frames:
                        combined = pd.concat(frames, axis=1)
                        if not combined.empty:
                            _logger.info(
                                "Merged batch OHLCV: %d/%d symbols covered "
                                "(INDstocks + yfinance gap-fill)",
                                len(frames),
                                len(symbols),
                            )
                            # frames starts as exactly batch's own keys, so
                            # anything beyond that count came from this
                            # yfinance gap-fill — record only those symbols,
                            # not the ones already counted by get_batch_ohlcv.
                            from utils.market_data_provider import (
                                record_ohlcv_served as _record_served,
                            )

                            _record_served("yfinance", count=len(frames) - len(batch))
                            return combined
                except Exception as _exc:
                    _logger.warning(
                        "yfinance gap-fill for INDstocks-missing symbols failed: %s "
                        "— falling back to a full yfinance batch fetch",
                        _exc,
                    )
        except Exception as _exc:
            _logger.debug("market_data_provider.get_batch_ohlcv failed: %s", _exc)

    # ── Batch path OR intraday interval OR INDstocks miss → yfinance ─────
    for attempt in range(3):
        try:
            data = yf.download(
                symbol,
                period=period,
                interval=interval,
                group_by=group_by,
                progress=False,
                auto_adjust=False,
            )
            if isinstance(data.columns, pd.MultiIndex) and group_by == "column":
                data.columns = data.columns.get_level_values(0)
            if not data.empty:
                from utils.market_data_provider import (
                    record_ohlcv_served as _record_served,
                )

                # `symbols` (the normalized list) is only assigned inside the
                # interval == "1d" batch branch above — for an intraday batch
                # or the single-symbol path, fall back to `symbol` itself
                # (the original param: a tuple/list when is_batch, else a
                # bare string).
                _record_served(
                    "yfinance", count=len(symbol) if is_batch else 1
                )
                return data
        except Exception as e:
            _logger.warning(
                f"yfinance get_stock_data attempt {attempt+1}/3 failed for {symbol}: {e}"
            )
            if attempt < 2:
                time.sleep(2**attempt)  # 1s, then 2s
    _logger.error(f"yfinance get_stock_data exhausted retries for {symbol}")
    return pd.DataFrame()


@lru_cache(maxsize=32)
def _download_close_series(symbol, period="1y", interval="1d"):
    """Download close price series.

    Provider priority (daily interval only):
        INDstocks (if INDSTOCKS_TOKEN set)  →  yfinance

    Intraday intervals always use yfinance.
    """
    if interval == "1d":
        try:
            from utils.market_data_provider import get_ohlcv as _get_ohlcv
            df = _get_ohlcv(symbol, period=period)
            if df is not None and not df.empty and "Close" in df.columns:
                series = df["Close"].dropna()
                if not series.empty:
                    return series
        except Exception as _exc:
            _logger.debug("market_data_provider close series failed for %s: %s", symbol, _exc)

    # yfinance fallback
    for attempt in range(3):
        try:
            bench = yf.download(
                symbol,
                period=period,
                interval=interval,
                progress=False,
                auto_adjust=False,
            )
            if isinstance(bench.columns, pd.MultiIndex):
                bench.columns = bench.columns.get_level_values(0)
            series = bench.get("Close", pd.Series(dtype=float)).dropna()
            if not series.empty:
                return series
        except Exception as e:
            _logger.warning(
                f"yfinance _download_close_series attempt {attempt+1}/3 failed for {symbol}: {e}"
            )
            if attempt < 2:
                time.sleep(2**attempt)
    return pd.Series(dtype=float)


_INFO_CACHE = {}
_NEWS_CACHE = {}
_CAL_CACHE = {}
_EARN_CACHE = {}
_META_LOCK = Lock()


def _safe_df_to_dict(df):
    if df is None:
        return {}
    if isinstance(df, pd.DataFrame):
        try:
            # Convert datetime indexes or columns to string safely
            return json.loads(df.to_json(date_format="iso", orient="split"))
        except (TypeError, ValueError):
            return {}
    return {}


def _safe_dict_to_df(d):
    try:
        if d and isinstance(d, dict) and "columns" in d and "data" in d:
            df = pd.read_json(io.StringIO(json.dumps(d)), orient="split")
            return df
    except (TypeError, ValueError):
        pass
    return None


def prefetch_metadata(symbols, max_age_hours=12):
    """Bulk-preload fundamental/news/calendar/earnings metadata for a whole
    scan's worth of tickers from the DB cache in one call, before the
    per-ticker scoring loop runs.

    Fundamental (market cap, debt-to-equity), sentiment (news), and context
    (earnings calendar) — 50% of the conviction score's weight combined —
    have no INDstocks/IndMoney equivalent; INDstocks' documented endpoints
    only cover quotes, historical candles, instruments, and option chains,
    not company financials or news. That data comes from yfinance regardless
    of which provider serves OHLCV, and always will unless a different
    fundamentals/news source is added.

    What *is* fixable is that every `/api/scan` run was calling yfinance
    live for `.info`/`.news`/`.calendar`/`.earnings_dates` — 4 requests per
    ticker — for every single ticker, every single time, with no cross-run
    caching and (see `_ensure_metadata_loaded`) a silent blank-on-failure
    fallback if any of those 4 calls got rate-limited. A DB-backed cache
    (`ticker_metadata` table, `bulk_fetch_metadata()`/
    `upsert_ticker_metadata_cache()` in `utils/db.py`) already existed for
    exactly this — but it was only ever wired into the legacy Streamlit UI's
    scan loop (`stock_scanner/ui.py::_run_scan_fragment`), never into this
    FastAPI-facing `logic.py`, so `/api/scan` and `/api/sector-pulse` (the
    Next.js app's actual scan paths) never benefited from it.

    Call this once with the full ticker list before scoring a batch. Tickers
    with a cache entry newer than `max_age_hours` are pre-filled into the
    in-memory caches, so `_ensure_metadata_loaded` skips its live yfinance
    call entirely for them; everything else still fetches live as before.

    Args:
        symbols: Tickers about to be scanned.
        max_age_hours: Maximum cache age to accept (matches the legacy UI's
            default of 12h — fundamentals/news/earnings-calendar dates don't
            meaningfully change within a trading day).
    """
    symbols = list(symbols)
    if not symbols:
        return

    try:
        from utils.db import bulk_fetch_metadata
    except ImportError:
        return

    try:
        cached = bulk_fetch_metadata(symbols, max_age_hours=max_age_hours)
    except Exception as exc:
        _logger.warning("prefetch_metadata: bulk_fetch_metadata failed: %s", exc)
        return

    if not cached:
        return

    with _META_LOCK:
        for sym, row in cached.items():
            _INFO_CACHE[sym] = row.get("info_json") or {}
            news = row.get("news_json")
            _NEWS_CACHE[sym] = news if isinstance(news, list) else []
            _CAL_CACHE[sym] = _safe_dict_to_df(row.get("cal_json"))
            _EARN_CACHE[sym] = _safe_dict_to_df(row.get("earn_json"))

    _logger.info(
        "prefetch_metadata: pre-filled %d/%d symbols from DB cache (skips live "
        "yfinance metadata calls for those)",
        len(cached),
        len(symbols),
    )


def _ensure_metadata_loaded(symbol):
    with _META_LOCK:
        if symbol in _INFO_CACHE:
            return

    try:
        tkr = yf.Ticker(symbol)
        info = tkr.info or {}
        news = tkr.news or []
        cal = tkr.calendar
        earn = tkr.earnings_dates

        # Save to memory cache immediately (thread safe)
        cal_df = cal if isinstance(cal, pd.DataFrame) else None
        earn_df = earn if isinstance(earn, pd.DataFrame) else None

        with _META_LOCK:
            _INFO_CACHE[symbol] = info
            _NEWS_CACHE[symbol] = news
            _CAL_CACHE[symbol] = cal_df
            _EARN_CACHE[symbol] = earn_df

        # Persist so the next scan's prefetch_metadata() can skip this ticker.
        cal_dict = _safe_df_to_dict(cal_df)
        earn_dict = _safe_df_to_dict(earn_df)

        upsert_ticker_metadata_cache(
            symbol,
            {
                "info_json": info,
                "news_json": news,
                "cal_json": cal_dict,
                "earn_json": earn_dict,
            },
        )
    except Exception as exc:
        # Previously silent: any yfinance failure here (rate limit, network
        # error, symbol delisted, etc.) permanently cached a blank entry for
        # the rest of this process's uptime with zero visibility — quietly
        # zeroing out 50% of that ticker's conviction score (fundamental +
        # sentiment + context) with no trace in the logs. Log it so a run of
        # bad scores is at least diagnosable.
        _logger.warning(
            "_ensure_metadata_loaded: yfinance metadata fetch failed for %s: %s "
            "(fundamental/sentiment/context scores for this ticker will use "
            "empty/default values)",
            symbol,
            exc,
        )
        with _META_LOCK:
            _INFO_CACHE[symbol] = {}
            _NEWS_CACHE[symbol] = []
            _CAL_CACHE[symbol] = None
            _EARN_CACHE[symbol] = None


def _get_ticker_info(symbol):
    _ensure_metadata_loaded(symbol)
    return _INFO_CACHE.get(symbol, {})


def _get_ticker_news(symbol):
    _ensure_metadata_loaded(symbol)
    return _NEWS_CACHE.get(symbol, [])


def _get_ticker_calendar(symbol):
    _ensure_metadata_loaded(symbol)
    return _CAL_CACHE.get(symbol, None)


def _get_ticker_earnings_dates(symbol):
    _ensure_metadata_loaded(symbol)
    return _EARN_CACHE.get(symbol, None)


def _get_benchmark_series(symbol):
    cached = _BENCHMARK_CACHE.get(symbol)
    if cached is not None and len(cached) > 0:
        return cached

    try:
        close = _download_close_series(symbol)
        _BENCHMARK_CACHE[symbol] = close
        return close
    except Exception as e:
        _logger.warning(f"_get_benchmark_series failed for {symbol}: {e}")
        return pd.Series(dtype=float)


def _return_ratio(series, periods):
    if len(series) <= periods:
        return 1.0
    base = _safe_float(series.iloc[-(periods + 1)], default=0.0)
    now = _safe_float(series.iloc[-1], default=0.0)
    if base <= 0:
        return 1.0
    return now / base


def _safe_info_float(info, key, default=0.0):
    if not isinstance(info, dict):
        return default
    return _safe_float(info.get(key, default), default=default)


def _extract_sector(symbol):
    return SECTOR_MAP.get(symbol, "General")


def _compute_sector_rotation_bonus(df):
    if df is None or df.empty or "Sector" not in df.columns:
        return pd.Series(0.0, index=df.index if df is not None else pd.Index([]))

    sector_ret = pd.to_numeric(df.get("Ret_90D", np.nan), errors="coerce")
    sector_perf = (
        pd.DataFrame({"Sector": df["Sector"], "Ret_90D": sector_ret})
        .dropna(subset=["Sector"])
        .groupby("Sector", as_index=False)["Ret_90D"]
        .mean()
        .sort_values("Ret_90D", ascending=False)
    )
    top_sectors = set(sector_perf.head(TOP_SECTOR_COUNT)["Sector"].tolist())
    return df["Sector"].isin(top_sectors).astype(float) * float(
        SECTOR_ROTATION_BONUS_POINTS
    )


def _normalize_series(series):
    numeric = pd.to_numeric(series, errors="coerce")
    if numeric.dropna().empty:
        return pd.Series(50.0, index=series.index)
    q1 = numeric.quantile(0.25)
    q3 = numeric.quantile(0.75)
    iqr = q3 - q1
    if iqr > 0:
        low = q1 - 1.5 * iqr
        high = q3 + 1.5 * iqr
        clipped = numeric.clip(lower=low, upper=high)
    else:
        clipped = numeric
    min_v = clipped.min()
    max_v = clipped.max()
    if pd.isna(min_v) or pd.isna(max_v):
        return pd.Series(50.0, index=series.index)
    if max_v == min_v:
        return series.clip(lower=0, upper=100).fillna(50.0)
    return ((clipped - min_v) / (max_v - min_v) * 100).fillna(50.0)


def calculate_ai_score(df, min_floor=18.0):
    """Calculate Fortress AI Score (0-100) using momentum, volume, volatility, and sector context."""
    if df is None or df.empty:
        return pd.Series(dtype=float)

    work_df = df

    def _series_or_default(column, default):
        value = work_df.get(column, None)
        if isinstance(value, pd.Series):
            return pd.to_numeric(value, errors="coerce").fillna(default)
        return pd.Series(default, index=work_df.index, dtype=float)

    rsi = pd.to_numeric(work_df.get("RSI", np.nan), errors="coerce")
    rs_score = _series_or_default("RS_Score", 0)
    ret_30 = _series_or_default("Ret_30D", 0)
    ret_90 = _series_or_default("Ret_90D", 0)
    rs_comp = _series_or_default("RS_Composite", 1.0)
    dist_52w = _series_or_default("Dist_52W_High_Pct", 25)
    vol_ratio = _series_or_default("Vol_Surge_Ratio", 1.0)
    value_cr = _series_or_default("Avg_Value_20D_Cr", 0)
    extension = _series_or_default("Extension_Pct", 0)
    sector_z = _series_or_default("Sector_Conviction_Z", 0)
    coiling = work_df.get("Is_Coiling", False).astype(float)

    # Momentum block (heavier weight): trend quality + price change + 52W strength
    rsi_quality = (100 - (rsi - 58).abs() * 2.2).clip(lower=0, upper=100).fillna(45)
    rs_comp_score = ((rs_comp - 0.85) / 0.5 * 100).clip(lower=0, upper=100)
    rs_score_norm = ((rs_score + 12) / 24 * 100).clip(lower=0, upper=100)
    price_change_score = ((ret_30 * 0.6 + ret_90 * 0.4 + 20) / 50 * 100).clip(
        lower=0, upper=100
    )
    high_proximity = (100 - dist_52w * 2.2).clip(lower=0, upper=100)
    momentum_score = (
        rsi_quality * 0.25
        + rs_comp_score * 0.25
        + rs_score_norm * 0.20
        + price_change_score * 0.20
        + high_proximity * 0.10
    )

    # Volume block: participation + liquidity
    vol_ratio_score = ((vol_ratio - 0.7) / 1.3 * 100).clip(lower=0, upper=100)
    liquidity_score = np.log1p(value_cr).replace([np.inf, -np.inf], np.nan).fillna(0)
    liquidity_score = (liquidity_score / max(np.log1p(150), 1e-6) * 100).clip(
        lower=0, upper=100
    )
    volume_score = (vol_ratio_score * 0.7) + (liquidity_score * 0.3)

    # Volatility block: reward constructive contraction, penalize over-extension
    extension_penalty = (extension.abs() * 2.8).clip(lower=0, upper=70)
    volatility_score = (70 - extension_penalty + (coiling * 20)).clip(
        lower=0, upper=100
    )

    # Sector relative block
    sector_score = ((sector_z + 2.0) / 4.0 * 100).clip(lower=0, upper=100)

    ai_score = (
        momentum_score * 0.45
        + volume_score * 0.25
        + volatility_score * 0.15
        + sector_score * 0.15
    ).clip(lower=0, upper=100)

    pass_mask = work_df.get("Quality_Gate_Pass", True).astype(bool) & ~work_df.get(
        "Avoid_Flag", False
    ).astype(bool)
    ai_score = pd.Series(ai_score, index=work_df.index).where(
        ~pass_mask, ai_score.clip(lower=min_floor)
    )
    return ai_score.round(1)


def _normalize_weight_map(weight_map):
    merged = {
        "technical": _safe_float(
            weight_map.get("technical", DEFAULT_SCORING_CONFIG["weights"]["technical"]),
            0.0,
        ),
        "fundamental": _safe_float(
            weight_map.get(
                "fundamental", DEFAULT_SCORING_CONFIG["weights"]["fundamental"]
            ),
            0.0,
        ),
        "sentiment": _safe_float(
            weight_map.get("sentiment", DEFAULT_SCORING_CONFIG["weights"]["sentiment"]),
            0.0,
        ),
        "context": _safe_float(
            weight_map.get("context", DEFAULT_SCORING_CONFIG["weights"]["context"]), 0.0
        ),
    }
    total = sum(max(v, 0.0) for v in merged.values())
    if total <= 0:
        return DEFAULT_SCORING_CONFIG["weights"].copy()
    return {k: max(v, 0.0) / total for k, v in merged.items()}


def _get_default_regime():
    return {"Market_Regime": "Range", "Regime_Multiplier": 1.00, "VIX": 20.0}


def _apply_quality_gates(df, cfg):
    market_cap_col = "Market_Cap_Cr" if "Market_Cap_Cr" in df.columns else None
    debt_col = "Debt_To_Equity" if "Debt_To_Equity" in df.columns else None
    gate_conditions = {
        # Strict less-than: a stock at exactly the threshold should PASS, not FAIL
        f"Liquidity<{cfg['liquidity_cr_min']}Cr": pd.to_numeric(
            df.get("Avg_Value_20D_Cr", np.nan), errors="coerce"
        )
        < cfg["liquidity_cr_min"],
        f"Price<{cfg['price_min']}": pd.to_numeric(
            df.get("Price", np.nan), errors="coerce"
        )
        < cfg["price_min"],
    }
    if market_cap_col:
        market_cap = pd.to_numeric(df.get(market_cap_col), errors="coerce")
        gate_conditions[f"MCap<{cfg['market_cap_cr_min']}Cr"] = market_cap.gt(
            0
        ) & market_cap.lt(cfg["market_cap_cr_min"])
    if debt_col:
        gate_conditions[f"Debt/Equity>{cfg['max_debt_to_equity']}"] = (
            pd.to_numeric(df.get(debt_col), errors="coerce") > cfg["max_debt_to_equity"]
        )

    # Fix: Ensure Liquidity_Flag is treated as Series and handle missing values safely
    if "Liquidity_Flag" in df.columns:
        gate_conditions["LowLiquidityFlag"] = (
            df["Liquidity_Flag"].fillna("").astype(str).eq("Low Liquidity - Avoid")
        )
    else:
        gate_conditions["LowLiquidityFlag"] = pd.Series(False, index=df.index)

    gate_frame = pd.DataFrame(
        {
            k: (
                v.fillna(False)
                if isinstance(v, pd.Series)
                else pd.Series(v, index=df.index).fillna(False)
            )
            for k, v in gate_conditions.items()
        },
        index=df.index,
    )
    df["Quality_Gate_Pass"] = ~gate_frame.any(axis=1)
    df["Quality_Gate_Failures"] = gate_frame.apply(
        lambda row: "|".join(row.index[row.values]), axis=1
    )
    return df


def _resolve_conviction_score(conviction, base_score_estimate, score_mod=0):
    """
    Combine the raw trend conviction with the fallback estimate.

    The fallback only fills cases where the trend path produced no score yet.
    Risk penalties are preserved in that fallback path via score_mod.
    """
    if conviction <= 0:
        conviction = min(100, round(base_score_estimate + score_mod, 2))
    return max(0, min(100, conviction))


def apply_advanced_scoring(df, scoring_config=None):
    # From main: clean scoring logic without inline duplication
    if df is None or df.empty:
        return df

    cfg = DEFAULT_SCORING_CONFIG.copy()
    if scoring_config:
        cfg.update({k: v for k, v in scoring_config.items() if k != "weights"})
        if "weights" in scoring_config:
            cfg["weights"] = _normalize_weight_map(scoring_config["weights"])
    else:
        cfg["weights"] = _normalize_weight_map(cfg["weights"])

    # Optimized: Avoid unnecessary copy if safe
    # df = df.copy()

    sector_rotation_bonus = _compute_sector_rotation_bonus(df)
    df["Sector_Rotation_Bonus"] = sector_rotation_bonus.round(2)
    df["Context_Raw"] = (
        pd.to_numeric(df.get("Context_Raw", 0), errors="coerce").fillna(0)
        + df["Sector_Rotation_Bonus"]
    )

    # Sector-relative scoring: normalize RSI and conviction by sector before blending into Context_Raw.
    if "Sector" in df.columns:
        rsi_raw = pd.to_numeric(df.get("RSI", np.nan), errors="coerce")
        conviction_raw = pd.to_numeric(df.get("Score", np.nan), errors="coerce")

        def _sector_zscore(series):
            std = series.std(ddof=0)
            if std is None or std == 0 or pd.isna(std):
                return pd.Series(0.0, index=series.index)
            return (series - series.mean()) / std

        rsi_z = rsi_raw.groupby(df["Sector"]).transform(_sector_zscore).fillna(0.0)
        conviction_z = (
            conviction_raw.groupby(df["Sector"]).transform(_sector_zscore).fillna(0.0)
        )
        df["Sector_RSI_Z"] = rsi_z.round(3)
        df["Sector_Conviction_Z"] = conviction_z.round(3)
        # Clip z-scores to ±2σ to prevent outliers from distorting cross-sector ranking
        df["Context_Raw"] += (rsi_z.clip(-2, 2) + conviction_z.clip(-2, 2)) * 5.0

    # Normalize category sub-scores within scan universe
    df["Technical_Score"] = _normalize_series(df.get("Technical_Raw", 50)).round(2)
    df["Fundamental_Score"] = _normalize_series(df.get("Fundamental_Raw", 50)).round(2)
    df["Sentiment_Score"] = _normalize_series(df.get("Sentiment_Raw", 50)).round(2)
    df["Context_Score"] = _normalize_series(df.get("Context_Raw", 50)).round(2)

    # RSI influence flows through technical_raw → Technical_Score normalization.
    # Post-normalization RSI bonus removed to prevent double-counting with check_institutional_fortress.

    # RS ranking and top quartile bonus
    rs_base = pd.to_numeric(
        df.get("RS_6M", df.get("RS_Composite", np.nan)), errors="coerce"
    )
    df["RS_Rank"] = (rs_base.rank(method="average", pct=True) * 100).fillna(50)
    rs_gate = (pd.to_numeric(df.get("RS_Composite", 0), errors="coerce") > 1.0) | (
        df["RS_Rank"] >= 75
    )
    df.loc[rs_gate.fillna(False), "Context_Score"] = (
        df.loc[rs_gate.fillna(False), "Context_Score"] + 20
    ).clip(upper=100)

    # Regime handling
    regime = (
        cfg.get("regime", _get_default_regime())
        if cfg.get("enable_regime", True)
        else _get_default_regime()
    )
    df["Market_Regime"] = regime["Market_Regime"]
    df["Regime"] = regime["Market_Regime"]
    df["Regime_Multiplier"] = regime["Regime_Multiplier"]
    df["Regime_Tag"] = REGIME_LABELS.get(
        regime["Market_Regime"], f"🟡 {regime['Market_Regime']}"
    )
    df["India_VIX"] = round(regime["VIX"], 2)

    w = cfg["weights"]
    df["Weight_Technical"] = round(w["technical"] * 100, 2)
    df["Weight_Fundamental"] = round(w["fundamental"] * 100, 2)
    df["Weight_Sentiment"] = round(w["sentiment"] * 100, 2)
    df["Weight_Context"] = round(w["context"] * 100, 2)
    df["Technical_Score"] = (
        _normalize_series(df.get("Technical_Raw", 50)).fillna(50.0).round(2)
    )
    df["Fundamental_Score"] = (
        _normalize_series(df.get("Fundamental_Raw", 50)).fillna(50.0).round(2)
    )
    df["Sentiment_Score"] = (
        _normalize_series(df.get("Sentiment_Raw", 50)).fillna(50.0).round(2)
    )
    df["Context_Score"] = (
        _normalize_series(df.get("Context_Raw", 50)).fillna(50.0).round(2)
    )

    df["Score_Pre_Regime"] = (
        df["Technical_Score"] * w.get("technical", 0.5)
        + df["Fundamental_Score"] * w.get("fundamental", 0.25)
        + df["Sentiment_Score"] * w.get("sentiment", 0.15)
        + df["Context_Score"] * w.get("context", 0.1)
    ).fillna(50.0)

    df["sub_scores"] = df.apply(
        lambda row: {
            "technical": round(_safe_float(row.get("Technical_Score")), 2),
            "fundamental": round(_safe_float(row.get("Fundamental_Score")), 2),
            "sentiment": round(_safe_float(row.get("Sentiment_Score")), 2),
            "context": round(_safe_float(row.get("Context_Score")), 2),
        },
        axis=1,
    )
    df["Score"] = (
        (df["Score_Pre_Regime"] * df["Regime_Multiplier"])
        .clip(lower=0, upper=100)
        .round(2)
    )

    df = _apply_quality_gates(df, cfg)
    fail_mask = ~df["Quality_Gate_Pass"]
    df.loc[fail_mask, "Score"] = (df.loc[fail_mask, "Score"] - 1000).clip(lower=0)

    avoid_mask = (df.get("Black_Swan_Flag", 0).astype(float) > 0) | (
        df.get("News") == "🚨 BLACK SWAN"
    )
    df.loc[avoid_mask.fillna(False), "Score"] = (
        df.loc[avoid_mask.fillna(False), "Score"] - 50
    ).clip(lower=0)
    df["Avoid_Flag"] = avoid_mask.fillna(False)

    # Keep verdict semantics backward-compatible
    df["Verdict"] = df["Score"].apply(
        lambda x: "🔥 HIGH" if x >= 85 else "🚀 PASS" if x >= 60 else "🟡 WATCH"
    )
    df.loc[fail_mask, "Verdict"] = "❌ FAIL"
    df.loc[df["Avoid_Flag"], "Verdict"] = "🚨 AVOID"

    # Backward-compatible aliases + transparency columns requested by desk users.
    df["Tech_Score"] = df["Technical_Score"]
    df["Fund_Score"] = df["Fundamental_Score"]
    df["Sent_Score"] = df["Sentiment_Score"]
    df["Context_Score"] = df["Context_Score"]
    df["ai_score"] = calculate_ai_score(df)

    if "Score" in df.columns and "ai_score" in df.columns:
        score_idx = df.columns.get_loc("Score")
        cols = list(df.columns)
        ai_col = cols.pop(cols.index("ai_score"))
        cols.insert(score_idx + 1, ai_col)
        df = df[cols]
    return df


def check_institutional_fortress(
    ticker,
    data,
    ticker_obj,
    portfolio_value,
    risk_per_trade,
    selected_universe=None,
    regime_data=None,
):
    try:
        if isinstance(data.columns, pd.MultiIndex):
            data.columns = data.columns.get_level_values(0)
        if len(data) < 210:
            return None

        close, high, low, open_price = (
            data["Close"],
            data["High"],
            data["Low"],
            data["Open"],
        )
        volume = data.get("Volume", pd.Series(0, index=data.index, dtype=float)).fillna(
            0
        )

        # Immediate Liquidity Guard
        price = _safe_float(close.iloc[-1])
        avg_volume_20 = _safe_float(volume.tail(20).mean())
        avg_value_20d_cr = (avg_volume_20 * price) / 1e7 if price > 0 else 0.0
        if (
            selected_universe == "Nifty Smallcap 250"
            and avg_value_20d_cr < SMALLCAP_LIQUIDITY_MIN_CR
        ):
            return None

        ema200 = _safe_float(ta.ema(close, 200).iloc[-1])
        ema50 = _safe_float(ta.ema(close, 50).iloc[-1])
        ema20 = _safe_float(ta.ema(close, 20).iloc[-1])
        rsi = _safe_float(ta.rsi(close, 14).iloc[-1])
        atr = _safe_float(ta.atr(high, low, close, 14).iloc[-1])
        atr100 = _safe_float(ta.atr(high, low, close, 100).iloc[-1])
        st_df = ta.supertrend(high, low, close, 10, 3)

        # ADX Calculation
        try:
            adx_df = ta.adx(high, low, close, 14)
            adx_col = [c for c in adx_df.columns if c.startswith("ADX_")][0]
            adx_val = _safe_float(adx_df[adx_col].iloc[-1])
        except Exception as e:
            _logger.debug(f"{ticker} ADX computation skipped: {e}")
            adx_val = 0.0

        # 52-Week High Calculation
        high_52w = _safe_float(high.tail(252).max()) if len(high) >= 200 else price
        distance_to_high_pct = ((high_52w - price) / price) * 100 if price > 0 else 0.0
        trend_col = [c for c in st_df.columns if c.startswith("SUPERTd")][0]
        trend_dir = int(_safe_float(st_df[trend_col].iloc[-1]))
        # price already defined above
        prev_close = _safe_float(close.iloc[-2])
        curr_open = _safe_float(open_price.iloc[-1])
        curr_low = _safe_float(low.iloc[-1])
        current_volume = _safe_float(volume.iloc[-1])
        # avg_volume_20 already defined above
        # avg_value_20d_cr already defined above

        vol_surge_ratio = (current_volume / avg_volume_20) if avg_volume_20 > 0 else 0.0
        vol_surge = vol_surge_ratio > 1.5

        weekly_close = (
            close.resample("W-FRI").last().dropna()
            if isinstance(close.index, pd.DatetimeIndex)
            else pd.Series(dtype=float)
        )
        weekly_ema30 = (
            _safe_float(ta.ema(weekly_close, 30).iloc[-1])
            if len(weekly_close) >= 30
            else 0.0
        )

        tech_base = price > ema200 and trend_dir == 1
        perfect_alignment = (
            price > ema20 and ema20 > ema50 and ema50 > ema200 and trend_dir == 1
        )
        mtf_aligned = price > weekly_ema30 if weekly_ema30 > 0 else False

        regime = regime_data if regime_data else _get_default_regime()
        regime_multiplier = float(regime.get("Regime_Multiplier", 1.0))
        # Adaptive: tighter stops in Bull, wider in Bear to avoid shakeouts
        adaptive_mult = np.clip(regime_multiplier, 0.7, 1.3)
        sl_distance = atr * (1.5 / adaptive_mult)
        sl_price = round(price - sl_distance, 2)
        target_10d = round(price + atr * 1.8, 2)
        risk_amount = portfolio_value * risk_per_trade
        pos_size = int(risk_amount / sl_distance) if sl_distance > 0 else 0

        conviction = 0
        score_mod = 0
        news_sentiment = "Neutral"
        event_status = "✅ Safe"
        black_swan_flag = 0

        # --- Resilience & Gap Logic ---
        # War/News Resilience
        drop = prev_close - curr_low
        resilience_label = "✅ Safe"
        if drop > (2.0 * atr):
            if price > ema200:
                resilience_label = "🛡️ HOLD (Shakeout)"
            else:
                resilience_label = "💀 FAIL (Breakdown)"
                score_mod -= 40  # Automatic penalty

        # Gap Integrity
        gap_integrity = "N/A"
        if curr_open < prev_close:
            gap_size = prev_close - curr_open
            # "Integral" if Open > EMA200 AND gap < 1.5 ATR
            if curr_open > ema200 and gap_size < (1.5 * atr):
                gap_integrity = "✅ Integral"
            else:
                gap_integrity = "⚠️ Gap Risk"

        try:
            # Optimized: Use cached news fetch
            news = _get_ticker_news(ticker) or []
            _BLACK_SWAN_TERMS = {
                "fraud",
                "investigation",
                "default",
                "bankruptcy",
                "scam",
                "class action",
                "sebi notice",
                "ed raid",
                "fir filed",
                "money laundering",
            }
            _FALSE_POSITIVE_GUARDS = {
                "victory",
                "compliance",
                "cleared",
                "acquit",
                "legal win",
                "no wrongdoing",
            }
            combined_text = " ".join(
                f"{n.get('title', '')} {n.get('summary', '')}".lower()
                for n in news[:10]
            )
            if any(k in combined_text for k in _BLACK_SWAN_TERMS) and not any(
                fp in combined_text for fp in _FALSE_POSITIVE_GUARDS
            ):
                news_sentiment = "🚨 BLACK SWAN"
                score_mod -= 40
                black_swan_flag = 1
        except Exception as e:
            _logger.debug(f"{ticker} news/black-swan check: {e}")
        try:
            # Optimized: Use cached calendar fetch
            cal = _get_ticker_calendar(ticker)
            if isinstance(cal, pd.DataFrame) and not cal.empty:
                next_date = pd.to_datetime(cal.iloc[0, 0]).date()
                days_to = (next_date - datetime.now().date()).days
                if 0 <= days_to <= 7:
                    event_status = f"🚨 EARNINGS ({next_date.strftime('%d-%b')})"
                    score_mod -= 20
        except Exception as e:
            _logger.debug(f"{ticker} calendar/earnings-risk check: {e}")

        analyst_count = None
        target_high = None
        target_low = None
        target_median = None
        target_mean = None
        market_cap_cr = debt_to_equity = interest_coverage = 0.0
        earnings_ts = None
        earnings_surprise = 0.0
        negative_earnings_surprise = False
        try:
            # Optimized: Use cached info fetch
            info = _get_ticker_info(ticker) or {}
            analyst_count = info.get("numberOfAnalystOpinions")
            target_high = info.get("targetHighPrice")
            target_low = info.get("targetLowPrice")
            target_median = info.get("targetMedianPrice")
            target_mean = info.get("targetMeanPrice")
            market_cap_cr = _safe_info_float(info, "marketCap", 0.0) / 1e7
            debt_to_equity = _safe_info_float(info, "debtToEquity", 0.0)
            interest_coverage = _safe_info_float(info, "interestCoverage", 0.0)
        except Exception as e:
            _logger.debug(f"{ticker} analyst/info fetch: {e}")

        try:
            # Optimized: Use cached earnings fetch
            earnings = _get_ticker_earnings_dates(ticker)
            if isinstance(earnings, pd.DataFrame) and not earnings.empty:
                latest = earnings.sort_index(ascending=False).iloc[0]
                earnings_ts = earnings.sort_index(ascending=False).index[0]
                earnings_surprise = _safe_float(
                    latest.get("Surprise(%)", 0.0), default=0.0
                )
                negative_earnings_surprise = earnings_surprise < 0
        except Exception as e:
            _logger.debug(f"{ticker} earnings dates fetch: {e}")

        if tech_base:
            conviction += 50
            if perfect_alignment:
                conviction += 15  # True alignment reward

            # ADX trend strength: tiered to capture emerging → confirmed trend
            if adx_val >= 30:
                conviction += 15  # Strong confirmed trend
            elif adx_val >= 25:
                conviction += 12  # Trend building
            elif adx_val >= 20:
                conviction += 5  # Emerging trend (previously a dead zone)
            elif adx_val > 0:
                conviction -= 15  # Choppy / trendless market

            # 52-week distance: 3-tier to distinguish breakout vs consolidation vs resistance
            if distance_to_high_pct < 5:
                conviction += 15  # Near ATH — breakout zone
            elif distance_to_high_pct < 15:
                conviction += 8  # Healthy consolidation within striking range
            elif distance_to_high_pct > 35:
                conviction -= 10  # Heavy overhead resistance

        # Relative Strength vs Nifty 50
        benchmark_close = _get_benchmark_series(NIFTY_SYMBOL)
        rs_score = 0.0
        try:
            stock_ret_30d = (
                ((price / _safe_float(close.iloc[-31], default=price)) - 1) * 100
                if len(close) > 30
                else 0.0
            )
            nifty_ret_30d = 0.0
            if len(benchmark_close) > 30:
                bench_now = _safe_float(benchmark_close.iloc[-1])
                bench_30 = _safe_float(benchmark_close.iloc[-31], default=bench_now)
                nifty_ret_30d = (
                    ((bench_now / bench_30) - 1) * 100 if bench_30 > 0 else 0.0
                )
            rs_score = stock_ret_30d - nifty_ret_30d
        except (IndexError, TypeError, ValueError, KeyError):
            rs_score = 0.0

        # Tiered RS conviction: magnitude of outperformance matters
        if rs_score > 5:
            conviction += 18  # Strong outperformer vs Nifty
        elif rs_score > 0:
            conviction += 8  # Mild outperformer
        elif rs_score < -3:
            conviction -= 10  # Meaningful underperformer

        # Multi-horizon RS — reuse benchmark_close already fetched above
        rs_3m = _return_ratio(close, 63) / max(_return_ratio(benchmark_close, 63), 1e-6)
        rs_6m = _return_ratio(close, 126) / max(
            _return_ratio(benchmark_close, 126), 1e-6
        )
        rs_12m = _return_ratio(close, 252) / max(
            _return_ratio(benchmark_close, 252), 1e-6
        )
        rs_composite = (rs_3m * 0.5) + (rs_6m * 0.3) + (rs_12m * 0.2)

        # Volume confirmation
        breakout = False
        if len(close) > 20:
            breakout_level = _safe_float(high.iloc[-21:-1].max(), default=price)
            breakout = price > breakout_level
        if vol_surge:
            conviction += 10
        if breakout and current_volume < avg_volume_20:
            conviction -= 25  # High penalty for low volume trap

        # Volatility contraction (VCP-like)
        volume_dry_up = _safe_float(volume.tail(5).mean()) < avg_volume_20
        is_coiling = atr > 0 and atr100 > 0 and atr < (atr100 * 0.6) and volume_dry_up
        # VCP bonus requires uptrend context + not too far from highs to be actionable
        if is_coiling and tech_base and distance_to_high_pct < 30:
            conviction += 20  # VCP: coiling in uptrend near highs = high-quality signal
        elif is_coiling:
            conviction += 5  # Coiling without trend context
        elif atr > 0 and atr100 > 0 and atr < (atr100 * 0.8):
            conviction += 3  # Mild volatility contraction only

        # Apply news / earnings / resilience adjustments once, outside the trend gate,
        # so they affect both trend-following and non-trend setups without double-counting.
        conviction += score_mod

        # Mean reversion / over-extension guard
        extension_pct = ((price - ema50) / ema50) * 100 if ema50 > 0 else 0.0
        extension_ema200_pct = ((price - ema200) / ema200) * 100 if ema200 > 0 else 0.0
        overextended = extension_pct > 15
        if overextended:
            conviction -= 20
        if extension_ema200_pct > 40:
            conviction -= 20

        if target_high is not None and target_low is not None and price > 0:
            dispersion_pct = ((float(target_high) - float(target_low)) / price) * 100
        else:
            dispersion_pct = 0.0
        dispersion_alert = "⚠️ High Dispersion" if dispersion_pct > 30 else "✅"
        if dispersion_pct > 30:
            conviction -= 10

        # Sub-score raw components
        technical_raw = 0.0
        technical_raw += 35 if tech_base else 0
        if 45 <= rsi <= 65:
            technical_raw += 15
        elif (40 <= rsi < 45) or (65 < rsi <= 72):
            technical_raw += 8
        technical_raw += 10 if vol_surge_ratio > 1.8 else 0
        technical_raw += 8 if is_coiling else 0
        technical_raw -= 20 if extension_ema200_pct > 40 else 0
        technical_raw = max(0, technical_raw)

        fundamental_raw = 30.0
        if analyst_count and analyst_count > 0 and target_mean is not None:
            upside_pct = (
                ((_safe_float(target_mean, price) - price) / price) * 100
                if price > 0
                else 0
            )
            fundamental_raw += min(max(upside_pct, -20), 25)
        fundamental_raw += 10 if market_cap_cr > 1500 else 0
        if dispersion_pct > 25:
            fundamental_raw *= 0.7

        sentiment_raw = 50.0
        if news_sentiment == "🚨 BLACK SWAN":
            sentiment_raw -= 50
        half_life_days = 5.0
        decay = 1.0
        if earnings_ts is not None:
            days_ago = max((datetime.now().date() - earnings_ts.date()).days, 0)
            decay = 0.5 ** (days_ago / half_life_days)
        # Graduated earnings surprise: magnitude + recency decay
        if earnings_ts is not None:
            if earnings_surprise < -20:
                sentiment_raw -= 25 * decay  # Significant miss
            elif earnings_surprise < 0:
                sentiment_raw -= 12 * decay  # Small miss
            elif earnings_surprise > 20:
                sentiment_raw += 15 * decay  # Strong beat
            elif earnings_surprise > 5:
                sentiment_raw += 8 * decay  # Moderate beat
            else:
                sentiment_raw += 5 * decay  # In-line / no surprise data

        context_raw = 30.0
        context_raw += 20 if mtf_aligned else 0
        context_raw += 20 if rs_composite > 1.0 else 0
        ret_6m = (_return_ratio(close, 126) - 1) * 100
        vol_adj_mom = ret_6m / atr if atr > 0 else 0
        context_raw += min(max(vol_adj_mom, -10), 20)

        # Raw conviction fallback: preserve a meaningful base score when the setup has
        # no trend-based conviction yet, while still respecting explicit risk penalties.
        base_score_estimate = (
            technical_raw * 0.4
            + fundamental_raw * 0.25
            + sentiment_raw * 0.15
            + context_raw * 0.20
        )
        conviction = _resolve_conviction_score(
            conviction, base_score_estimate, score_mod
        )
        verdict = (
            "🔥 HIGH"
            if conviction >= 85 and mtf_aligned
            else (
                "🚀 PASS"
                if conviction >= 60
                else "🟡 WATCH" if tech_base else "❌ FAIL"
            )
        )
        if overextended:
            verdict = "⚠️ OVEREXTENDED"

        # Backtest returns (7, 30, 60, 90 days)
        current_date = close.index[-1]
        returns = {}
        for days in [7, 30, 60, 90]:
            try:
                target_date = current_date - pd.Timedelta(days=days)
                # Find nearest index
                idx = close.index.get_indexer([target_date], method="nearest")[0]
                past_price = float(close.iloc[idx])
                pct_change = ((price - past_price) / past_price) * 100
                returns[f"Ret_{days}D"] = pct_change
            except Exception as e:
                _logger.debug(f"{ticker} backtest return calc {days}D: {e}")
                returns[f"Ret_{days}D"] = 0.0

        # --- Velocity & Strategy ---
        ret_7d = returns.get("Ret_7D", 0.0)
        ret_30d = returns.get("Ret_30D", 0.0)
        velocity = ret_7d - ret_30d

        strategy = "Neutral"
        if price > ema50 and 55 <= rsi <= 70:
            strategy = "Momentum Pick"
        elif price > ema200 and dispersion_pct <= 30:
            strategy = "Long-Term Pick"

        buy_zone_high = price + (0.5 * atr)
        buy_zone = f"₹{price:.2f} - ₹{buy_zone_high:.2f}"

        steam_left = target_10d - price
        rsi_vel_factor = rsi / 50.0
        days_to_target = 0
        if rsi_vel_factor > 0 and atr > 0:
            days_to_target = steam_left / (atr * rsi_vel_factor)

        return {
            "Symbol": ticker,
            "Verdict": verdict,
            "Score": conviction,
            "Price": round(price, 2),
            "RSI": round(rsi, 1),
            "News": news_sentiment,
            "Events": event_status,
            "Sector": SECTOR_MAP.get(ticker, "General"),
            "Position_Qty": pos_size,
            "Stop_Loss": sl_price,
            "Target_10D": target_10d,
            "Analysts": analyst_count,
            "Tgt_High": target_high,
            "Tgt_Median": target_median,
            "Tgt_Low": target_low,
            "Tgt_Mean": target_mean,
            "Dispersion_Alert": dispersion_alert,
            "Ret_30D": returns.get("Ret_30D"),
            "Ret_60D": returns.get("Ret_60D"),
            "Ret_90D": returns.get("Ret_90D"),
            # New Metrics
            "Ret_7D": ret_7d,
            "Velocity": velocity,
            "Strategy": strategy,
            "Buy_Zone": buy_zone,
            "Steam_Left": steam_left,
            "Days_To_Target": days_to_target,
            "Resilience": resilience_label,
            "Gap_Integrity": gap_integrity,
            "Above_EMA200": price > ema200,
            "RS_Score": round(rs_score, 2),
            "Dist_52W_High_Pct": round(distance_to_high_pct, 2),
            "Vol_Surge_Ratio": round(vol_surge_ratio, 2),
            "Extension_Pct": round(extension_pct, 2),
            "Is_Coiling": is_coiling,
            "Avg_Volume_20D": round(avg_volume_20, 0),
            "Avg_Value_20D_Cr": round(avg_value_20d_cr, 2),
            "Market_Cap_Cr": round(market_cap_cr, 2),
            "Debt_To_Equity": round(debt_to_equity, 2),
            "Interest_Coverage": round(interest_coverage, 2),
            "Negative_Earnings_Surprise": bool(negative_earnings_surprise),
            "Black_Swan_Flag": black_swan_flag,
            "RS_3M": round(rs_3m, 3),
            "RS_6M": round(rs_6m, 3),
            "RS_12M": round(rs_12m, 3),
            "RS_Composite": round(rs_composite, 3),
            "Vol_Adj_Mom": round(vol_adj_mom, 2),
            "EMA200_Extension_Pct": round(extension_ema200_pct, 2),
            "Technical_Raw": round(technical_raw, 2),
            "Fundamental_Raw": round(fundamental_raw, 2),
            "Sentiment_Raw": round(sentiment_raw, 2),
            "Context_Raw": round(context_raw, 2),
            "Regime_Multiplier": round(regime_multiplier, 2),
        }
    except Exception as e:
        _logger.warning(f"check_institutional_fortress failed for {ticker}: {e}")
        return None


def backtest_top_picks(scan_timestamp):
    """Backtest top picks from a scan timestamp against Nifty benchmark forward returns."""
    try:
        from utils.db import get_connection

        with get_connection() as conn:
            query = """
                SELECT d.symbol AS Symbol, d.price AS Entry_Price
                FROM scan_history_details d
                INNER JOIN scans s ON s.scan_id = d.scan_id
                WHERE s.timestamp = ?
                  AND s.scan_type = 'STOCK'
                  AND COALESCE(d.score, 0) >= 60
            """
            picks = pd.read_sql(query, conn, params=(scan_timestamp,))
        if picks.empty:
            return pd.DataFrame()

        benchmark = _download_close_series(NIFTY_SYMBOL, period="2y")
        if benchmark.empty:
            return pd.DataFrame()

        horizon_days = [7, 30, 60]
        out_rows = []
        for _, row in picks.iterrows():
            symbol = row["Symbol"]
            data = _download_close_series(symbol, period="2y")
            if data.empty:
                continue
            latest = float(data.iloc[-1])
            stock_returns = {}
            nifty_returns = {}
            for days in horizon_days:
                if len(data) > days and len(benchmark) > days:
                    stock_returns[f"Stock_{days}D_%"] = (
                        (latest / float(data.iloc[-(days + 1)])) - 1
                    ) * 100
                    nifty_returns[f"Nifty_{days}D_%"] = (
                        (float(benchmark.iloc[-1]) / float(benchmark.iloc[-(days + 1)]))
                        - 1
                    ) * 100
                else:
                    stock_returns[f"Stock_{days}D_%"] = np.nan
                    nifty_returns[f"Nifty_{days}D_%"] = np.nan
            out_rows.append({"Symbol": symbol, **stock_returns, **nifty_returns})

        detail_df = pd.DataFrame(out_rows)
        if detail_df.empty:
            return detail_df

        avg_row = {"Symbol": "AVERAGE"}
        for days in horizon_days:
            avg_row[f"Stock_{days}D_%"] = detail_df[f"Stock_{days}D_%"].mean()
            avg_row[f"Nifty_{days}D_%"] = detail_df[f"Nifty_{days}D_%"].mean()
        avg_df = pd.concat([detail_df, pd.DataFrame([avg_row])], ignore_index=True)
        return avg_df
    except Exception:
        return pd.DataFrame()
