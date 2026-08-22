"""
engine/utils/market_data_provider.py
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Unified market data abstraction for Fortress.

**This is the only module the rest of the engine should import for price data.**
It selects the best available provider automatically:

    INDstocks / INDmoney (primary, TOTP or static token)  →  yfinance (fallback)

Callers never need to know which provider is active. If the primary fails,
the module falls back silently and logs a warning.

Usage::

    from utils.market_data_provider import get_ltp, get_ohlcv

    price = get_ltp("RELIANCE.NS")          # float | None
    df    = get_ohlcv("RELIANCE.NS", "1y")  # pd.DataFrame with OHLCV columns
"""

from __future__ import annotations

import logging
import os
import time
from datetime import datetime, timedelta, timezone
from typing import Optional

import pandas as pd

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Provider detection
# ---------------------------------------------------------------------------

def _totp_creds_configured() -> bool:
    """Return True if the TOTP auto-refresh trio is set (client id/mpin/secret)."""
    return all(
        os.getenv(k, "").strip()
        for k in ("INDSTOCKS_CLIENT_ID", "INDSTOCKS_MPIN", "INDSTOCKS_TOTP_SECRET")
    )


def _indstocks_available() -> bool:
    """Return True if the INDstocks/INDmoney provider is configured.

    This must be True whenever ``engine.utils.indstocks_client.get_client()``
    would be able to construct a client — i.e. either a static
    ``INDSTOCKS_TOKEN`` is present, *or* the TOTP auto-refresh trio
    (``INDSTOCKS_CLIENT_ID`` + ``INDSTOCKS_MPIN`` + ``INDSTOCKS_TOTP_SECRET``)
    is set.

    Previously this only checked ``INDSTOCKS_TOKEN``. ``INDSTOCKS_TOKEN`` is
    populated lazily, as a *side effect* of ``indstocks_client.get_client()``
    generating a fresh token via TOTP — but this module never called
    ``get_client()`` unless this function already returned True. With only
    the (documented, "preferred") TOTP trio set and no static token, that
    meant INDstocks/INDmoney was never even attempted: every request silently
    fell straight through to yfinance, forever, regardless of documentation
    and architecture rules saying INDstocks/INDmoney is primary.
    """
    if os.getenv("INDSTOCKS_TOKEN", "").strip():
        return True
    return _totp_creds_configured()


# ---------------------------------------------------------------------------
# OHLCV/scan data source preference (Bhav Copy vs INDstocks toggle)
# ---------------------------------------------------------------------------
#
# This ONLY affects get_ohlcv()/get_batch_ohlcv() (historical/scan data).
# get_ltp()/get_batch_ltp() above are untouched by this setting and always
# go INDstocks -> yfinance: NSE Bhav Copy is an end-of-day file, it has no
# intraday/live price to serve.

_OHLCV_PREFERENCE_SETTING_KEY = "ohlcv_provider_preference"
_OHLCV_PREFERENCE_DEFAULT = "bhavcopy"
_OHLCV_PREFERENCE_VALID = {"bhavcopy", "indstocks"}

# Short in-process TTL cache so every get_ohlcv()/get_batch_ohlcv() call
# doesn't hit the DB just to read a setting that changes maybe once in a
# session — same short-lived-cache shape as the REIT degraded-cache cooldown
# in routers/reit_invits.py.
_PREFERENCE_CACHE_TTL_S = 30
_preference_cache: dict = {"value": None, "ts": None}


def get_ohlcv_provider_preference() -> str:
    """Return the active OHLCV/scan-data source: "bhavcopy" (default) or
    "indstocks". Backed by utils.db.get_setting/set_setting (app_settings
    table) — see engine/main.py's /api/settings/data-provider endpoints for
    where this gets written."""
    now = time.monotonic()
    cached_ts = _preference_cache["ts"]
    if cached_ts is not None and (now - cached_ts) < _PREFERENCE_CACHE_TTL_S:
        return _preference_cache["value"]

    try:
        from utils.db import get_setting

        value = get_setting(_OHLCV_PREFERENCE_SETTING_KEY, default=_OHLCV_PREFERENCE_DEFAULT)
    except Exception as exc:
        logger.warning(
            "Failed to read OHLCV provider preference, defaulting to %s: %s",
            _OHLCV_PREFERENCE_DEFAULT,
            exc,
        )
        value = _OHLCV_PREFERENCE_DEFAULT

    if value not in _OHLCV_PREFERENCE_VALID:
        value = _OHLCV_PREFERENCE_DEFAULT

    _preference_cache["value"] = value
    _preference_cache["ts"] = now
    return value


# Cumulative count of OHLCV calls actually SERVED by each source, since
# process start (or the last reset). This exists because
# provider_status()'s ohlcv_source field only reflects the configured
# PREFERENCE, not what actually satisfied any given call — a preference of
# "bhavcopy" silently falls through to indstocks/yfinance per-symbol
# whenever Bhav Copy has no data yet (e.g. before a backfill has run, or
# for a single symbol Bhav Copy doesn't cover), and that fallback is
# invisible to anyone just reading the preference setting. These counters
# are the concrete, checkable answer to "is Bhav Copy actually being used".
_ohlcv_source_call_counts: dict = {"bhavcopy": 0, "indstocks": 0, "yfinance": 0}


def get_ohlcv_source_call_counts() -> dict:
    """Cumulative per-source OHLCV call counts since process start or the
    last reset_ohlcv_source_call_counts() call. Surfaced via
    GET /api/bhavcopy/status."""
    return dict(_ohlcv_source_call_counts)


def reset_ohlcv_source_call_counts() -> None:
    """Zero the counters — e.g. right before a scan, so the counts that
    follow reflect just that scan rather than everything since the process
    started."""
    for key in _ohlcv_source_call_counts:
        _ohlcv_source_call_counts[key] = 0


def _record_ohlcv_source(source: str, count: int = 1) -> None:
    if count <= 0:
        return
    _ohlcv_source_call_counts[source] = _ohlcv_source_call_counts.get(source, 0) + count


def invalidate_ohlcv_provider_preference_cache() -> None:
    """Drop the cached preference so the next get_ohlcv()/get_batch_ohlcv()
    call re-reads the DB immediately. Called by the settings POST endpoint
    right after writing a new preference, so a toggle takes effect without
    waiting out _PREFERENCE_CACHE_TTL_S."""
    _preference_cache["value"] = None
    _preference_cache["ts"] = None


# ---------------------------------------------------------------------------
# LTP (Last Traded Price)
# ---------------------------------------------------------------------------

def get_ltp(symbol: str) -> Optional[float]:
    """Get the last traded price for an NSE equity symbol.

    Tries INDstocks first (if token is set), falls back to yfinance.

    Args:
        symbol: NSE ticker with or without ``.NS`` suffix
                (e.g. ``"RELIANCE"`` or ``"RELIANCE.NS"``).

    Returns:
        Last traded price as a float, or ``None`` on failure.
    """
    if _indstocks_available():
        price = _ltp_indstocks(symbol)
        if price is not None:
            return price
        logger.warning("INDstocks LTP failed for %s, falling back to yfinance", symbol)

    return _ltp_yfinance(symbol)


def _ltp_indstocks(symbol: str) -> Optional[float]:
    """Fetch LTP from INDstocks."""
    try:
        from utils.instruments_cache import get_instruments_cache
        from utils.indstocks_client import get_client, INDstocksError

        scrip = get_instruments_cache().get_scrip_code(symbol)
        if scrip is None:
            logger.debug("No scrip code for %s in instruments cache", symbol)
            return None

        data = get_client().get_ltp([scrip])
        entry = data.get(scrip, {})
        price = entry.get("live_price")
        if price is not None:
            logger.debug("INDstocks LTP %s = %s", symbol, price)
            return float(price)
        return None
    except Exception as exc:
        logger.warning("INDstocks LTP error for %s: %s", symbol, exc)
        return None


def _format_yf_ticker(symbol: str) -> str:
    """Format symbol for Yahoo Finance."""
    s = symbol.strip()
    if s.startswith("^") or "." in s or "=" in s:
        return s
    return f"{s}.NS"


def _ltp_yfinance(symbol: str) -> Optional[float]:
    """Fetch LTP from yfinance (current fallback)."""
    try:
        import yfinance as yf  # type: ignore[import]

        ticker = _format_yf_ticker(symbol)
        info = yf.Ticker(ticker).fast_info
        price = getattr(info, "last_price", None)
        if price is not None:
            logger.debug("yfinance LTP %s = %s", ticker, price)
            return float(price)
        return None
    except Exception as exc:
        logger.warning("yfinance LTP error for %s: %s", symbol, exc)
        return None


# ---------------------------------------------------------------------------
# OHLCV historical data
# ---------------------------------------------------------------------------

def get_ohlcv(symbol: str, period: str = "1y") -> pd.DataFrame:
    """Get historical OHLCV data for an NSE equity symbol.

    Tier order depends on ``get_ohlcv_provider_preference()``:
      - ``"bhavcopy"`` (default): NSE Bhav Copy -> INDstocks -> yfinance.
      - ``"indstocks"``: INDstocks -> yfinance (Bhav Copy not tried at all).

    Args:
        symbol: NSE ticker with or without ``.NS`` suffix.
        period: Time period string. Supports yfinance-style periods
                (``"1d"``, ``"5d"``, ``"1mo"``, ``"3mo"``, ``"6mo"``,
                ``"1y"``, ``"2y"``, ``"5y"``). Periods > 1y automatically
                skip the INDstocks tier (daily candles max 1 year there) but
                are supported by both Bhav Copy (however much history has
                accumulated/been backfilled) and yfinance.

    Returns:
        DataFrame with columns ``["Open", "High", "Low", "Close", "Volume"]``
        and a DatetimeIndex. Empty DataFrame on failure.
    """
    preference = get_ohlcv_provider_preference()

    if preference == "bhavcopy":
        df = _ohlcv_bhavcopy(symbol, period)
        if df is not None and not df.empty:
            if _bhavcopy_has_sufficient_coverage(df, period):
                _record_ohlcv_source("bhavcopy")
                return df
            logger.debug(
                "Bhav Copy has only %d rows for %s (%s) — below the coverage "
                "threshold for this period (likely mid-backfill), falling back",
                len(df),
                symbol,
                period,
            )
        else:
            logger.debug(
                "Bhav Copy has no OHLCV for %s (%s) yet, falling back", symbol, period
            )

    if _indstocks_available():
        df = _ohlcv_indstocks(symbol, period)
        if df is not None and not df.empty:
            _record_ohlcv_source("indstocks")
            return df
        logger.warning(
            "INDstocks OHLCV failed for %s (%s), falling back to yfinance",
            symbol,
            period,
        )

    df = _ohlcv_yfinance(symbol, period)
    if not df.empty:
        _record_ohlcv_source("yfinance")
    return df


# Period string -> lookback in days, for the Bhav Copy tier. Deliberately a
# separate mapping from _period_to_ms below (which is INDstocks-specific and
# caps at 1y, an INDstocks API limit that doesn't apply to Bhav Copy's own
# accumulated history).
_BHAVCOPY_PERIOD_TO_DAYS = {
    "1d": 1,
    "5d": 5,
    "1mo": 30,
    "3mo": 90,
    "6mo": 180,
    "1y": 365,
    "2y": 730,
    "3y": 1095,
    "5y": 1825,
}


def _period_to_start_date(period: str) -> Optional[str]:
    """Convert a period string to a "YYYY-MM-DD" start-date bound for the
    Bhav Copy tier. Returns None for an unrecognised period string, which
    callers should treat as "no lower bound — return everything cached"."""
    days = _BHAVCOPY_PERIOD_TO_DAYS.get(period)
    if days is None:
        return None
    start = datetime.now(tz=timezone.utc) - timedelta(days=days)
    return start.strftime("%Y-%m-%d")


# Below this fraction of the trading days a requested period should actually
# contain, Bhav Copy's answer is treated as "not enough history yet" (e.g.
# mid-backfill, or a genuinely recent listing) rather than "good enough" —
# and the tier falls through to INDstocks/yfinance instead of silently
# serving a technically-non-empty-but-practically-useless partial history.
#
# This was found live: right after the backfill first ran, Bhav Copy had
# only ~16 trading days of history. Because the old check was just "is the
# DataFrame non-empty", get_ohlcv()/get_batch_ohlcv() served that thin
# 16-row history outright for period="1y" requests — which then silently
# failed stock_scanner.logic.check_institutional_fortress's own
# `len(data) < 210` minimum-history gate for every single symbol, so a full
# scan came back with 0 results and no error anywhere in the chain.
_BHAVCOPY_MIN_COVERAGE_RATIO = 0.5


def _bhavcopy_has_sufficient_coverage(df: pd.DataFrame, period: str) -> bool:
    """Return False if ``df`` (Bhav Copy's answer for ``period``) covers
    meaningfully fewer trading days than the period actually spans. Uses the
    real NSE-week calendar (``pandas.bdate_range``, Mon–Fri) rather than a
    hardcoded row count, so this stays correct for every period string
    (a "1mo" request needing ~22 trading days isn't held to the same bar as
    a "1y" request needing ~260) without hardcoding any specific caller's
    own downstream minimum (e.g. the scanner's 210)."""
    start_date = _period_to_start_date(period)
    if start_date is None:
        # Unrecognised period string — no expected-length bound to compare
        # against, so accept whatever Bhav Copy has.
        return True
    expected_trading_days = len(
        pd.bdate_range(start=start_date, end=datetime.now(tz=timezone.utc).date())
    )
    if expected_trading_days == 0:
        return True
    return len(df) >= expected_trading_days * _BHAVCOPY_MIN_COVERAGE_RATIO


def _ohlcv_bhavcopy(symbol: str, period: str) -> Optional[pd.DataFrame]:
    """Fetch OHLCV from the NSE Bhav Copy accumulation table. Returns None
    (not an empty DataFrame) when there's nothing cached for this symbol at
    all, matching _ohlcv_indstocks's "None means try the next tier"
    contract — an empty-but-not-None DataFrame would be indistinguishable
    from "genuinely no data in this date range" for a symbol we otherwise
    do have history for.
    """
    try:
        from utils.db import fetch_bhavcopy_ohlcv

        start_date = _period_to_start_date(period)
        df = fetch_bhavcopy_ohlcv(symbol, start_date=start_date)
        if df.empty:
            return None
        return df
    except Exception as exc:
        logger.warning("Bhav Copy OHLCV error for %s: %s", symbol, exc)
        return None


def _period_to_ms(period: str) -> tuple[int, int] | None:
    """Convert a period string to (start_ms, end_ms) Unix epoch milliseconds.

    Returns None if the period exceeds INDstocks limits (1 year for daily).
    """
    now = datetime.now(tz=timezone.utc)
    period_map = {
        "1d": timedelta(days=1),
        "5d": timedelta(days=5),
        "1mo": timedelta(days=30),
        "3mo": timedelta(days=90),
        "6mo": timedelta(days=180),
        "1y": timedelta(days=365),
    }
    if period not in period_map:
        return None  # Unknown period — let yfinance handle it

    delta = period_map[period]
    start = now - delta
    return int(start.timestamp() * 1000), int(now.timestamp() * 1000)


def _candles_to_df(candles: list[dict]) -> pd.DataFrame:
    """Convert a list of INDstocks candle dicts into a standard OHLCV DataFrame.

    Args:
        candles: List of ``{"ts": int, "o": float, "h": float, "l": float,
                 "c": float, "v": int}`` dicts (``ts`` = Unix epoch seconds).

    Returns:
        DataFrame with ``["Open", "High", "Low", "Close", "Volume"]`` columns
        and a tz-aware (IST) ``DatetimeIndex`` named ``"Date"``. Empty
        DataFrame if ``candles`` is empty.
    """
    if not candles:
        return pd.DataFrame()

    df = pd.DataFrame(candles)
    # ts is Unix epoch seconds (IST per INDstocks docs)
    IST = timezone(timedelta(hours=5, minutes=30))
    df["datetime"] = pd.to_datetime(df["ts"], unit="s", utc=True).dt.tz_convert(IST)
    df = df.set_index("datetime")
    df = df.rename(columns={"o": "Open", "h": "High", "l": "Low", "c": "Close", "v": "Volume"})
    df = df[["Open", "High", "Low", "Close", "Volume"]].astype(float)
    df.index.name = "Date"
    return df


def _ohlcv_indstocks(symbol: str, period: str) -> Optional[pd.DataFrame]:
    """Fetch OHLCV from INDstocks (daily candles)."""
    try:
        from utils.instruments_cache import get_instruments_cache
        from utils.indstocks_client import get_client

        range_ms = _period_to_ms(period)
        if range_ms is None:
            logger.debug("Period %s exceeds INDstocks range, skipping", period)
            return None

        scrip = get_instruments_cache().get_scrip_code(symbol)
        if scrip is None:
            return None

        start_ms, end_ms = range_ms
        raw = get_client().get_historical([scrip], "1day", start_ms, end_ms)
        candles = raw.get(scrip, {}).get("candles", [])
        df = _candles_to_df(candles)
        if df.empty:
            return None

        logger.debug(
            "INDstocks OHLCV %s: %d candles (%s → %s)",
            symbol,
            len(df),
            df.index.min(),
            df.index.max(),
        )
        return df

    except Exception as exc:
        logger.warning("INDstocks OHLCV error for %s: %s", symbol, exc)
        return None


# ---------------------------------------------------------------------------
# Batch OHLCV (multi-ticker, single/few INDstocks calls)
# ---------------------------------------------------------------------------

# INDstocks does NOT publish a cap for /market/historical scrip-codes (unlike
# the LTP/quote endpoints, which document 1000/call) — this was determined
# empirically: a live probe against the real API showed batches of 5 scrip
# codes succeed and batches of 6+ fail with a generic
# {"debug_info":"Invalid scrip codes","message":"Bad Request"}, with no
# indication in the error that it's actually a size limit. Every code in a
# failing batch works fine solo, ruling out a bad/invalid scrip code. If
# INDstocks ever documents or changes this limit, update it here.
_BATCH_CHUNK_SIZE = 5


def _batch_ohlcv_bhavcopy(symbols: list[str], period: str) -> dict[str, pd.DataFrame]:
    """Bhav Copy equivalent of get_batch_ohlcv — a single local DB read
    (utils.db.fetch_bhavcopy_ohlcv_batch), not a network call, so unlike the
    INDstocks tier there's no chunking/rate limit to worry about here."""
    if not symbols:
        return {}
    try:
        from utils.db import fetch_bhavcopy_ohlcv_batch

        start_date = _period_to_start_date(period)
        return fetch_bhavcopy_ohlcv_batch(symbols, start_date=start_date)
    except Exception as exc:
        logger.warning("Bhav Copy batch OHLCV error: %s", exc)
        return {}


def get_batch_ohlcv(symbols: list[str], period: str = "1y") -> dict[str, pd.DataFrame]:
    """Get daily OHLCV for multiple NSE symbols.

    Tier order depends on ``get_ohlcv_provider_preference()``:
      - ``"bhavcopy"`` (default): Bhav Copy DB read first (cheap, no network
        call at all), then INDstocks for whatever symbols it didn't cover.
      - ``"indstocks"``: INDstocks only (Bhav Copy not tried).

    Neither tier falls back to yfinance itself — callers should treat a
    partial or empty result as "fetch the missing symbols elsewhere" (e.g.
    via yfinance's grouped download), the same pattern ``get_batch_ltp`` uses.

    Args:
        symbols: NSE tickers (with or without ``.NS``).
        period: Yfinance-style period string.

    Returns:
        Dict mapping each symbol that was successfully fetched to its OHLCV
        DataFrame. Symbols that could not be resolved are simply absent
        from the dict (not mapped to ``None``/empty).
    """
    if not symbols:
        return {}

    preference = get_ohlcv_provider_preference()
    result: dict[str, pd.DataFrame] = {}
    remaining = symbols

    if preference == "bhavcopy":
        raw_result = _batch_ohlcv_bhavcopy(symbols, period)
        # Drop any symbol whose Bhav Copy history doesn't clear the coverage
        # bar for this period (see _bhavcopy_has_sufficient_coverage) — those
        # symbols fall through to the INDstocks tier below just like a
        # symbol Bhav Copy had nothing for at all, instead of being served a
        # thin partial history that downstream scoring would just reject.
        result = {
            sym: df
            for sym, df in raw_result.items()
            if _bhavcopy_has_sufficient_coverage(df, period)
        }
        _record_ohlcv_source("bhavcopy", count=len(result))
        remaining = [s for s in symbols if s not in result]
        if not remaining:
            return result

    if not remaining or not _indstocks_available():
        return result

    indstocks_result = _batch_ohlcv_indstocks(remaining, period)
    _record_ohlcv_source("indstocks", count=len(indstocks_result))
    result.update(indstocks_result)
    return result


def _batch_ohlcv_indstocks(symbols: list[str], period: str) -> dict[str, pd.DataFrame]:
    """INDstocks tier of get_batch_ohlcv (split out so the Bhav Copy tier
    above can call this only for symbols it didn't already cover).

    Resolves every symbol to a scrip code via the instruments cache, then
    fetches historical candles in chunks of ``_BATCH_CHUNK_SIZE`` scrip codes
    per request (``INDstocksClient.get_historical`` already accepts a list of
    scrip codes in one call). Only periods INDstocks supports for daily
    candles (``1d`` .. ``1y``) are attempted; anything else returns ``{}``
    immediately so the caller falls back.
    """
    if not symbols or not _indstocks_available():
        return {}

    range_ms = _period_to_ms(period)
    if range_ms is None:
        logger.debug("Period %s exceeds INDstocks batch range, skipping", period)
        return {}

    try:
        from utils.instruments_cache import get_instruments_cache
        from utils.indstocks_client import get_client

        cache = get_instruments_cache()
        sym_to_scrip: dict[str, str] = {}
        for sym in symbols:
            scrip = cache.get_scrip_code(sym)
            if scrip:
                sym_to_scrip[sym] = scrip

        if not sym_to_scrip:
            return {}

        scrip_to_sym = {v: k for k, v in sym_to_scrip.items()}
        start_ms, end_ms = range_ms
        client = get_client()

        result: dict[str, pd.DataFrame] = {}
        codes = list(sym_to_scrip.values())
        for i in range(0, len(codes), _BATCH_CHUNK_SIZE):
            chunk = codes[i : i + _BATCH_CHUNK_SIZE]
            try:
                raw = client.get_historical(chunk, "1day", start_ms, end_ms)
            except Exception as exc:
                logger.warning(
                    "INDstocks batch OHLCV chunk (%d symbols) failed: %s",
                    len(chunk),
                    exc,
                )
                continue
            for scrip, payload in raw.items():
                sym = scrip_to_sym.get(scrip)
                if sym is None:
                    continue
                df = _candles_to_df(payload.get("candles", []))
                if not df.empty:
                    result[sym] = df

        logger.info(
            "INDstocks batch OHLCV: %d/%d symbols fetched", len(result), len(symbols)
        )
        return result

    except Exception as exc:
        logger.warning("INDstocks batch OHLCV error: %s", exc)
        return {}


def _ohlcv_yfinance(symbol: str, period: str) -> pd.DataFrame:
    """Fetch OHLCV from yfinance (current fallback)."""
    try:
        import yfinance as yf  # type: ignore[import]

        ticker = _format_yf_ticker(symbol)
        df = yf.download(ticker, period=period, auto_adjust=True, progress=False)
        if df.empty:
            logger.warning("yfinance returned empty data for %s (%s)", ticker, period)
            return pd.DataFrame()
        # Normalise column names (yfinance may return multi-level columns)
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        df = df[["Open", "High", "Low", "Close", "Volume"]]
        logger.debug("yfinance OHLCV %s: %d rows", ticker, len(df))
        return df
    except Exception as exc:
        logger.warning("yfinance OHLCV error for %s: %s", symbol, exc)
        return pd.DataFrame()


# ---------------------------------------------------------------------------
# Batch LTP (convenience)
# ---------------------------------------------------------------------------

def get_batch_ltp(symbols: list[str]) -> dict[str, Optional[float]]:
    """Get LTP for multiple symbols in one call where possible.

    Uses INDstocks batch endpoint when available (avoids N sequential calls).
    Falls back to yfinance per-symbol if INDstocks is unavailable.

    Args:
        symbols: List of NSE tickers (with or without ``.NS``).

    Returns:
        Dict mapping each symbol to its LTP, or ``None`` on failure.
    """
    result: dict[str, Optional[float]] = {}

    if _indstocks_available():
        result = _batch_ltp_indstocks(symbols)
        missing = [s for s, v in result.items() if v is None]
        if missing:
            logger.warning(
                "INDstocks batch LTP missing %d symbols, using yfinance for those",
                len(missing),
            )
            for sym in missing:
                result[sym] = _ltp_yfinance(sym)
        return result

    # yfinance fallback — individual calls
    for sym in symbols:
        result[sym] = _ltp_yfinance(sym)
    return result


def _batch_ltp_indstocks(symbols: list[str]) -> dict[str, Optional[float]]:
    """Fetch LTP for multiple symbols in one INDstocks call."""
    result: dict[str, Optional[float]] = {s: None for s in symbols}
    try:
        from utils.instruments_cache import get_instruments_cache
        from utils.indstocks_client import get_client

        cache = get_instruments_cache()
        sym_to_scrip: dict[str, str] = {}
        for sym in symbols:
            scrip = cache.get_scrip_code(sym)
            if scrip:
                sym_to_scrip[sym] = scrip

        if not sym_to_scrip:
            return result

        # INDstocks supports up to 1000 scrips per call
        scrip_codes = list(sym_to_scrip.values())
        data = get_client().get_ltp(scrip_codes)

        scrip_to_sym = {v: k for k, v in sym_to_scrip.items()}
        for scrip, entry in data.items():
            sym = scrip_to_sym.get(scrip)
            if sym and "live_price" in entry:
                result[sym] = float(entry["live_price"])

    except Exception as exc:
        logger.warning("INDstocks batch LTP error: %s", exc)

    return result


# ---------------------------------------------------------------------------
# Provider info (for debugging / health checks)
# ---------------------------------------------------------------------------

def provider_status() -> dict[str, str]:
    """Return current provider configuration for debugging and UI display.

    Returns:
        Dict with keys:
            ``"primary"``: ``"indstocks"`` (INDmoney) or ``"yfinance"`` —
                whichever is actually attempted first for LIVE PRICE
                (get_ltp/get_batch_ltp) requests. Untouched by the OHLCV
                provider toggle below — Bhav Copy has no intraday price.
            ``"fallback"``: ``"yfinance"`` or ``"none"``.
            ``"primary_label"``: human-readable name for the live-price
                primary source (``"INDmoney"`` or ``"Yahoo Finance"``).
            ``"auth_mode"``: ``"totp"``, ``"static_token"``, or ``"none"`` —
                which INDstocks credential path is configured.
            ``"indstocks_token_set"``: legacy string bool, kept for callers
                that already depend on this key.
            ``"ohlcv_source"``: ``"bhavcopy"`` (default) or ``"indstocks"``
                — the active OHLCV/SCAN data preference (see
                get_ohlcv_provider_preference()), independently toggleable
                from the live-price ``"primary"`` above via
                POST /api/settings/data-provider.
            ``"ohlcv_source_label"``: human-readable name for
                ``"ohlcv_source"`` (``"NSE Bhav Copy"``, ``"INDmoney"``, or
                ``"Yahoo Finance"``).
    """
    available = _indstocks_available()
    if os.getenv("INDSTOCKS_TOKEN", "").strip():
        auth_mode = "static_token"
    elif _totp_creds_configured():
        auth_mode = "totp"
    else:
        auth_mode = "none"

    ohlcv_preference = get_ohlcv_provider_preference()
    ohlcv_source_label = (
        "NSE Bhav Copy"
        if ohlcv_preference == "bhavcopy"
        else ("INDmoney" if available else "Yahoo Finance")
    )

    return {
        "primary": "indstocks" if available else "yfinance",
        "primary_label": "INDmoney" if available else "Yahoo Finance",
        "fallback": "yfinance" if available else "none",
        "auth_mode": auth_mode,
        "indstocks_token_set": str(available),
        "ohlcv_source": ohlcv_preference,
        "ohlcv_source_label": ohlcv_source_label,
    }
