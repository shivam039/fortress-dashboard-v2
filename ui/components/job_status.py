"""
ui/components/job_status.py  —  Background MF Job Status Indicator
====================================================================
Tracks and displays the state of in-process (background thread) MF jobs.
Renders a compact status badge and a detailed status panel.

Session-state keys managed here:
  ``_mf_job_running``       bool  — True while a job thread is alive
  ``_mf_job_label``         str   — Display name of the current job
  ``_mf_job_started_at``    float — Unix timestamp when job started
  ``_mf_job_last_result``   dict  — Last completed result dict
  ``_mf_job_last_error``    str   — Last error message (or empty string)
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Any, Dict, Optional

import streamlit as st

logger = logging.getLogger("fortress.ui.job_status")

# ---------------------------------------------------------------------------
# Job launcher — wraps in-process execution with status tracking
# ---------------------------------------------------------------------------


def launch_mf_job(
    payload: Dict[str, Any],
    label: str = "MF Job",
) -> None:
    """
    Dispatch an MF job to a daemon thread and update session-state status.

    Args:
        payload: The job payload dict (job_type, force_refresh, scheme_codes).
        label:   Human-readable job name for the status display.
    """
    from mf_lab.jobs import _run_job_sync  # type: ignore[import]

    st.session_state["_mf_job_running"] = True
    st.session_state["_mf_job_label"] = label
    st.session_state["_mf_job_started_at"] = time.time()
    st.session_state["_mf_job_last_error"] = ""

    def _target() -> None:
        try:
            result = _run_job_sync(
                job_type=payload["job_type"],
                force_refresh=payload.get("force_refresh", False),
                scheme_codes=payload.get("scheme_codes"),
            )
            # Thread cannot write directly to st.session_state safely,
            # so we write to a thread-local dict that the main thread
            # reads on next re-run via a Streamlit cache trick.
            _JOB_RESULTS["last_result"] = result
            _JOB_RESULTS["last_error"] = ""
            _JOB_RESULTS["running"] = False
            logger.info("MF job '%s' completed: %s", payload["job_type"], result)
        except Exception as exc:
            _JOB_RESULTS["last_error"] = str(exc)
            _JOB_RESULTS["running"] = False
            logger.error("MF job '%s' failed: %s", payload["job_type"], exc)

    _JOB_RESULTS["running"] = True
    thread = threading.Thread(target=_target, daemon=True, name=f"mf-job-{label}")
    thread.start()


# Module-level store — written by the worker thread, read by main thread.
# Streamlit session_state is NOT safe to write from worker threads.
_JOB_RESULTS: Dict[str, Any] = {
    "running": False,
    "last_result": None,
    "last_error": "",
}


def _sync_from_thread() -> None:
    """Pull results from the thread store into session state on each re-run."""
    running = _JOB_RESULTS.get("running", False)
    was_running = st.session_state.get("_mf_job_running", False)

    if was_running and not running:
        # Job just finished
        st.session_state["_mf_job_running"] = False
        st.session_state["_mf_job_last_result"] = _JOB_RESULTS.get("last_result")
        st.session_state["_mf_job_last_error"] = _JOB_RESULTS.get("last_error", "")


# ---------------------------------------------------------------------------
# Status rendering
# ---------------------------------------------------------------------------


def render_job_status_badge() -> None:
    """
    Render a compact inline status badge.

    Call this at the top of the MF Lab view or in the sidebar.
    """
    _sync_from_thread()

    running = st.session_state.get("_mf_job_running", False)
    label = st.session_state.get("_mf_job_label", "")
    started_at: Optional[float] = st.session_state.get("_mf_job_started_at")
    last_result: Optional[Dict] = st.session_state.get("_mf_job_last_result")
    last_error: str = st.session_state.get("_mf_job_last_error", "")

    if running:
        elapsed = int(time.time() - started_at) if started_at else 0
        st.info(
            f"⏳ **{label}** running… ({elapsed}s elapsed)\n\n"
            "This runs in the background — you can navigate away and come back.",
            icon="🔄",
        )
        # Auto-refresh every 3 seconds while job is running
        st.markdown(
            "<meta http-equiv='refresh' content='3'>",
            unsafe_allow_html=True,
        )
    elif last_error:
        st.error(f"❌ **Last job failed:** `{last_error}`")
    elif last_result is not None:
        processed = last_result.get("processed", last_result.get("refreshed", "?"))
        st.success(
            f"✅ **{label or 'Job'}** completed — {processed} schemes processed."
        )


def render_job_status_panel() -> None:
    """
    Render the full job status panel in an expander.

    Includes running indicator, last result, and last error.
    """
    _sync_from_thread()

    running = st.session_state.get("_mf_job_running", False)
    label = st.session_state.get("_mf_job_label", "")
    started_at: Optional[float] = st.session_state.get("_mf_job_started_at")
    last_result: Optional[Dict] = st.session_state.get("_mf_job_last_result")
    last_error: str = st.session_state.get("_mf_job_last_error", "")

    with st.expander(
        "📊 Job Status"
        + (" 🔄" if running else (" ✅" if last_result and not last_error else "")),
        expanded=running,
    ):
        if running:
            elapsed = int(time.time() - started_at) if started_at else 0
            st.info(f"**{label}** is running… ({elapsed}s elapsed)")
            col1, col2 = st.columns([3, 1])
            with col2:
                if st.button("🔄 Refresh Status", use_container_width=True):
                    st.rerun()
        elif last_error:
            st.error(f"**Last job failed:** {last_error}")
        elif last_result is not None:
            st.success("**Last job completed successfully.**")
            for k, v in last_result.items():
                st.write(f"- **{k.replace('_', ' ').title()}:** {v}")
        else:
            st.caption("No jobs have run in this session yet.")
