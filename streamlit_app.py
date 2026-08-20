"""
=============================================================================
                          AI AGENT DOORSTEP PROTOCOL
=============================================================================
ATTENTION ALL AI AGENTS (Jules, Codex, Claude, Grok, etc.):
Before modifying this file or any file in this project, you MUST read and
adhere to the mandatory checklist in `AI_AGENT_PROTOCOL.md` located in the
repository root.

All code changes MUST be explicitly logged to `logs/ai_audit_log.jsonl` using
the helper functions in `engine/utils/ai_audit.py`.

This is a strict requirement to prevent context washout and careless edits.
=============================================================================

streamlit_app.py  —  Application entry point  (~80 lines)
==========================================================
This file is intentionally minimal.  All business logic, UI components,
and view rendering live under the ``ui/`` package:

  ui/state.py          Central session-state manager & app-wide constants
  ui/components/       Reusable widgets (auth, broker, orders, profile, sidebar)
  ui/utils/            Pure helpers — formatting, scan runners, telegram
  ui/views/            One render() entry-point per dashboard module
"""

import importlib
import logging
import os
import sys
from pathlib import Path

import streamlit as st

# ---------------------------------------------------------------------------
# Path setup — must run before any engine imports
# ---------------------------------------------------------------------------
ROOT_DIR = Path(__file__).resolve().parent
ENGINE_DIR = ROOT_DIR / "engine"
for _p in (str(ENGINE_DIR), str(ROOT_DIR)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

# Pre-load engine packages to avoid Python 3.13 Streamlit concurrent-reload issues
for _pkg in [
    "utils",
    "mf_lab",
    "stock_scanner",
    "options_algo",
    "commodities",
    "fortress_config",
]:
    if _pkg not in sys.modules:
        try:
            importlib.import_module(_pkg)
        except Exception as _e:
            logging.getLogger("fortress").debug(
                "Pre-loading %s failed or skipped: %s", _pkg, _e
            )

# ---------------------------------------------------------------------------
# Page config — must be the first Streamlit call
# ---------------------------------------------------------------------------
st.set_page_config(page_title="Fortress 95 Pro", layout="wide")

# ---------------------------------------------------------------------------
# Bootstrap session state & database
# ---------------------------------------------------------------------------
from ui.state import State  # noqa: E402 — after sys.path setup

State.bootstrap()

if not st.session_state.get("_db_initialized"):
    from utils.db import init_db  # noqa: E402

    init_db()
    st.session_state["_db_initialized"] = True

# ---------------------------------------------------------------------------
# Background scheduler (idempotent — starts threads once per process)
# ---------------------------------------------------------------------------
try:
    from scripts.scheduler import start_scheduler  # noqa: E402

    if start_scheduler():
        logging.getLogger("fortress").info("Background scheduler initialized.")
except Exception as _sched_err:
    logging.getLogger("fortress").warning(f"Scheduler start skipped: {_sched_err}")

# ---------------------------------------------------------------------------
# Auth gate
# ---------------------------------------------------------------------------
if not st.session_state["logged_in"]:
    from ui.components.auth import render_login_screen  # noqa: E402

    render_login_screen()
    st.stop()

import ui.views.commodities as _v_commodities  # noqa: E402
import ui.views.dashboard as _v_dashboard  # noqa: E402
import ui.views.history as _v_history  # noqa: E402
import ui.views.mf_lab as _v_mf  # noqa: E402
import ui.views.options as _v_options  # noqa: E402
import ui.views.orders as _v_orders  # noqa: E402
import ui.views.stock_screener as _v_screener  # noqa: E402

# ---------------------------------------------------------------------------
# Authenticated app
# ---------------------------------------------------------------------------
from ui.components.auth import delete_account_dialog  # noqa: E402
from ui.components.auth import (  # noqa: E402
    logout_dialog,
    sync_user_profile,
)
from ui.components.broker import handle_broker_oauth_callback  # noqa: E402
from ui.components.broker import (  # noqa: E402
    render_broker_settings_section,
    render_broker_settings_section_enhanced,
)
from ui.components.orders import render_enhanced_orders_table  # noqa: E402
from ui.components.profile import render_profile_page  # noqa: E402
from ui.components.profile import (  # noqa: E402
    render_profile_section,
)
from ui.components.sidebar import render_module_filters  # noqa: E402
from ui.components.sidebar import (  # noqa: E402
    render_system_status,
)

username = st.session_state["current_user"]

# Handle broker OAuth callback (Zerodha request_token in URL params)
if username != "guest_user":
    handle_broker_oauth_callback(username)

# Use cached profile — re-sync only on first load after login
profile = st.session_state.get("current_user_profile") or {}
if not profile:
    profile = sync_user_profile(username)
    st.session_state["current_user_profile"] = profile

api_url: str = st.session_state["fastapi_url"]
os.environ["FORTRESS_API_URL"] = api_url

modules = State.available_modules()
if st.session_state.get("active_module") not in modules:
    st.session_state["active_module"] = modules[0]

# ── Sidebar ───────────────────────────────────────────────────────────────
with st.sidebar:
    st.markdown("## 🏹 Fortress")
    st.divider()

    # ── System status ────────────────────────────────────────────────────
    render_system_status()
    st.divider()

    # ── Navigation ────────────────────────────────────────────────────────
    module = st.radio(
        "Navigate",
        modules,
        key="active_module",
        label_visibility="collapsed",
    )
    st.divider()

    filters = render_module_filters(module, username, api_url)
    st.divider()

    with st.expander(f"👤 {profile.get('full_name') or username}", expanded=False):
        render_profile_section(profile)

    if username != "guest_user":
        if st.session_state.get("ENABLE_NEW_FEATURES", False):
            with st.expander("🔑 Broker Settings", expanded=False):
                render_broker_settings_section_enhanced(username)
        else:
            with st.expander("🔑 Broker Connections", expanded=False):
                render_broker_settings_section(username)

    with st.expander("⚙️ Settings", expanded=False):
        st.text_input("API URL", key="fastapi_url", help="Backend FastAPI endpoint.")
        admin_username = os.environ.get("FORTRESS_APP_USERNAME", "admin")
        if username in ("admin", admin_username):
            st.markdown("---")
            st.markdown("### 🤖 AI Agent Audit Log")
            try:
                from utils.ai_audit import get_recent_ai_changes

                ai_logs = get_recent_ai_changes(limit=15)
                if ai_logs:
                    import pandas as pd

                    st.dataframe(
                        pd.DataFrame(ai_logs), use_container_width=True, hide_index=True
                    )
                else:
                    st.info("No AI agent changes logged yet.")
            except ImportError:
                st.warning("AI Audit module not found.")

    with st.expander("📡 Telegram Scheduler", expanded=False):
        try:
            from scripts.scheduler import (
                _scheduler_started,
                _seconds_until_next_broadcast,
            )

            if _scheduler_started:
                from datetime import datetime as _dt
                from datetime import timedelta as _td

                import pytz as _ptz

                _ist = _ptz.timezone("Asia/Kolkata")
                next_secs = _seconds_until_next_broadcast()
                next_time = _dt.now(_ist) + _td(seconds=next_secs)
                st.success("✅ Scheduler Active")
                st.caption(
                    f"Next broadcast: **{next_time.strftime('%d-%b %H:%M IST')}** "
                    f"({next_secs/3600:.1f}h)"
                )
            else:
                st.warning("⏸️ Scheduler not started")
        except Exception:
            st.info("Scheduler module not loaded")

        if st.button(
            "📤 Send Broadcast Now",
            use_container_width=True,
            type="primary",
            key="manual_tg_broadcast",
        ):
            try:
                from scripts.scheduler import _run_telegram_broadcast

                with st.spinner("Broadcasting to Telegram..."):
                    _run_telegram_broadcast()
                st.success("✅ Broadcast sent!")
            except Exception as exc:
                st.error(f"Broadcast failed: {exc}")

    if st.session_state.get("ENABLE_NEW_FEATURES", False):
        with st.expander("🛠️ Setup", expanded=False):
            st.caption("One-time development helpers.")
            if st.button("Seed 5 Dummy Users", use_container_width=True):
                from utils.db import seed_dummy_users

                added = seed_dummy_users()
                st.success(f"Dummy user setup complete. Added {added} user(s).")

    st.divider()
    if st.button("🚪 Logout", use_container_width=True, type="secondary"):
        logout_dialog()
    if username != "guest_user":
        if st.button("🗑️ Delete Account", use_container_width=True, type="secondary"):
            delete_account_dialog(username)

# ── Main Content ─────────────────────────────────────────────────────────────
st.session_state["mf_job_controls_rendered"] = False

if module == "🏠 Dashboard":
    if st.session_state.get("ENABLE_NEW_FEATURES", False):
        tab_overview, tab_orders = st.tabs(["Overview", "Orders"])
        with tab_overview:
            _v_dashboard.render(profile, username)
        with tab_orders:
            st.subheader("📋 Orders")
            render_enhanced_orders_table(username)
    else:
        _v_dashboard.render(profile, username)

elif module == "👤 Profile":
    render_profile_page(profile, username)

elif module == "📊 Stock Screener":
    _v_screener.render(username, api_url, filters)

elif module == "📈 MF Lab":
    _v_mf.render(api_url)

elif module == "📋 Orders":
    _v_orders.render(username, filters)

elif module == "🌍 Commodities":
    _v_commodities.render(username, filters.get("broker"))

elif module == "⚡ Options":
    _v_options.render(username, filters.get("broker"))

elif module == "🕐 Scan History":
    _v_history.render()

elif module == "🤖 Test Agent" and st.session_state.get("ENABLE_NEW_FEATURES", False):
    st.subheader("🤖 Test Agent")
    tab_generate, tab_run, tab_reports = st.tabs(
        ["Generate Tests", "Run Tests", "Reports"]
    )
    with tab_generate:
        st.write("Generate tests...")
    with tab_run:
        if st.button("Run Tests"):
            st.success("Test run initiated (mocked logic).")
            st.code("Test Session Mock Run Passes")
    with tab_reports:
        st.write("Reports will appear here.")
