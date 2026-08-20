"""
ui/components/orders.py  —  Orders table component
===================================================
Renders the enhanced orders history table.
"""

from __future__ import annotations

import pandas as pd
import streamlit as st

from ui.utils.formatting import format_timestamp  # type: ignore[import]


def render_enhanced_orders_table(username: str) -> None:
    """Render the full orders table for *username*."""
    from utils.db import fetch_fortress_orders  # type: ignore[import]

    orders_df = fetch_fortress_orders(username=username)
    if orders_df.empty:
        empty_df = pd.DataFrame(
            columns=[
                "Order ID",
                "Symbol",
                "Type",
                "Qty",
                "Price",
                "Status",
                "Broker",
                "Time",
            ]
        )
        st.dataframe(empty_df, hide_index=True, use_container_width=True)
        return

    display_cols = [
        col
        for col in [
            "symbol",
            "order_type",
            "quantity",
            "price",
            "status",
            "broker_name",
            "created_at",
        ]
        if col in orders_df.columns
    ]
    if "created_at" in display_cols:
        orders_df["created_at"] = orders_df["created_at"].apply(format_timestamp)
    st.dataframe(
        orders_df[display_cols].rename(
            columns={
                "symbol": "Symbol",
                "order_type": "Type",
                "quantity": "Qty",
                "price": "Price",
                "status": "Status",
                "broker_name": "Broker",
                "created_at": "Timestamp",
            }
        ),
        width="stretch",
        hide_index=True,
    )
