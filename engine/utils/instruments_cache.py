"""
engine/utils/instruments_cache.py
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Daily NSE/BSE instruments CSV cache with symbol → security_id lookup.

The INDstocks instruments endpoint returns a CSV with all tradable instruments.
This module downloads it once per calendar day (cached in /tmp) and provides
fast in-memory lookups so the rest of the engine can translate NSE ticker
symbols (``"RELIANCE"``) to the numeric security IDs the INDstocks API needs.

Typical usage::

    from utils.instruments_cache import get_instruments_cache

    cache = get_instruments_cache()
    sec_id = cache.get_security_id("RELIANCE")      # "2885"
    scrip  = cache.get_scrip_code("RELIANCE")       # "NSE_2885"
"""

from __future__ import annotations

import io
import logging
import os
from datetime import date
from pathlib import Path
from typing import Optional

import pandas as pd

logger = logging.getLogger(__name__)

# Where to cache the CSV on disk (survives the process, cleared each new day)
_CACHE_DIR = Path(os.getenv("TMPDIR", "/tmp")) / "fortress_instruments"
_CACHE_DIR.mkdir(parents=True, exist_ok=True)


def _cache_path(source: str) -> Path:
    today = date.today().isoformat()  # "2026-08-21"
    return _CACHE_DIR / f"instruments_{source}_{today}.csv"


class InstrumentsCache:
    """In-memory instruments lookup backed by a daily-refreshed CSV file.

    Args:
        source: INDstocks instruments source. Use ``"equity"`` for NSE stocks
                (default), ``"fno"`` for derivatives, ``"index"`` for indices.
    """

    def __init__(self, source: str = "equity") -> None:
        self._source = source
        self._df: pd.DataFrame | None = None

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _load(self) -> pd.DataFrame:
        """Return the instruments DataFrame, loading/downloading as needed."""
        if self._df is not None:
            return self._df

        cache_file = _cache_path(self._source)

        if cache_file.exists():
            logger.debug("Loading instruments from disk cache: %s", cache_file)
            df = pd.read_csv(cache_file, dtype=str)
        else:
            df = self._download_and_cache(cache_file)

        self._df = df
        logger.info(
            "Instruments cache ready: source=%s rows=%d", self._source, len(df)
        )
        return self._df

    def _download_and_cache(self, cache_file: Path) -> pd.DataFrame:
        """Download instruments CSV from INDstocks and persist to disk."""
        from utils.indstocks_client import get_client

        logger.info("Downloading INDstocks instruments CSV (source=%s)...", self._source)
        try:
            csv_bytes = get_client().get_instruments(self._source)
        except Exception as exc:
            logger.error("Failed to download instruments CSV: %s", exc)
            raise

        df = pd.read_csv(io.BytesIO(csv_bytes), dtype=str)
        cache_file.write_bytes(csv_bytes)
        logger.info("Instruments CSV cached at %s (%d rows)", cache_file, len(df))
        return df

    # ------------------------------------------------------------------
    # Public lookups
    # ------------------------------------------------------------------

    def get_security_id(self, nse_symbol: str) -> Optional[str]:
        """Return the numeric SECURITY_ID for an NSE equity symbol.

        Strips ``.NS`` / ``.BO`` suffixes automatically.

        Args:
            nse_symbol: NSE ticker, with or without ``.NS`` suffix
                        (e.g. ``"RELIANCE"`` or ``"RELIANCE.NS"``). This must
                        match the ``TRADING_SYMBOL`` column in the instruments
                        CSV (the short exchange ticker, not the full company name).

        Returns:
            Security ID string (e.g. ``"2885"``), or ``None`` if not found.
        """
        symbol = nse_symbol.upper().replace(".NS", "").replace(".BO", "").strip()
        df = self._load()

        # INDstocks equity CSV columns:
        #   EXCH | SEGMENT | SECURITY_ID | INSTRUMENT_NAME | EXPIRY_CODE |
        #   TRADING_SYMBOL | LOT_UNITS | CUSTOM_SYMBOL | EXPIRY_DATE |
        #   STRIKE_PRICE | OPTION_TYPE | TICK_SIZE | EXPIRY_FLAG |
        #   SEM_EXCH_INSTRUMENT_TYPE | SERIES | SYMBOL_NAME
        #
        # TRADING_SYMBOL holds the short NSE ticker (e.g. "RELIANCE").
        # SYMBOL_NAME holds the full company name (e.g. "Reliance Industries Ltd").
        if "TRADING_SYMBOL" not in df.columns or "SECURITY_ID" not in df.columns:
            logger.error("Unexpected CSV columns: %s", df.columns.tolist())
            return None

        # Prefer NSE rows in the EQ series (cash market delivery)
        mask_nse = df["EXCH"].str.upper() == "NSE"
        mask_eq = df.get("SERIES", pd.Series(dtype=str)).str.upper() == "EQ"
        mask_sym = df["TRADING_SYMBOL"].str.upper() == symbol

        matches = df[mask_nse & mask_eq & mask_sym]
        if matches.empty:
            # Fallback: any NSE row for this trading symbol
            matches = df[mask_nse & mask_sym]
        if matches.empty:
            logger.debug("Symbol not found in instruments cache: %s", symbol)
            return None

        return str(matches.iloc[0]["SECURITY_ID"])

    def get_scrip_code(self, nse_symbol: str, exchange: str = "NSE") -> Optional[str]:
        """Return the scrip code ready for INDstocks quote/historical APIs.

        Args:
            nse_symbol: NSE ticker (e.g. ``"RELIANCE"`` or ``"RELIANCE.NS"``).
            exchange: Exchange prefix (default ``"NSE"``).

        Returns:
            Scrip code string like ``"NSE_2885"``, or ``None`` if not found.
        """
        sec_id = self.get_security_id(nse_symbol)
        if sec_id is None:
            return None
        return f"{exchange}_{sec_id}"

    def search_symbol(self, query: str, n: int = 10) -> list[dict]:
        """Fuzzy-ish symbol search for debugging / admin use.

        Searches both ``TRADING_SYMBOL`` (short ticker) and ``SYMBOL_NAME``
        (full company name).

        Args:
            query: Partial symbol or company name (case-insensitive).
            n: Maximum number of results.

        Returns:
            List of dicts with ``TRADING_SYMBOL``, ``SYMBOL_NAME``,
            ``SECURITY_ID``, ``EXCH``, ``SERIES`` columns.
        """
        df = self._load()
        query_upper = query.upper()
        mask = (
            df["TRADING_SYMBOL"].str.upper().str.contains(query_upper, na=False)
            | df.get("SYMBOL_NAME", pd.Series(dtype=str))
            .str.upper()
            .str.contains(query_upper, na=False)
        )
        cols = [c for c in ["TRADING_SYMBOL", "SYMBOL_NAME", "SECURITY_ID", "EXCH", "SERIES"]
                if c in df.columns]
        return df[mask].head(n)[cols].to_dict(orient="records")

    def invalidate(self) -> None:
        """Force a re-download on the next lookup (clears in-memory cache only)."""
        self._df = None
        logger.info("Instruments cache invalidated (in-memory)")


# ------------------------------------------------------------------
# Module-level singletons
# ------------------------------------------------------------------
_equity_cache: InstrumentsCache | None = None


def get_instruments_cache(source: str = "equity") -> InstrumentsCache:
    """Return the module-level singleton InstrumentsCache for a given source.

    Args:
        source: ``"equity"`` (default), ``"fno"``, or ``"index"``.

    Returns:
        Shared ``InstrumentsCache`` instance (lazy-loaded on first lookup).
    """
    global _equity_cache
    if source == "equity":
        if _equity_cache is None:
            _equity_cache = InstrumentsCache("equity")
        return _equity_cache
    # Non-equity caches are not singletonized (less frequent use)
    return InstrumentsCache(source)
