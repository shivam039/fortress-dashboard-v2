"""
ui/views/dashboard.py  —  Dashboard overview view
==================================================
Renders the main landing page after login: metrics, profile snapshot,
and recent orders summary.
"""

from __future__ import annotations

from typing import Any, Dict

import pandas as pd
import streamlit as st

from ui.utils.formatting import format_timestamp  # type: ignore[import]


def render(profile: Dict[str, Any], username: str) -> None:
    """Render the 🏠 Dashboard module."""
    from utils.db import fetch_fortress_orders  # type: ignore[import]
    from utils.db import (
        list_user_broker_connections,
    )

    brokers_df = list_user_broker_connections(username)
    orders_df = fetch_fortress_orders(username)
    is_guest = username == "guest_user"

    st.subheader("Dashboard")
    st.caption(
        "Quick overview of your Fortress workspace, broker connectivity, "
        "and recent order flow."
    )

    col1, col2, col3, col4 = st.columns(4)
    if not is_guest:
        col1.metric(
            "Active Brokers",
            (
                int(brokers_df["is_active"].astype(bool).sum())
                if not brokers_df.empty
                else 0
            ),
        )
    else:
        col1.metric("Account Type", "Guest Explorer")
    col2.metric("Total Orders", len(orders_df))
    col3.metric(
        "Pending Orders",
        int((orders_df["status"] == "Pending").sum()) if not orders_df.empty else 0,
    )
    col4.metric("Account Status", profile.get("account_status", "Active"))

    left, right = st.columns([1.2, 1])
    with left:
        st.markdown("#### Profile Snapshot")
        summary_df = pd.DataFrame(
            [
                {"Field": "Full Name", "Value": profile.get("full_name") or "N/A"},
                {"Field": "Email", "Value": profile.get("email") or "N/A"},
                {"Field": "Phone", "Value": profile.get("phone") or "N/A"},
                {
                    "Field": "Last Login",
                    "Value": format_timestamp(profile.get("last_login_at")),
                },
            ]
        )
        st.dataframe(summary_df, width="stretch", hide_index=True)

    with right:
        st.markdown("#### Recent Orders")
        if orders_df.empty:
            st.info("No orders recorded yet.")
        else:
            preview_cols = [
                c
                for c in [
                    "order_id",
                    "symbol",
                    "order_type",
                    "quantity",
                    "status",
                    "broker_name",
                    "created_at",
                ]
                if c in orders_df.columns
            ]
            st.dataframe(
                orders_df[preview_cols].head(8), width="stretch", hide_index=True
            )
