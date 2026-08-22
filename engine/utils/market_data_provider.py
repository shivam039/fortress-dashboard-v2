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

    Tries INDstocks first (if token is set), falls back to yfinance.

    Args:
        symbol: NSE ticker with or without ``.NS`` suffix.
        period: Time period string. Supports yfinance-style periods
                (``"1d"``, ``"5d"``, ``"1mo"``, ``"3mo"``, ``"6mo"``,
                ``"1y"``, ``"2y"``). Periods > 1y fall back to yfinance
                automatically (INDstocks daily candles max 1 year).

    Returns:
        DataFrame with columns ``["Open", "High", "Low", "Close", "Volume"]``
        and a timezone-aware DatetimeIndex (IST). Empty DataFrame on failure.
    """
    if _indstocks_available():
        df = _ohlcv_indstocks(symbol, period)
        if df is not None and not df.empty:
            return df
        logger.warning(
            "INDstocks OHLCV failed for %s (%s), falling back to yfinance",
            symbol,
            period,
        )

    return _ohlcv_yfinance(symbol, period)


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


def get_batch_ohlcv(symbols: list[str], period: str = "1y") -> dict[str, pd.DataFrame]:
    """Get daily OHLCV for multiple NSE symbols from INDstocks in a few calls.

    This is the INDstocks/INDmoney equivalent of a bulk grouped download: it
    resolves every symbol to a scrip code via the instruments cache, then
    fetches historical candles in chunks of ``_BATCH_CHUNK_SIZE`` scrip codes
    per request (``INDstocksClient.get_historical`` already accepts a list of
    scrip codes in one call).

    This does **not** fall back to yfinance itself — callers should treat a
    partial or empty result as "fetch the missing symbols elsewhere" (e.g.
    via yfinance's grouped download), the same pattern ``get_batch_ltp`` uses.

    Args:
        symbols: NSE tickers (with or without ``.NS``).
        period: Yfinance-style period string. Only periods INDstocks supports
                for daily candles (``1d`` .. ``1y``) are attempted; anything
                else returns ``{}`` immediately so the caller falls back.

    Returns:
        Dict mapping each symbol that was successfully fetched to its OHLCV
        DataFrame. Symbols that could not be resolved or returned no candles
        are simply absent from the dict (not mapped to ``None``/empty).
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
                whichever is actually attempted first for new requests.
            ``"fallback"``: ``"yfinance"`` or ``"none"``.
            ``"primary_label"``: human-readable name for the primary source,
                for direct use in UI (``"INDmoney"`` or ``"Yahoo Finance"``).
            ``"auth_mode"``: ``"totp"``, ``"static_token"``, or ``"none"`` —
                which INDstocks credential path is configured.
            ``"indstocks_token_set"``: legacy string bool, kept for callers
                that already depend on this key.
    """
    available = _indstocks_available()
    if os.getenv("INDSTOCKS_TOKEN", "").strip():
        auth_mode = "static_token"
    elif _totp_creds_configured():
        auth_mode = "totp"
    else:
        auth_mode = "none"

    return {
        "primary": "indstocks" if available else "yfinance",
        "primary_label": "INDmoney" if available else "Yahoo Finance",
        "fallback": "yfinance" if available else "none",
        "auth_mode": auth_mode,
        "indstocks_token_set": str(available),
    }
