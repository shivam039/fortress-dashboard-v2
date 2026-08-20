"""
ui/utils/telegram.py  —  Telegram alert helpers
================================================
Wrappers around engine/scripts/telegram_bot.py used from the UI layer.
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path
from typing import Any, Dict

import streamlit as st

_ROOT_DIR = Path(__file__).resolve().parents[2]
_ENGINE_SCRIPTS = str(_ROOT_DIR / "engine" / "scripts")

logger = logging.getLogger("fortress.ui.telegram")


def _ensure_scripts_path() -> None:
    if _ENGINE_SCRIPTS not in sys.path:
        sys.path.append(_ENGINE_SCRIPTS)


def send_telegram_tip(row_data: Any) -> bool:
    """
    Send a single stock tip to all configured Telegram subscribers.

    Returns *True* on success.
    """
    _ensure_scripts_path()
    try:
        import telegram_bot  # type: ignore[import]
        from telegram_bot import (
            format_telegram_message,
        )
        from telegram_bot import (
            send_telegram_message as _tg_send,  # type: ignore[import]
        )

        subscribers = st.session_state.get("telegram_subscribers", "").strip()
        if subscribers:
            telegram_bot.TELEGRAM_CHAT_ID = subscribers
        msg = format_telegram_message(row_data)
        return _tg_send(msg)
    except Exception as exc:
        logger.error("Telegram tip failed: %s", exc)
        st.error(f"Telegram error: {exc}")
        return False


def send_commodity_alert(commodity_name: str, row_data: Dict[str, Any]) -> bool:
    """Send a commodity Telegram alert. Returns *True* on success."""
    _ensure_scripts_path()
    try:
        import telegram_bot  # type: ignore[import]
        from telegram_bot import (  # type: ignore[import]
            format_commodity_message,
            send_telegram_message,
        )

        subscribers = st.session_state.get("telegram_subscribers", "").strip()
        if subscribers:
            telegram_bot.TELEGRAM_CHAT_ID = subscribers
        msg = format_commodity_message(row_data)
        return send_telegram_message(msg)
    except Exception as exc:
        logger.error("Commodity telegram alert failed: %s", exc)
        st.error(f"Telegram error: {exc}")
        return False


def render_subscriber_manager() -> None:
    """
    Render the Telegram subscriber management expander widget.

    Saves subscriber Chat IDs both to session state and to
    ``engine/scripts/telegram_subscribers.txt``.
    """
    with st.expander("📢 Telegram Alert Settings", expanded=False):
        st.caption(
            "Enter comma-separated Telegram Chat IDs below. "
            "To get a Chat ID: have the user message @fortress_screener_bot, then check "
            "`https://api.telegram.org/bot<TOKEN>/getUpdates` for their chat ID. "
            "For channels, add the bot as admin and use the channel's numeric ID (starts with -100)."
        )
        current_subs = st.session_state.get(
            "telegram_subscribers", "677141544,-1003933571318"
        )
        new_subs = st.text_area(
            "Chat IDs (comma-separated)",
            value=current_subs,
            key="tg_subs_input",
            height=80,
        )
        if st.button("💾 Save Subscriber List", use_container_width=True):
            st.session_state["telegram_subscribers"] = new_subs.strip()
            subs_file = _ROOT_DIR / "engine" / "scripts" / "telegram_subscribers.txt"
            try:
                subs_file.write_text(new_subs.strip(), encoding="utf-8")
                count = len([s for s in new_subs.split(",") if s.strip()])
                st.success(f"Saved {count} subscriber(s).")
            except Exception as exc:
                st.error(f"Could not save subscriber file: {exc}")
