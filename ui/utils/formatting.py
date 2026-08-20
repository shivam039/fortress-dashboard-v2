"""
ui/utils/formatting.py  —  Pure formatting helpers
===================================================
No Streamlit widgets here — only pure Python functions that transform
data for display.  Import freely from views, components, or tests.
"""

from __future__ import annotations

from typing import Any, Tuple

import pandas as pd


def format_timestamp(value: Any) -> str:
    """Return a human-readable timestamp string in IST, or 'N/A'."""
    if value in (None, "", pd.NaT):
        return "N/A"
    parsed = pd.to_datetime(value, errors="coerce")
    if pd.isna(parsed):
        return str(value)
    if parsed.tzinfo is None:
        return parsed.strftime("%Y-%m-%d %H:%M:%S")
    return parsed.tz_convert("Asia/Kolkata").strftime("%Y-%m-%d %H:%M:%S IST")


def check_token_expiry(expires_at_raw: Any) -> Tuple[str, str]:
    """
    Return *(badge_text, color)* based on token expiry date.

    Returns empty strings when no expiry is set.
    """
    if not expires_at_raw or str(expires_at_raw).strip() in ("", "None", "nan"):
        return ("", "")
    try:
        exp = pd.to_datetime(expires_at_raw, errors="coerce")
        if pd.isna(exp):
            return ("", "")
        now = pd.Timestamp.now(tz=exp.tzinfo)
        days_left = (exp - now).days
        if days_left < 0:
            return ("🔴 Token Expired", "#ff4b4b")
        elif days_left <= 2:
            return (f"🟠 Expires in {days_left}d", "#ffa500")
        elif days_left <= 7:
            return (f"🟡 Expires in {days_left}d", "#f0c040")
        else:
            return (f"🟢 Valid ({days_left}d)", "#00c851")
    except Exception:
        return ("", "")


def score_style(value: Any) -> str:
    """
    CSS style string for conviction-score cells in a styled DataFrame.

    Usage: ``df.style.map(score_style, subset=["Conviction Score"])``
    """
    try:
        val = float(value)
    except Exception:
        return ""
    if val >= 85:
        return "background-color: #d9f2d9; color: #0f5132; font-weight: 700;"
    if val >= 70:
        return "background-color: #e9f9e9; color: #1f7a1f; font-weight: 600;"
    return ""
