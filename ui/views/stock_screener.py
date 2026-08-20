"""
ui/views/stock_screener.py  —  Stock Screener view
====================================================
Full stock screener: scan trigger, sector intelligence, momentum/LT splits,
full results table, Telegram tip, pick tracker, order form, and heatmap.
"""

from __future__ import annotations

import datetime
import logging
import time
from typing import Any, Dict, List, Optional

import matplotlib.pyplot as plt
import pandas as pd
import seaborn as sns
import streamlit as st

from ui.state import BROKER_OPTIONS, ORDER_STATUS_OPTIONS, State  # type: ignore[import]
from ui.utils.api import APIError, trigger_scan  # type: ignore[import]
from ui.utils.error_handling import error_boundary  # type: ignore[import]
from ui.utils.formatting import score_style  # type: ignore[import]
from ui.utils.scan import build_order_link, run_scan_directly
from ui.utils.telegram import (  # type: ignore[import]
    render_subscriber_manager,
    send_telegram_tip,
)

logger = logging.getLogger("fortress.ui.screener")


# ---------------------------------------------------------------------------
# Pick tracker helpers
# ---------------------------------------------------------------------------


@st.dialog("📌 Track Pick")
def _track_pick_dialog(uid: int, symbol: str, row_dict: Dict[str, Any]) -> None:
    st.write(f"**{symbol}**")
    entry = float(row_dict.get("Price", 0))
    t1 = float(row_dict.get("Target_10D", 0))
    sl = float(row_dict.get("Stop_Loss", 0))

    col1, col2, col3 = st.columns(3)
    col1.metric("Entry Price", f"₹{entry:.2f}")
    col2.metric("🎯 Target", f"₹{t1:.2f}")
    col3.metric("🛑 Stop Loss", f"₹{sl:.2f}")

    st.write("Timeframe: 10 trading days")
    pick_date = st.date_input(
        "Pick Date",
        value=datetime.date.today(),
        max_value=datetime.date.today(),
    )

    if st.button("✅ Confirm & Track", use_container_width=True, type="primary"):
        from scripts.pick_tracker import record_pick  # type: ignore[import]

        pick_dt = datetime.datetime.combine(pick_date, datetime.datetime.now().time())
        record_pick(uid, row_dict, pick_date=pick_dt)
        st.success(f"Tracked {symbol}!")
        time.sleep(1)
        st.rerun()


def _render_pick_tracker_section(
    username: str,
    display_df: pd.DataFrame,
    symbol_options: List[str],
) -> None:
    from utils.db import get_pick_outcome_summary  # type: ignore[import]
    from utils.db import (
        get_user_id_by_username,
        get_user_picks,
    )

    uid = get_user_id_by_username(username)
    if not uid:
        return

    st.markdown("#### 📌 Track a Pick")
    col1, col2 = st.columns([3, 1])
    with col1:
        track_symbol = st.selectbox(
            "Select Stock to Track", symbol_options, key="track_symbol_select"
        )
    with col2:
        st.write("")
        if st.button("📌 Track Selected", use_container_width=True):
            track_row = display_df[display_df["Symbol"] == track_symbol].iloc[0]
            _track_pick_dialog(uid, track_symbol, track_row.to_dict())

    st.markdown("#### 📊 My Picks")
    summary = get_pick_outcome_summary(uid)
    sc1, sc2, sc3, sc4 = st.columns(4)
    sc1.metric(
        "Win Rate",
        f"{summary['hit_rate']}%",
        f"{summary['hits']} Hits / {summary['misses']} Misses",
    )
    sc2.metric("Avg P&L", f"{summary['avg_pnl']}%")
    sc3.metric("Avg Days to Resolve", f"{summary['avg_days']}d")
    sc4.metric("Best Pick", f"{summary['best_pnl']}%")

    tab1, tab2 = st.tabs(["📈 Active Picks (Trailing)", "✅ Resolved Picks"])
    with tab1:
        active_picks = get_user_picks(uid, status="TRAILING")
        if active_picks.empty:
            st.info("No active picks trailing.")
        else:
            disp = active_picks[
                [
                    "symbol",
                    "pick_date",
                    "entry_price",
                    "target_price",
                    "stop_loss",
                    "max_price",
                    "min_price",
                    "pnl_pct",
                ]
            ].copy()
            disp["pick_date"] = pd.to_datetime(disp["pick_date"]).dt.strftime(
                "%Y-%m-%d"
            )
            st.dataframe(disp, hide_index=True, use_container_width=True)

    with tab2:
        resolved_picks = get_user_picks(uid)
        resolved_picks = resolved_picks[resolved_picks["outcome"] != "TRAILING"]
        if resolved_picks.empty:
            st.info("No resolved picks yet.")
        else:
            disp_r = resolved_picks[
                [
                    "symbol",
                    "pick_date",
                    "outcome",
                    "outcome_date",
                    "outcome_price",
                    "pnl_pct",
                    "days_to_resolve",
                ]
            ].copy()
            disp_r["pick_date"] = pd.to_datetime(disp_r["pick_date"]).dt.strftime(
                "%Y-%m-%d"
            )
            disp_r["outcome_date"] = pd.to_datetime(disp_r["outcome_date"]).dt.strftime(
                "%Y-%m-%d"
            )
            st.dataframe(disp_r, hide_index=True, use_container_width=True)


# ---------------------------------------------------------------------------
# Main view entry-point
# ---------------------------------------------------------------------------


def render(
    username: str,
    api_url: str,
    sidebar_filters: Optional[Dict] = None,
) -> None:
    """Render the 📊 Stock Screener module."""
    from stock_scanner.ui_helpers import prepare_screener_table  # type: ignore[import]
    from utils.db import create_fortress_order  # type: ignore[import]

    f = sidebar_filters or {}
    universe = f.get("universe", "NIFTY50")
    portfolio_val = f.get("portfolio_val", 1_000_000.0)
    risk_pct = f.get("risk_pct", 1.0)
    active_brokers = State.get_active_broker_names(username)
    broker_choices = active_brokers or BROKER_OPTIONS
    broker_name = f.get("broker", broker_choices[0])

    st.subheader("📊 Stock Screener")
    st.caption(
        "Scan controls are in the sidebar. Use Advanced Settings below for fine-tuning."
    )
    show_ai_score = True
    if st.session_state.get("ENABLE_NEW_FEATURES", False):
        show_ai_score = st.checkbox(
            "Show Fortress AI Score",
            value=True,
            help="Danelfin-inspired Fortress AI Score for momentum-quality ranking.",
        )

    # ── Advanced settings ─────────────────────────────────────────────────
    enable_regime = True
    liquidity_cr_min = 8.0
    market_cap_cr_min = 1500.0
    price_min = 80.0
    technical, fundamental, sentiment, context_w = 50, 25, 15, 10

    with st.expander("⚙️ Advanced Scan Settings", expanded=False):
        col_a, col_b, col_c, col_d = st.columns(4)
        with col_a:
            enable_regime = st.checkbox("Enable Regime Scaling", value=True)
        with col_b:
            liquidity_cr_min = st.number_input(
                "Liquidity Gate (₹ Cr)", min_value=0.0, value=8.0, step=0.5
            )
        with col_c:
            market_cap_cr_min = st.number_input(
                "Market Cap Gate (₹ Cr)", min_value=0.0, value=1500.0, step=50.0
            )
        with col_d:
            price_min = st.number_input(
                "Min Price Gate (₹)", min_value=0.0, value=80.0, step=5.0
            )
        w1, w2, w3, w4 = st.columns(4)
        with w1:
            technical = st.slider("Technical", 0, 100, 50, 1)
        with w2:
            fundamental = st.slider("Fundamental", 0, 100, 25, 1)
        with w3:
            sentiment = st.slider("Sentiment", 0, 100, 15, 1)
        with w4:
            context_w = st.slider("Context", 0, 100, 10, 1)

    # ── Run scan ─────────────────────────────────────────────────────────
    if st.button("🔍 Run Screener", type="primary", use_container_width=True):
        total = max(technical + fundamental + sentiment + context_w, 1)
        payload = {
            "universe": universe,
            "portfolio_val": portfolio_val,
            "risk_pct": risk_pct / 100.0,
            "weights": {
                "technical": technical / total,
                "fundamental": fundamental / total,
                "sentiment": sentiment / total,
                "context": context_w / total,
            },
            "enable_regime": enable_regime,
            "liquidity_cr_min": liquidity_cr_min,
            "market_cap_cr_min": market_cap_cr_min,
            "price_min": price_min,
            "broker": broker_name,
        }

        # ── FastAPI first, in-process fallback ─────────────────────────────
        try:
            with st.spinner("🔍 Scanning via FastAPI…"):
                records = trigger_scan(payload)
            st.session_state["screener_results"] = records
            st.session_state["screener_selected_broker"] = broker_name
            st.success(f"✅ Scan completed (FastAPI) — {len(records)} results.")
        except APIError:
            # Backend unreachable — run in-process
            try:
                with st.spinner("🔍 Running in-process scan (engine)…"):
                    records = run_scan_directly(payload)
                st.session_state["screener_results"] = records
                st.session_state["screener_selected_broker"] = broker_name
                st.success(f"✅ Scan completed (in-process) — {len(records)} results.")
            except Exception as exc:
                st.error(
                    f"❌ Scan failed: `{exc}`\n\n"
                    "Check that universe tickers are available and try again."
                )

    results = pd.DataFrame(st.session_state.get("screener_results", []))
    if results.empty:
        st.info("Run a scan to see actionable stock setups here.")
        return

    feature_ai_enabled = (
        st.session_state.get("ENABLE_NEW_FEATURES", False)
        and show_ai_score
        and "ai_score" in results.columns
    )
    if not feature_ai_enabled and "ai_score" in results.columns:
        results = results.drop(columns=["ai_score"])

    def _display_scan_table(df: pd.DataFrame) -> None:
        if df.empty:
            st.dataframe(df, width="stretch", hide_index=True)
            return
        table_df = prepare_screener_table(df, feature_ai_enabled)
        if (
            feature_ai_enabled
            and "AI Score" in table_df.columns
            and "Conviction Score" in table_df.columns
        ):
            styled = table_df.style.format(
                {"Conviction Score": "{:.1f}", "AI Score": "{:.1f}"}
            ).map(score_style, subset=["Conviction Score", "AI Score"])
            st.dataframe(styled, width="stretch", hide_index=True)
            return
        st.dataframe(table_df, width="stretch", hide_index=True)

    if "Quality_Gate_Pass" in results.columns:
        actionable_df = results[results["Quality_Gate_Pass"]].copy()
        filtered_out_df = results[~results["Quality_Gate_Pass"]].copy()
    else:
        actionable_df = results.copy()
        filtered_out_df = pd.DataFrame()

    # ── Sector intelligence ───────────────────────────────────────────────
    if not results.empty and "Sector" in results.columns:
        with error_boundary("Sector Intelligence"):
            st.markdown("#### 🔥 Sector Intelligence & Rotation")
            sector_df = results.copy()
            if "Velocity" not in sector_df.columns:
                sector_df["Velocity"] = pd.to_numeric(
                    sector_df.get("Ret_7D", 0), errors="coerce"
                ).fillna(0) - pd.to_numeric(
                    sector_df.get("Ret_30D", 0), errors="coerce"
                ).fillna(
                    0
                )
            sector_stats = (
                sector_df.groupby("Sector")
                .agg({"Velocity": "mean", "Above_EMA200": "mean", "Score": "mean"})
                .reset_index()
            )
            sector_stats["Breadth (%)"] = (sector_stats["Above_EMA200"] * 100).round(1)
            sector_stats["Avg Score"] = sector_stats["Score"].round(1)
            sector_stats["Velocity"] = sector_stats["Velocity"].round(2)

            def get_thesis(row: Any) -> str:
                if row["Score"] > 75 and row["Velocity"] > 0:
                    return "🐂 Bullish Accumulation"
                elif row["Score"] < 35 and row["Breadth (%)"] < 40:
                    return "❄️ Structural Weakness"
                elif row["Velocity"] > 2:
                    return "🚀 High Momentum"
                return "⚖️ Neutral / Rotation"

            sector_stats["Thesis"] = sector_stats.apply(get_thesis, axis=1)
            sector_stats["On the Rise"] = sector_stats.apply(
                lambda r: (
                    "🔥 YES" if r["Velocity"] > 0 and r["Breadth (%)"] > 70 else ""
                ),
                axis=1,
            )
            sector_stats["On the Fall"] = sector_stats.apply(
                lambda r: (
                    "❄️ YES" if r["Velocity"] < 0 or r["Breadth (%)"] < 40 else ""
                ),
                axis=1,
            )
            st.dataframe(
                sector_stats[
                    [
                        "Sector",
                        "Thesis",
                        "Velocity",
                        "Breadth (%)",
                        "Avg Score",
                        "On the Rise",
                        "On the Fall",
                    ]
                ].sort_values("Velocity", ascending=False),
                width="stretch",
                column_config={
                    "Velocity": st.column_config.NumberColumn(
                        "Momentum Vel", format="%.2f%%"
                    ),
                    "Breadth (%)": st.column_config.ProgressColumn(
                        "Inst. Breadth", min_value=0, max_value=100, format="%.1f%%"
                    ),
                    "Avg Score": st.column_config.ProgressColumn(
                        "Sector Strength", min_value=0, max_value=100
                    ),
                },
                hide_index=True,
            )

    # ── Strategic splits ──────────────────────────────────────────────────
    momentum_picks = actionable_df[actionable_df["Strategy"] == "Momentum Pick"].copy()
    lt_picks = actionable_df[actionable_df["Strategy"] == "Long-Term Pick"].copy()

    if not momentum_picks.empty:
        st.markdown(f"#### 🚀 Momentum Picks ({len(momentum_picks)})")
        if "Actions" in momentum_picks.columns:
            momentum_picks.drop(columns=["Actions"], inplace=True)
        _display_scan_table(momentum_picks)

    if not lt_picks.empty:
        st.markdown(f"#### 💎 Long-Term Picks ({len(lt_picks)})")
        if "Actions" in lt_picks.columns:
            lt_picks.drop(columns=["Actions"], inplace=True)
        _display_scan_table(lt_picks)

    # ── Full results ──────────────────────────────────────────────────────
    st.markdown("#### 📋 All Scan Results")
    display_df = results.copy()
    if "Actions" in display_df.columns:
        display_df = display_df.drop(columns=["Actions"])
    _display_scan_table(display_df)

    if not filtered_out_df.empty:
        with st.expander(
            f"Filtered Out ({len(filtered_out_df)}) - Hard Quality Gates",
            expanded=False,
        ):
            f_df = filtered_out_df.copy()
            if "Actions" in f_df.columns:
                f_df = f_df.drop(columns=["Actions"])
            _display_scan_table(f_df)

    symbol_options = (
        display_df["Symbol"].dropna().astype(str).tolist()
        if "Symbol" in display_df.columns
        else []
    )
    if not symbol_options:
        return

    # ── Telegram tip ──────────────────────────────────────────────────────
    st.markdown("#### ✈️ Send Telegram Alert")
    tip_col1, tip_col2 = st.columns([3, 1])
    with tip_col1:
        tip_symbol = st.selectbox(
            "Select Stock to Tip", symbol_options, key="tip_symbol_select"
        )
    with tip_col2:
        st.write("")
        if st.button(
            "📤 Send Tip Now",
            use_container_width=True,
            type="primary",
        ):
            tip_row = display_df[display_df["Symbol"] == tip_symbol].iloc[0]
            success = send_telegram_tip(tip_row)
            if success:
                st.success(f"✅ Tip sent for {tip_symbol}!")
                if username != "guest_user":
                    try:
                        from utils.db import (  # type: ignore[import]
                            get_user_id_by_username,
                        )

                        from scripts.pick_tracker import (  # type: ignore[import]
                            record_pick,
                        )

                        uid = get_user_id_by_username(username)
                        if uid:
                            record_pick(uid, tip_row.to_dict())
                            st.info(f"📌 Pick auto-tracked for {tip_symbol}")
                    except Exception as exc:
                        logger.debug("Auto-track on tip failed: %s", exc)
            else:
                st.error("Failed to send tip. Check Telegram settings below.")

    render_subscriber_manager()
    st.markdown("---")

    # ── Pick tracker ──────────────────────────────────────────────────────
    if username != "guest_user":
        _render_pick_tracker_section(username, display_df, symbol_options)

    st.markdown("---")

    # ── Record order ──────────────────────────────────────────────────────
    st.markdown("#### Record Order From Fortress")
    with st.form("fortress_order_form"):
        selected_symbol = st.selectbox("Symbol", symbol_options)
        selected_row = display_df[display_df["Symbol"] == selected_symbol].iloc[0]
        order_cols = st.columns(4)
        with order_cols[0]:
            order_type = st.selectbox("Order Type", ["Buy", "Sell"])
        with order_cols[1]:
            quantity = st.number_input(
                "Quantity",
                min_value=1.0,
                value=float(selected_row.get("Position_Qty", 1) or 1),
                step=1.0,
            )
        with order_cols[2]:
            price = st.number_input(
                "Price",
                min_value=0.0,
                value=float(selected_row.get("Price", 0) or 0),
                step=1.0,
            )
        with order_cols[3]:
            status = st.selectbox("Status", ORDER_STATUS_OPTIONS)
        notes = st.text_input("Notes", value=str(selected_row.get("Strategy", "")))
        submitted = st.form_submit_button(
            "Save Order", type="primary", use_container_width=True
        )

    broker_link = build_order_link(selected_symbol, quantity, price, broker_name)
    if broker_link and username != "guest_user":
        st.link_button("Open Broker Order Page", broker_link, use_container_width=False)

    # ── Conviction heatmap ────────────────────────────────────────────────
    if not results.empty and "Score" in results.columns:
        st.subheader("📊 Conviction Heatmap")
        results["Score"] = pd.to_numeric(results["Score"], errors="coerce").fillna(0)

        def get_band(x: float) -> str:
            if x >= 85:
                return "🔥 High (85+)"
            if x >= 60:
                return "🚀 Pass (60-85)"
            return "🟡 Watch (<60)"

        heatmap_df = results[["Symbol", "Score"]].copy()
        heatmap_df["Conviction_Band"] = heatmap_df["Score"].apply(get_band)
        pivot = heatmap_df.pivot_table(
            index="Symbol",
            columns="Conviction_Band",
            values="Score",
            fill_value=0,
        )
        for col in ["🔥 High (85+)", "🚀 Pass (60-85)", "🟡 Watch (<60)"]:
            if col not in pivot.columns:
                pivot[col] = 0.0
        pivot = pivot[["🔥 High (85+)", "🚀 Pass (60-85)", "🟡 Watch (<60)"]]
        plt.figure(figsize=(10, max(4, len(results) / 3)))
        sns.heatmap(
            pivot,
            annot=True,
            cmap="Greens",
            cbar=False,
            linewidths=0.5,
            linecolor="grey",
        )
        st.pyplot(plt)

    if submitted:
        create_fortress_order(
            username=username,
            symbol=selected_symbol,
            stock_name=str(selected_row.get("Company", selected_symbol)),
            order_type=order_type,
            quantity=quantity,
            price=price,
            status=status,
            broker_name=broker_name,
            notes=notes,
        )
        st.success(f"Order for {selected_symbol} saved to Fortress order history.")
