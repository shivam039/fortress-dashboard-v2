"""
ui/views/options.py  —  Options view
=====================================
Delegates rendering to the engine's options_algo.ui module.
"""

from __future__ import annotations

import importlib
from typing import Optional

import streamlit as st

from ui.state import BROKER_OPTIONS, State  # type: ignore[import]


def render(username: str, broker: Optional[str] = None) -> None:
    """Render the ⚡ Options module."""
    options_ui = importlib.import_module("options_algo.ui")
    active_brokers = State.get_active_broker_names(username)
    broker_name = broker or (active_brokers[0] if active_brokers else BROKER_OPTIONS[0])

    st.subheader("⚡ Options")
    if username != "guest_user":
        st.caption(f"Broker: **{broker_name}** — change in the sidebar.")
    options_ui.render(broker_name)
