"""
ui/views/mf_lab.py  —  Mutual Fund Lab view
============================================
Renders the MF Lab dashboard with:
- Background job status indicator (refresh indicator)
- Job controls with FastAPI → in-process fallback
- Fund analysis via engine's mf_lab.ui module

Business logic stays in the engine layer (mf_lab.jobs, mf_lab.logic).
This file only orchestrates rendering.
"""

from __future__ import annotations

import importlib
from typing import Any, Dict, List

import streamlit as st

from ui.components.job_status import launch_mf_job  # type: ignore[import]
from ui.components.job_status import (
    render_job_status_badge,
    render_job_status_panel,
)
from ui.state import MF_JOB_OPTIONS  # type: ignore[import]
from ui.utils.api import APIError, trigger_mf_job  # type: ignore[import]
from ui.utils.error_handling import error_boundary  # type: ignore[import]


def _build_payload(
    job_label: str,
    force_refresh: bool,
    scheme_code_text: str,
) -> Dict[str, Any]:
    """Build the MF job payload from form inputs."""
    scheme_codes: List[str] = [
        code.strip() for code in scheme_code_text.split(",") if code.strip()
    ]
    return {
        "job_type": MF_JOB_OPTIONS[job_label],
        "force_refresh": force_refresh,
        "scheme_codes": scheme_codes,
    }


def _render_job_controls(api_url: str, key_prefix: str = "mf_main") -> None:
    """
    Render MF job trigger controls — FastAPI first, in-process fallback.

    Separated from the main render() so it can be tested independently.

    Args:
        api_url:    Backend URL (unused when api.py resolves from session state).
        key_prefix: Unique prefix to avoid Streamlit duplicate-key errors.
    """
    st.markdown("### ⚙️ Server-Side MF Data Jobs")
    st.caption(
        "Heavy MF processing runs in the background so the UI stays responsive. "
        "Job status appears below after triggering."
    )

    with st.form(f"{key_prefix}_form"):
        col_a, col_b = st.columns([2, 1])
        with col_a:
            job_label = st.selectbox(
                "Job Type",
                list(MF_JOB_OPTIONS.keys()),
                key=f"{key_prefix}_job_type",
            )
        with col_b:
            force_refresh = st.checkbox(
                "Force Refresh",
                value=False,
                key=f"{key_prefix}_force_refresh",
                help="Bypass the NAV cache and fetch fresh data from MFAPI.",
            )
        scheme_code_text = st.text_input(
            "Scheme Codes (optional, comma-separated)",
            key=f"{key_prefix}_scheme_codes",
            placeholder="e.g. 120503, 120716 — leave blank for all",
        )
        submitted = st.form_submit_button(
            "🚀 Trigger Job", type="primary", use_container_width=True
        )

    if submitted:
        payload = _build_payload(job_label, force_refresh, scheme_code_text)

        # ── Try FastAPI first ───────────────────────────────────────────────
        try:
            msg = trigger_mf_job(payload)
            st.success(f"✅ `{payload['job_type']}` accepted by FastAPI: {msg}")
        except APIError:
            # FastAPI not reachable — run in-process background thread
            launch_mf_job(payload, label=job_label)
            st.info(
                f"⏳ `{payload['job_type']}` started in-process (background thread). "
                "Status updates will appear below.",
                icon="🔄",
            )


def render(api_url: str) -> None:
    """
    Render the 📈 MF Lab module.

    Args:
        api_url: The backend FastAPI URL (used only if api.py cannot resolve
                 it from session state, which is always set at this point).
    """
    mf_lab_ui = importlib.import_module("mf_lab.ui")

    st.subheader("📈 MF Lab")
    st.caption(
        "Quantitative mutual fund analysis. Trigger data jobs in the sidebar "
        "or below, then explore fund rankings and backtest results."
    )

    # ── Background job status banner ──────────────────────────────────────
    render_job_status_badge()

    # ── Job controls (shown in main area when ENABLE_NEW_FEATURES is set) ─
    if st.session_state.get("ENABLE_NEW_FEATURES", False):
        with st.expander("⚙️ Trigger MF Data Job", expanded=False):
            _render_job_controls(api_url)
        st.session_state["mf_job_controls_rendered"] = True

    # ── Detailed job status panel ─────────────────────────────────────────
    render_job_status_panel()

    st.markdown("---")

    # ── Fund analysis (delegated to engine layer) ─────────────────────────
    with error_boundary("MF Fund Analysis"):
        mf_lab_ui.render()
