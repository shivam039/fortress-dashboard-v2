"""
ui/views/orders.py  —  Orders history view
==========================================
Renders the full filtered orders table with summary metrics.
"""

from __future__ import annotations

from typing import Dict, Optional

import streamlit as st

from ui.utils.formatting import format_timestamp  # type: ignore[import]


def render(username: str, sidebar_filters: Optional[Dict] = None) -> None:
    """Render the 📋 Orders module."""
    from utils.db import fetch_fortress_orders  # type: ignore[import]

    f = sidebar_filters or {}
    status_filter = f.get("status", "All")
    broker_filter = f.get("broker", "All")
    date_from = f.get("date_from", "").strip()
    date_to = f.get("date_to", "").strip()

    st.subheader("📋 Orders")
    st.caption("Filters are in the sidebar. Showing Fortress orders for your account.")

    orders_df = fetch_fortress_orders(
        username=username,
        status=status_filter,
        broker_name=broker_filter,
        date_from=date_from or None,
        date_to=date_to or None,
    )

    if orders_df.empty:
        st.info("No orders match the current filters.")
        return

    metric_col1, metric_col2, metric_col3 = st.columns(3)
    metric_col1.metric("Orders", len(orders_df))
    metric_col2.metric("Executed", int((orders_df["status"] == "Executed").sum()))
    metric_col3.metric("Pending", int((orders_df["status"] == "Pending").sum()))

    if "created_at" in orders_df.columns:
        orders_df["created_at"] = orders_df["created_at"].apply(format_timestamp)
    if "updated_at" in orders_df.columns:
        orders_df["updated_at"] = orders_df["updated_at"].apply(format_timestamp)

    st.dataframe(
        orders_df.rename(
            columns={
                "order_id": "Order ID",
                "symbol": "Symbol",
                "stock_name": "Stock Name",
                "order_type": "Order Type",
                "quantity": "Quantity",
                "price": "Price",
                "status": "Status",
                "broker_name": "Broker",
                "broker_order_id": "Broker Order ID",
                "notes": "Notes",
                "created_at": "Timestamp",
            }
        ),
        width="stretch",
        hide_index=True,
    )
