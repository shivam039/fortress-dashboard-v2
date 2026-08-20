"""
ui/views/commodities.py  —  Commodities view
=============================================
Delegates rendering to the engine's commodities.ui module and appends
a Telegram alert widget.
"""

from __future__ import annotations

import importlib
from typing import Optional

import streamlit as st

from ui.state import BROKER_OPTIONS, State  # type: ignore[import]
from ui.utils.telegram import send_commodity_alert  # type: ignore[import]


def render(username: str, broker: Optional[str] = None) -> None:
    """Render the 🌍 Commodities module."""
    commodities_ui = importlib.import_module("commodities.ui")
    active_brokers = State.get_active_broker_names(username)
    broker_name = broker or (active_brokers[0] if active_brokers else BROKER_OPTIONS[0])

    st.subheader("🌍 Commodities")
    if username != "guest_user":
        st.caption(f"Broker: **{broker_name}** — change in the sidebar.")
    commodities_ui.render(broker_name)

    # ── Telegram alert ─────────────────────────────────────────────────────
    st.markdown("---")
    st.markdown("#### ✈️ Send Commodity Telegram Alert")
    commodity_options = ["Gold", "Silver", "Crude", "Copper"]
    tip_col1, tip_col2 = st.columns([3, 1])
    with tip_col1:
        selected_commodity = st.selectbox(
            "Select Commodity to Alert",
            commodity_options,
            key="commodity_tip_select",
        )
    with tip_col2:
        st.write("")
        if st.button(
            "📤 Send Alert Now",
            use_container_width=True,
            type="primary",
            key="send_commodity_tip",
        ):
            try:
                from commodities.logic import (  # type: ignore[import]
                    build_commodities_frame,
                )

                with st.spinner(f"Fetching {selected_commodity} data..."):
                    df = build_commodities_frame(selected_commodity)
                if df.empty:
                    st.error(f"No data available for {selected_commodity}.")
                else:
                    row = df.iloc[0]
                    success = send_commodity_alert(selected_commodity, row)
                    if success:
                        st.success(f"✅ {selected_commodity} alert sent!")
                    else:
                        st.error("Failed to send alert.")
            except Exception as exc:
                st.error(f"Error: {exc}")
