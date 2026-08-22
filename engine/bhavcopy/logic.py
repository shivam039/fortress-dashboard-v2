"""
engine/bhavcopy/logic.py
=========================
Fetch and parse NSE's daily UDiFF common Bhav Copy — the exchange's own
official EOD file (OHLC, volume, turnover, deliverable quantity) for every
NSE-listed equity, published after market close.

URL pattern (confirmed against current NSE archive behaviour, not the older
pre-2024 `archives.nseindia.com/.../cmDDMMMYYYYbhav.csv.zip` path, which NSE
has since retired):

    https://nsearchives.nseindia.com/content/cm/BhavCopy_NSE_CM_0_0_0_{YYYYMMDD}_F_0000.csv.zip

No API key or per-symbol rate limit — but NSE returns 403 for requests that
don't look like a real browser. `_new_session()` below does the same
"warm up on the homepage first, then fetch" dance that's standard practice
against this exact endpoint.

Column names in the downloaded CSV are UDiFF's own (not verified against a
live file as of writing this module — see the docstring on
`_normalise_columns` for exactly what's assumed and how a mismatch surfaces).

No live network calls happen at import time — this module only fetches when
one of the public functions below is called.
"""

from __future__ import annotations

import io
import logging
import zipfile
from datetime import date
from typing import Optional

import pandas as pd
import requests

logger = logging.getLogger("fortress.bhavcopy")

_BASE_URL = "https://nsearchives.nseindia.com/content/cm/BhavCopy_NSE_CM_0_0_0_{date}_F_0000.csv.zip"
_HOMEPAGE_URL = "https://www.nseindia.com"

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.nseindia.com/all-reports",
}

_REQUEST_TIMEOUT_S = 30

# UDiFF column -> our normalised column. Left-hand names are what NSE's UDiFF
# common bhavcopy format documents; if NSE renames a column again (it has
# done this before — see the pre-UDiFF -> UDiFF migration), a symbol/row
# simply won't map and `fetch_bhavcopy()` will raise a clear "no recognised
# columns" error rather than silently returning wrong data. Verify against a
# real downloaded file the first time this runs against production.
_COLUMN_MAP = {
    "TckrSymb": "symbol",
    "SctySrs": "series",
    "OpnPric": "open",
    "HghPric": "high",
    "LwPric": "low",
    "ClsPric": "close",
    "TtlTradgVol": "volume",
    "TtlTrdgVal": "turnover",
    "DlvryQty": "deliv_qty",
    "DlvryPct": "deliv_pct",
}

_REQUIRED_COLUMNS = {"symbol", "series", "open", "high", "low", "close", "volume"}


class BhavCopyUnavailable(Exception):
    """Raised when the file for a given date isn't published yet (or the
    date has no trading — weekend/holiday). Callers should treat this as
    "try again later", not a hard failure."""


class BhavCopyFormatError(Exception):
    """Raised when a downloaded file doesn't match the expected UDiFF
    column layout — signals NSE changed the format again, not a transient
    network issue."""


def _new_session() -> requests.Session:
    """A requests.Session that's been to the NSE homepage first, so it
    carries the cookies NSE's edge expects before it'll serve the archive
    file. A bare request to the bhavcopy URL with no prior visit reliably
    403s."""
    session = requests.Session()
    session.headers.update(_HEADERS)
    try:
        session.get(_HOMEPAGE_URL, timeout=_REQUEST_TIMEOUT_S)
    except requests.RequestException as exc:
        logger.warning("bhavcopy: homepage warm-up request failed: %s", exc)
    return session


def _download_zip(trade_date: date, session: Optional[requests.Session] = None) -> bytes:
    """Download the raw zip bytes for `trade_date`. Raises BhavCopyUnavailable
    on 404 (not published yet / non-trading day), re-raises other HTTP/
    network errors as-is so callers can distinguish "try later" from "this
    is broken"."""
    url = _BASE_URL.format(date=trade_date.strftime("%Y%m%d"))
    session = session or _new_session()
    resp = session.get(url, timeout=_REQUEST_TIMEOUT_S)
    if resp.status_code == 404:
        raise BhavCopyUnavailable(
            f"No Bhav Copy published yet for {trade_date.isoformat()} (404 at {url})"
        )
    resp.raise_for_status()
    return resp.content


def _normalise_columns(raw_df: pd.DataFrame) -> pd.DataFrame:
    """Rename UDiFF columns to our internal names and validate the result
    actually has what we need. Raises BhavCopyFormatError (not a silent
    empty result) if the expected columns aren't present, since that means
    NSE changed the format rather than "no data for this day"."""
    rename = {c: _COLUMN_MAP[c] for c in raw_df.columns if c in _COLUMN_MAP}
    if not rename:
        raise BhavCopyFormatError(
            f"None of the expected UDiFF columns {sorted(_COLUMN_MAP)} were found "
            f"in the downloaded file (got columns: {list(raw_df.columns)}). "
            "NSE may have changed the Bhav Copy format again."
        )
    df = raw_df.rename(columns=rename)
    missing = _REQUIRED_COLUMNS - set(df.columns)
    if missing:
        raise BhavCopyFormatError(
            f"Downloaded Bhav Copy is missing required column(s) {sorted(missing)} "
            f"after normalisation (had: {list(df.columns)})."
        )
    return df


def parse_bhavcopy_zip(raw_bytes: bytes) -> pd.DataFrame:
    """Parse a downloaded Bhav Copy zip into a normalised DataFrame.

    Returns columns: symbol (with .NS suffix), open, high, low, close,
    volume, turnover, deliv_qty, deliv_pct — filtered to SERIES == "EQ"
    (NSE bundles debt/preference-share series into the same file; those
    aren't equities this app scans/scores).
    """
    with zipfile.ZipFile(io.BytesIO(raw_bytes)) as zf:
        csv_names = [n for n in zf.namelist() if n.lower().endswith(".csv")]
        if not csv_names:
            raise BhavCopyFormatError(
                f"Downloaded zip contains no .csv file (contents: {zf.namelist()})"
            )
        with zf.open(csv_names[0]) as f:
            raw_df = pd.read_csv(f)

    df = _normalise_columns(raw_df)
    df = df[df["series"].astype(str).str.strip().str.upper() == "EQ"].copy()

    df["symbol"] = df["symbol"].astype(str).str.strip().str.upper() + ".NS"
    for col in ("open", "high", "low", "close", "volume", "turnover", "deliv_qty", "deliv_pct"):
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    keep = ["symbol", "open", "high", "low", "close", "volume", "turnover", "deliv_qty", "deliv_pct"]
    return df[[c for c in keep if c in df.columns]].reset_index(drop=True)


def fetch_bhavcopy(trade_date: date, session: Optional[requests.Session] = None) -> pd.DataFrame:
    """Download and parse one day's Bhav Copy. Raises BhavCopyUnavailable if
    not published yet, BhavCopyFormatError if the layout doesn't match
    expectations. No caching/DB access here — that's the job module's
    concern (see engine/bhavcopy/jobs.py)."""
    raw_bytes = _download_zip(trade_date, session=session)
    return parse_bhavcopy_zip(raw_bytes)
