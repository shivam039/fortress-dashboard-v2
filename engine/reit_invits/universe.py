"""
reit_invits/universe.py
=======================
Static universe of tradeable Indian REITs and InvITs on NSE/BSE.
Yahoo Finance tickers use the .NS suffix.

Ticker corrections (verified against screener.in / nseindia.com — the
exchange-registered NSE symbol, not a marketing name, is what yfinance
needs): several entries here used to be guessed from the company's
marketing name rather than its actual NSE trading symbol, which silently
broke every fetch for that instrument (yfinance returns an empty frame for
an unknown ticker, which then shows as permanently "loading"/no-data for
that row instead of a clear error):
  - "BROOKFIELD.NS"  -> "BIRET.NS"       (Brookfield India Real Estate Trust
                                           trades as BIRET, not BROOKFIELD)
  - "NEXUSMALLS.NS"  -> "NXST.NS"        (Nexus Select Trust trades as NXST)
  - "POWERTRAN.NS"   -> "PGINVIT.NS"     (PowerGrid Infra InvIT trades as
                                           PGINVIT)
  - "NHAI.NS"        -> "NHIT.NS"        (National Highways Infra Trust
                                           trades as NHIT — "NHAI" is the
                                           sponsoring authority, not the
                                           trust's own ticker)
  - "BHINVIT.NS"     -> "INDUSINVIT.NS"  (Bharat Highways InvIT was renamed
                                           Indus Infra Trust; INDUSINVIT is
                                           its current symbol)

Also added two more listed InvITs/REITs that were missing from the universe
entirely: Knowledge Realty Trust (KRT) and Raajmarg Infra Investment Trust
(RIIT, NHAI-sponsored).

This list is necessarily maintained by hand — there's no single reliable
free API for "every listed Indian REIT/InvIT" — so it should be re-checked
periodically against the Nifty REITs & InvITs Index factsheet
(niftyindices.com) as new trusts list or existing ones rename.
"""

from typing import Any

REIT_INVIT_UNIVERSE: dict[str, dict[str, Any]] = {
    # ── REITs ────────────────────────────────────────────────────────────────
    "EMBASSY.NS": {
        "name": "Embassy Office Parks REIT",
        "type": "REIT",
        "sub_type": "Office",
        "sponsor": "Embassy Group / Blackstone",
        "sector": "Real Estate",
    },
    "MINDSPACE.NS": {
        "name": "Mindspace Business Parks REIT",
        "type": "REIT",
        "sub_type": "Office",
        "sponsor": "K Raheja Corp / Blackstone",
        "sector": "Real Estate",
    },
    "BIRET.NS": {
        "name": "Brookfield India Real Estate Trust",
        "type": "REIT",
        "sub_type": "Office",
        "sponsor": "Brookfield Asset Management",
        "sector": "Real Estate",
    },
    "NXST.NS": {
        "name": "Nexus Select Trust",
        "type": "REIT",
        "sub_type": "Retail Mall",
        "sponsor": "Nexus Malls / Blackstone",
        "sector": "Real Estate",
    },
    "KRT.NS": {
        "name": "Knowledge Realty Trust",
        "type": "REIT",
        "sub_type": "Office",
        "sponsor": "Blackstone / Sattva Group",
        "sector": "Real Estate",
    },
    # ── InvITs ───────────────────────────────────────────────────────────────
    "INDIGRID.NS": {
        "name": "India Grid Trust (IndiGrid)",
        "type": "InvIT",
        "sub_type": "Power Transmission",
        "sponsor": "Sterlite Power",
        "sector": "Infrastructure",
    },
    "PGINVIT.NS": {
        "name": "PowerGrid Infrastructure InvIT",
        "type": "InvIT",
        "sub_type": "Power Transmission",
        "sponsor": "Power Grid Corporation",
        "sector": "Infrastructure",
    },
    "IRBINVIT.NS": {
        "name": "IRB InvIT Fund",
        "type": "InvIT",
        "sub_type": "Roads & Highways",
        "sponsor": "IRB Infrastructure",
        "sector": "Infrastructure",
    },
    "NHIT.NS": {
        "name": "National Highways Infra Trust",
        "type": "InvIT",
        "sub_type": "Roads & Highways",
        "sponsor": "NHAI",
        "sector": "Infrastructure",
    },
    "INDUSINVIT.NS": {
        "name": "Indus Infra Trust (formerly Bharat Highways InvIT)",
        "type": "InvIT",
        "sub_type": "Roads & Highways",
        "sponsor": "NHAI / MEP Infrastructure",
        "sector": "Infrastructure",
    },
    "RIIT.NS": {
        "name": "Raajmarg Infra Investment Trust",
        "type": "InvIT",
        "sub_type": "Roads & Highways",
        "sponsor": "NHAI",
        "sector": "Infrastructure",
    },
}

BENCHMARK_TICKER = "^NSEI"  # Nifty 50 as sector benchmark
