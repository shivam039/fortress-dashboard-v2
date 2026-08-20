"""
=============================================================================
ui/state.py  —  Central Session-State Manager
=============================================================================
Single source of truth for every st.session_state key used across the app.

Usage
-----
    from ui.state import State

    # At top of every page / view:
    State.bootstrap()          # idempotent; safe to call on every re-run
    State.require_login()      # st.stop() if user is not authenticated

    # Typed helpers:
    State.set("active_module", "📊 Stock Screener")
    module = State.get("active_module")

    # Broker cache:
    names = State.get_active_broker_names(username)
    State.invalidate_broker_cache()
=============================================================================
"""

from __future__ import annotations

import os
from typing import Any, Dict, List

import streamlit as st

# ---------------------------------------------------------------------------
# App-wide constants
# ---------------------------------------------------------------------------

ENABLE_NEW_FEATURES: bool = False

DEFAULT_API_URL: str = (
    os.environ.get("FORTRESS_API_URL", "").strip() or "http://127.0.0.1:8000"
)

MF_JOB_OPTIONS: Dict[str, str] = {
    "Refresh NAV Cache": "refresh_nav",
    "Update Metrics": "update_metrics",
    "Full Refresh": "full_refresh",
    "Recalculate Rankings": "recalculate_rankings",
}

ORDER_STATUS_OPTIONS: List[str] = ["Pending", "Executed", "Rejected", "Cancelled"]

BROKER_OPTIONS: List[str] = ["Zerodha", "Dhan"]

BROKER_LOGIN_URLS: Dict[str, str] = {
    "Zerodha": "https://kite.zerodha.com/connect/login?api_key={api_key}&v=3",
    "Dhan": "https://api.dhan.co/v2/login",
}

BASE_MODULES: List[str] = [
    "🏠 Dashboard",
    "📊 Stock Screener",
    "📈 MF Lab",
    "📋 Orders",
    "🌍 Commodities",
    "⚡ Options",
    "🕐 Scan History",
]


# ---------------------------------------------------------------------------
# State manager
# ---------------------------------------------------------------------------


class State:
    """
    Thin, stateless wrapper around st.session_state.

    All methods are class-methods so callers never need to instantiate.
    """

    # ── Lifecycle ──────────────────────────────────────────────────────────

    @classmethod
    def bootstrap(cls) -> None:
        """
        Idempotent initialisation of every session-state key.

        Safe to call on every Streamlit re-run — setdefault means an already-
        set key is never overwritten.
        """
        ss = st.session_state

        ss.setdefault("ENABLE_NEW_FEATURES", ENABLE_NEW_FEATURES)
        ss.setdefault("logged_in", False)
        ss.setdefault("auth_error", "")
        ss.setdefault("current_user", "")
        ss.setdefault("current_user_profile", {})
        ss.setdefault("fastapi_url", DEFAULT_API_URL)
        # Repair blank/None values that may have survived between sessions
        if not str(ss.get("fastapi_url", "")).strip():
            ss["fastapi_url"] = DEFAULT_API_URL
        ss.setdefault("mf_job_controls_rendered", False)
        ss.setdefault("screener_results", [])
        ss.setdefault("screener_selected_broker", BROKER_OPTIONS[0])
        ss.setdefault("active_tab", "login")
        ss.setdefault("signup_notice", "")
        ss.setdefault("show_delete_confirm", False)
        ss.setdefault("active_module", BASE_MODULES[0])

    @classmethod
    def require_login(cls) -> None:
        """
        Guard: stop rendering if the user is not logged in.

        Call this at the top of any view or page that requires authentication.
        In the main app, the login screen is rendered before calling this, so
        the user will see the login form rather than a blank page.
        """
        if not st.session_state.get("logged_in", False):
            st.warning("Please log in to access this page.")
            st.stop()

    # ── Typed getters / setters ────────────────────────────────────────────

    @classmethod
    def get(cls, key: str, default: Any = None) -> Any:
        """Retrieve a value from session state."""
        return st.session_state.get(key, default)

    @classmethod
    def set(cls, key: str, value: Any) -> None:
        """Write a value to session state."""
        st.session_state[key] = value

    # ── Module helpers ─────────────────────────────────────────────────────

    @classmethod
    def available_modules(cls) -> List[str]:
        """Return the ordered list of sidebar modules for the current session."""
        modules = list(BASE_MODULES)
        if st.session_state.get("ENABLE_NEW_FEATURES", False):
            modules.insert(1, "👤 Profile")
        return modules

    # ── Broker cache helpers ───────────────────────────────────────────────

    @classmethod
    def get_active_broker_names(cls, username: str) -> List[str]:
        """
        Return active broker names for *username*.

        Result is cached in session state for the lifetime of the browser
        session.  Call ``invalidate_broker_cache()`` after any connect /
        disconnect action.
        """
        if "active_brokers_cache" not in st.session_state:
            from utils.db import list_user_broker_connections  # type: ignore[import]

            df = list_user_broker_connections(username)
            st.session_state["brokers_df_cache"] = df
            st.session_state["active_brokers_cache"] = (
                df[df["is_active"].astype(bool)]["broker_name"]
                .dropna()
                .astype(str)
                .tolist()
                if not df.empty
                else []
            )
        return st.session_state["active_brokers_cache"]

    @classmethod
    def invalidate_broker_cache(cls) -> None:
        """Force a fresh broker fetch on the next call to get_active_broker_names."""
        st.session_state.pop("active_brokers_cache", None)
        st.session_state.pop("brokers_df_cache", None)

    # ── Auth helpers ───────────────────────────────────────────────────────

    @classmethod
    def logout(cls) -> None:
        """Clear all session state and restart from the login screen."""
        fastapi_url = st.session_state.get("fastapi_url", DEFAULT_API_URL)
        for key in list(st.session_state.keys()):
            del st.session_state[key]
        cls.bootstrap()
        st.session_state["fastapi_url"] = fastapi_url
        st.rerun()
