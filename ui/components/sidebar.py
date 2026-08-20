"""
ui/components/sidebar.py  —  Sidebar navigation & contextual filters
=====================================================================
Renders the authenticated sidebar:
  - Navigation radio with grouped modules
  - System status strip (scheduler, API connectivity)
  - Per-module contextual filter controls
  - MF job controls widget

All business-logic API calls go through ``ui.utils.api``.
"""

from __future__ import annotations

from typing import Dict

import streamlit as st

from ui.state import MF_JOB_OPTIONS  # type: ignore[import]
from ui.state import (
    BROKER_OPTIONS,
    ORDER_STATUS_OPTIONS,
    State,
)
from ui.utils.api import APIError, is_reachable, trigger_mf_job  # type: ignore[import]

# ---------------------------------------------------------------------------
# System status strip
# ---------------------------------------------------------------------------


def render_system_status() -> None:
    """
    Render a compact system status line in the sidebar.

    Shows API connectivity and scheduler state at a glance.
    """
    api_ok = is_reachable()
    api_badge = "🟢 API" if api_ok else "🔴 API offline"

    try:
        from scripts.scheduler import _scheduler_started  # type: ignore[import]

        sched_badge = "🟢 Scheduler" if _scheduler_started else "⏸️ Scheduler"
    except Exception:
        sched_badge = "⏸️ Scheduler"

    # Compact row
    col1, col2 = st.columns(2)
    col1.markdown(
        f'<span style="font-size:0.72em;color:#aaa;">{api_badge}</span>',
        unsafe_allow_html=True,
    )
    col2.markdown(
        f'<span style="font-size:0.72em;color:#aaa;">{sched_badge}</span>',
        unsafe_allow_html=True,
    )


# ---------------------------------------------------------------------------
# MF job controls widget
# ---------------------------------------------------------------------------


def render_mf_job_controls(
    api_url: str, key_prefix: str, sidebar: bool = False
) -> None:
    """
    Render MF data job trigger controls.

    When *sidebar* is True the widgets are placed in ``st.sidebar``; otherwise
    they are rendered inline in the main content area.

    Args:
        api_url:    Backend URL (kept for backward compat; api.py reads from session state).
        key_prefix: Unique prefix to avoid Streamlit duplicate-key errors.
        sidebar:    If True, render into the sidebar container.
    """
    from ui.components.job_status import launch_mf_job  # type: ignore[import]

    target = st.sidebar if sidebar else st
    target.markdown("**MF Data Jobs**" if sidebar else "### Server-Side MF Data Jobs")
    target.caption(
        "Trigger heavy MF processing. Runs in-process when FastAPI is offline."
    )

    job_label = target.selectbox(
        "Job Type", list(MF_JOB_OPTIONS.keys()), key=f"{key_prefix}_job_type"
    )
    force_refresh = target.checkbox(
        "Force Refresh",
        value=False,
        key=f"{key_prefix}_force_refresh",
        help="Bypass the NAV cache and fetch fresh data from MFAPI.",
    )
    scheme_code_text = target.text_input(
        "Scheme Codes (optional)",
        key=f"{key_prefix}_scheme_codes",
        placeholder="e.g. 120503, 120716",
    )

    if target.button(
        "🚀 Trigger Job",
        type="primary",
        use_container_width=True,
        key=f"{key_prefix}_trigger_button",
    ):
        scheme_codes = [c.strip() for c in scheme_code_text.split(",") if c.strip()]
        payload = {
            "job_type": MF_JOB_OPTIONS[job_label],
            "force_refresh": force_refresh,
            "scheme_codes": scheme_codes,
        }

        # ── FastAPI first, then in-process ─────────────────────────────────
        try:
            msg = trigger_mf_job(payload)
            target.success(f"✅ `{payload['job_type']}` accepted (FastAPI): {msg}")
        except APIError:
            launch_mf_job(payload, label=job_label)
            target.info(
                f"⏳ `{payload['job_type']}` started in-process (background thread).",
                icon="🔄",
            )


# ---------------------------------------------------------------------------
# Module-specific sidebar filters
# ---------------------------------------------------------------------------


def render_module_filters(module: str, username: str, api_url: str) -> Dict:
    """
    Render contextual filter controls for the currently active *module*.

    Returns a dict of filter values that views should consume.

    Args:
        module:   Active module name (e.g. "📊 Stock Screener").
        username: Current logged-in username.
        api_url:  Backend URL (passed to universe fetch).
    """
    from ui.utils.api import fetch_universes  # type: ignore[import]

    filters: Dict = {}
    is_guest = username == "guest_user"

    if module == "📊 Stock Screener":
        st.markdown("**Scan Controls**")

        # Universe list (cached, fast)
        with st.spinner("Loading universes…"):
            universes = fetch_universes()

        active_brokers = State.get_active_broker_names(username)
        broker_choices = active_brokers or BROKER_OPTIONS
        default_broker = st.session_state.get(
            "screener_selected_broker", broker_choices[0]
        )
        if default_broker not in broker_choices:
            default_broker = broker_choices[0]

        filters["universe"] = st.selectbox("Universe", universes, key="sb_universe")
        filters["portfolio_val"] = st.number_input(
            "Portfolio (₹)",
            min_value=100_000.0,
            value=1_000_000.0,
            step=50_000.0,
            key="sb_portfolio_val",
        )
        filters["risk_pct"] = st.number_input(
            "Risk %",
            min_value=0.1,
            value=1.0,
            step=0.1,
            format="%.1f",
            key="sb_risk_pct",
        )
        if not is_guest:
            filters["broker"] = st.selectbox(
                "Broker",
                broker_choices,
                index=broker_choices.index(default_broker),
                key="sb_broker",
            )
        else:
            filters["broker"] = broker_choices[0]

    elif module == "📈 MF Lab":
        render_mf_job_controls(api_url, key_prefix="mf_sidebar", sidebar=True)

    elif module == "📋 Orders":
        st.markdown("**Order Filters**")
        active_brokers = State.get_active_broker_names(username)
        broker_filter_options = ["All"] + sorted(set(active_brokers + BROKER_OPTIONS))
        filters["status"] = st.selectbox(
            "Status", ["All"] + ORDER_STATUS_OPTIONS, key="sb_order_status"
        )
        if not is_guest:
            filters["broker"] = st.selectbox(
                "Broker", broker_filter_options, key="sb_order_broker"
            )
        else:
            filters["broker"] = "All"
        filters["date_from"] = st.text_input(
            "From Date", key="sb_date_from", placeholder="2026-04-01"
        )
        filters["date_to"] = st.text_input(
            "To Date", key="sb_date_to", placeholder="2026-04-30"
        )

    elif module in ("🌍 Commodities", "⚡ Options"):
        active_brokers = State.get_active_broker_names(username)
        broker_choices = active_brokers or BROKER_OPTIONS
        safe_key = module.replace(" ", "_").replace("🌍", "com").replace("⚡", "opt")
        if not is_guest:
            filters["broker"] = st.selectbox(
                "Broker", broker_choices, key=f"sb_{safe_key}_broker"
            )
        else:
            filters["broker"] = broker_choices[0]

    return filters
