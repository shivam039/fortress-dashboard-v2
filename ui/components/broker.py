"""
ui/components/broker.py  —  Broker connection UI components
============================================================
Dialogs and settings sections for connecting Zerodha / Dhan accounts.
All tokens are encrypted before storage (via utils.token_encryption).
"""

from __future__ import annotations

import pandas as pd
import streamlit as st

from ui.state import BROKER_OPTIONS, State  # type: ignore[import]
from ui.utils.formatting import check_token_expiry  # type: ignore[import]
from ui.utils.formatting import (
    format_timestamp,
)

# ---------------------------------------------------------------------------
# OAuth callback
# ---------------------------------------------------------------------------


def handle_broker_oauth_callback(username: str) -> None:
    """
    Read query params after a broker OAuth redirect and auto-save the token.

    Called once per page load by the main app before rendering content.
    """
    from utils.db import upsert_user_broker_connection  # type: ignore[import]

    params = st.query_params
    request_token = params.get("request_token", "")
    status = params.get("status", "")

    if request_token and status == "success":
        st.success("✅ Zerodha login successful! Saving your access token...")
        upsert_user_broker_connection(
            username=username,
            broker_name="Zerodha",
            access_token=request_token,
        )
        State.invalidate_broker_cache()
        st.query_params.clear()
        st.rerun()


# ---------------------------------------------------------------------------
# Dialogs
# ---------------------------------------------------------------------------


@st.dialog("Connect Broker")
def connect_broker_dialog(username: str) -> None:
    """Manual token entry dialog — for permanent / pre-generated tokens."""
    from utils.db import upsert_user_broker_connection  # type: ignore[import]

    st.write(
        "Link your Zerodha or Dhan account by providing an access token. "
        "All tokens are encrypted before storage."
    )
    with st.form("broker_connection_form", clear_on_submit=True):
        broker_name = st.selectbox("Broker", BROKER_OPTIONS)
        broker_client_id = st.text_input(
            "Client ID / User ID", placeholder="e.g. AB1234 or DHAN_ID"
        )
        access_token = st.text_area(
            "Access Token",
            placeholder="Paste your permanent or session access token here...",
            height=120,
        )
        col1, col2 = st.columns(2)
        with col1:
            expires_on = st.text_input("Expiry (Optional)", placeholder="YYYY-MM-DD")
        with col2:
            refresh_token = st.text_input("Refresh Token (Optional)", type="password")
        submitted = st.form_submit_button(
            "💾 Save & Connect", type="primary", use_container_width=True
        )

    if submitted:
        if not access_token.strip():
            st.error("Access token is required.")
        else:
            upsert_user_broker_connection(
                username=username,
                broker_name=broker_name,
                broker_client_id=broker_client_id.strip(),
                access_token=access_token.strip(),
                refresh_token=refresh_token.strip(),
                expires_at=expires_on.strip() or None,
            )
            State.invalidate_broker_cache()
            st.success(f"✅ {broker_name} connection saved successfully.")
            st.rerun()


@st.dialog("🔗 Broker Login")
def broker_login_dialog(username: str) -> None:
    """OAuth-guided broker login dialog."""
    from utils.db import upsert_user_broker_connection  # type: ignore[import]

    st.write(
        "Choose your broker and follow the steps to authenticate via their "
        "official login page."
    )
    broker_name = st.selectbox(
        "Broker", BROKER_OPTIONS, key="broker_login_dialog_broker"
    )
    st.divider()

    if broker_name == "Zerodha":
        api_key = st.text_input(
            "Your Kite API Key",
            placeholder="Enter your Zerodha Kite API Key",
            help="Get this from your Kite Connect developer account at https://developers.kite.trade",
        )
        if api_key:
            login_url = (
                f"https://kite.zerodha.com/connect/login?api_key={api_key.strip()}&v=3"
            )
            st.info(
                "Click the button below to open Zerodha Kite login. After "
                "authentication you will be redirected back with a `request_token` "
                "in the URL. Copy and paste it below."
            )
            st.link_button(
                "🔐 Login via Zerodha Kite", login_url, use_container_width=True
            )
            st.divider()
            st.markdown("**Step 2: Paste the `request_token` from redirect URL**")
            st.caption(
                "After login, Zerodha redirects you to your redirect URL with "
                "`?request_token=XXXXX&status=success`. Copy the token value."
            )
            request_token = st.text_input(
                "Request Token / Access Token",
                type="password",
                placeholder="Paste token here...",
            )
            client_id = st.text_input(
                "Client ID (optional)", placeholder="Your Zerodha User ID e.g. AB1234"
            )
            if st.button(
                "✅ Save Zerodha Token", type="primary", use_container_width=True
            ):
                if request_token.strip():
                    upsert_user_broker_connection(
                        username=username,
                        broker_name="Zerodha",
                        broker_client_id=client_id.strip(),
                        access_token=request_token.strip(),
                    )
                    State.invalidate_broker_cache()
                    st.success(
                        "✅ Zerodha token saved! You can now use it for order placement."
                    )
                    st.rerun()
                else:
                    st.error("Please paste the token before saving.")
        else:
            st.warning("Enter your API key to get the login URL.")

    elif broker_name == "Dhan":
        st.info(
            "Dhan uses a permanent access token. Generate it from your Dhan "
            "developer console and paste it below."
        )
        st.link_button(
            "🔐 Open Dhan Console", "https://login.dhan.co", use_container_width=True
        )
        st.divider()
        client_id = st.text_input("Dhan Client ID", placeholder="Your Dhan User ID")
        access_token = st.text_input(
            "Access Token",
            type="password",
            placeholder="Paste your Dhan access token",
        )
        if st.button("✅ Save Dhan Token", type="primary", use_container_width=True):
            if access_token.strip():
                upsert_user_broker_connection(
                    username=username,
                    broker_name="Dhan",
                    broker_client_id=client_id.strip(),
                    access_token=access_token.strip(),
                )
                State.invalidate_broker_cache()
                st.success(
                    "✅ Dhan token saved! You can now use it for order placement."
                )
                st.rerun()
            else:
                st.error("Please paste the access token before saving.")


@st.dialog("Add/Update Broker")
def broker_modal(username: str) -> None:
    """Simple legacy dialog (token-only, no client ID)."""
    broker_name = st.selectbox("Broker", ["Zerodha", "Dhan"])
    access_token = st.text_input("Access Token", type="password")
    if st.button("Save Broker Connection"):
        from utils.db import upsert_user_broker_connection  # type: ignore[import]
        from utils.token_encryption import encrypt_broker_token  # type: ignore[import]

        encrypted_token = encrypt_broker_token(access_token)
        upsert_user_broker_connection(
            username=username,
            broker_name=broker_name,
            access_token=encrypted_token,
            is_active=True,
        )
        st.success(f"{broker_name} connected successfully.")
        st.rerun()


# ---------------------------------------------------------------------------
# Broker settings sections
# ---------------------------------------------------------------------------


def render_broker_settings_section(username: str) -> None:
    """Full broker management panel (connect, list, delete)."""
    from utils.db import delete_user_broker_connection  # type: ignore[import]

    st.markdown("### 🔑 Broker Connections")
    brokers_df = st.session_state.get("brokers_df_cache", pd.DataFrame())
    if brokers_df.empty:
        State.get_active_broker_names(username)  # populates cache
        brokers_df = st.session_state.get("brokers_df_cache", pd.DataFrame())

    btn_col1, btn_col2 = st.columns(2)
    with btn_col1:
        if st.button("🔗 Login via Broker", use_container_width=True, type="primary"):
            broker_login_dialog(username)
    with btn_col2:
        if st.button("➕ Manual Token", use_container_width=True):
            connect_broker_dialog(username)

    if not brokers_df.empty:
        st.divider()
        for _, row in brokers_df.iterrows():
            expiry_badge, expiry_color = check_token_expiry(row.get("expires_at"))
            is_expired = expiry_badge.startswith("🔴")
            with st.container(border=True):
                col_info, col_btn = st.columns([3, 1])
                with col_info:
                    st.write(
                        f"**{row['broker_name']}** ({row.get('broker_client_id') or 'N/A'})"
                    )
                    status = (
                        "❌ Inactive (Expired)"
                        if is_expired
                        else (
                            "✅ Active" if bool(row.get("is_active")) else "❌ Inactive"
                        )
                    )
                    st.caption(
                        f"{status} | Connected: {format_timestamp(row.get('connected_at'))}"
                    )
                    if expiry_badge:
                        st.markdown(
                            f'<span style="color:{expiry_color};font-size:0.8em;'
                            f'font-weight:600;">{expiry_badge}</span>',
                            unsafe_allow_html=True,
                        )
                    if is_expired:
                        st.warning(
                            "⚠️ Token expired — reconnect to restore broker access.",
                            icon=None,
                        )
                with col_btn:
                    if st.button(
                        "Delete",
                        key=f"del_{row['broker_name']}",
                        type="secondary",
                        use_container_width=True,
                    ):
                        delete_user_broker_connection(username, row["broker_name"])
                        State.invalidate_broker_cache()
                        st.rerun()
    else:
        st.caption("No broker connections yet. Use the buttons above to connect.")


def render_broker_settings_section_enhanced(username: str) -> None:
    """Enhanced broker settings panel (simplified, modal-based)."""
    st.markdown("### Broker Settings")
    if st.button("Add/Update Broker Connection", type="primary"):
        broker_modal(username)
