"""
reit_invits/universe.py
=======================
Static universe of tradeable Indian REITs and InvITs on NSE/BSE.
Yahoo Finance tickers use the .NS suffix.
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
    "BROOKFIELD.NS": {
        "name": "Brookfield India Real Estate Trust",
        "type": "REIT",
        "sub_type": "Office",
        "sponsor": "Brookfield Asset Management",
        "sector": "Real Estate",
    },
    "NEXUSMALLS.NS": {
        "name": "Nexus Select Trust",
        "type": "REIT",
        "sub_type": "Retail Mall",
        "sponsor": "Nexus Malls / Blackstone",
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
    "POWERTRAN.NS": {
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
    "NHAI.NS": {
        "name": "National Highways Infra Trust",
        "type": "InvIT",
        "sub_type": "Roads & Highways",
        "sponsor": "NHAI",
        "sector": "Infrastructure",
    },
    "BHINVIT.NS": {
        "name": "Bharat Highways InvIT",
        "type": "InvIT",
        "sub_type": "Roads & Highways",
        "sponsor": "NHAI / MEP Infrastructure",
        "sector": "Infrastructure",
    },
}

BENCHMARK_TICKER = "^NSEI"  # Nifty 50 as sector benchmark
