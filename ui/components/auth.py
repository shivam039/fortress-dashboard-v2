"""
ui/components/auth.py  —  Authentication UI components
=======================================================
Renders the login / sign-up / guest forms and handles credential checking,
profile sync, and the logout / delete-account dialogs.
"""

from __future__ import annotations

import os
from typing import Any, Dict

import streamlit as st

from ui.state import State  # type: ignore[import]

# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _configured_users() -> Dict[str, Dict[str, str]]:
    username = os.environ.get("FORTRESS_APP_USERNAME", "admin")
    return {
        username: {
            "password": os.environ.get("FORTRESS_APP_PASSWORD", "fortress123"),
            "full_name": os.environ.get("FORTRESS_APP_FULL_NAME", "Fortress Admin"),
            "email": os.environ.get("FORTRESS_APP_EMAIL", "admin@fortress.local"),
            "phone": os.environ.get("FORTRESS_APP_PHONE", "+91 99999 99999"),
            "account_status": os.environ.get("FORTRESS_APP_STATUS", "Active"),
        }
    }


def authenticate(username: str, password: str) -> bool:
    """
    Return True if *username* / *password* is valid.

    Admin login is handled via ``FORTRESS_APP_PASSWORD``; all other users are
    verified against the database.
    """
    from utils.db import verify_user_credentials  # type: ignore[import]

    username = username.strip()

    if username == "admin":
        admin_pwd = os.environ.get("FORTRESS_APP_PASSWORD", "fortress123")
        if not admin_pwd:
            st.error(
                "⚠️ Admin login is disabled: the **FORTRESS_APP_PASSWORD** "
                "environment variable is not set. Contact the administrator.",
                icon="🔐",
            )
            return False
        return password == admin_pwd

    return verify_user_credentials(username, password)


def sync_user_profile(username: str) -> Dict[str, Any]:
    """Upsert the user record from env-config and return the current profile dict."""
    from utils.db import get_app_user, upsert_app_user  # type: ignore[import]

    user_config = _configured_users().get(username, {})
    upsert_app_user(
        username=username,
        full_name=user_config.get("full_name", ""),
        email=user_config.get("email", ""),
        phone=user_config.get("phone", ""),
        account_status=user_config.get("account_status", "Active"),
    )
    return get_app_user(username)


# ---------------------------------------------------------------------------
# Dialogs
# ---------------------------------------------------------------------------


@st.dialog("Confirm Logout")
def logout_dialog() -> None:
    st.write("Are you sure you want to log out of the Fortress Terminal?")
    col1, col2 = st.columns(2)
    with col1:
        if st.button("Yes, Logout", type="primary", use_container_width=True):
            State.logout()
    with col2:
        if st.button("Cancel", use_container_width=True):
            st.rerun()


@st.dialog("⚠️ Delete Account")
def delete_account_dialog(username: str) -> None:
    from utils.db import delete_app_user  # type: ignore[import]

    st.error(
        "This will **permanently delete** your account, all broker connections, "
        "and order history. This action cannot be undone."
    )
    confirm_text = st.text_input("Type your username to confirm", placeholder=username)
    col1, col2 = st.columns(2)
    with col1:
        if st.button("Delete My Account", type="primary", use_container_width=True):
            if confirm_text.strip() == username:
                delete_app_user(username)
                State.logout()
            else:
                st.error("Username does not match. Please try again.")
    with col2:
        if st.button("Cancel", use_container_width=True):
            st.rerun()


# ---------------------------------------------------------------------------
# Login screen
# ---------------------------------------------------------------------------


def render_login_screen() -> None:
    """Render the full login / sign-up / guest screen."""
    st.title("🏹 Fortress Terminal")
    st.caption("Professional quantitative dashboard and execution engine.")
    if st.session_state.get("ENABLE_NEW_FEATURES", False):
        st.info("Enhanced workspace mode is enabled for this session.", icon="✨")

    _, center, _ = st.columns([1, 1.5, 1])
    with center:
        active_tab = st.session_state.get("active_tab", "login")
        if active_tab == "login":
            tab_login, tab_signup, tab_guest = st.tabs(
                ["🔐 Login", "📝 Sign Up", "👤 Guest"]
            )
        elif active_tab == "signup":
            tab_signup, tab_login, tab_guest = st.tabs(
                ["📝 Sign Up", "🔐 Login", "👤 Guest"]
            )
        else:
            tab_login, tab_signup, tab_guest = st.tabs(
                ["🔐 Login", "📝 Sign Up", "👤 Guest"]
            )

        # ── Login ──────────────────────────────────────────────────────────
        with tab_login:
            if st.session_state.get("signup_notice"):
                st.success(st.session_state["signup_notice"])
                st.session_state["signup_notice"] = ""
            with st.form("login_form"):
                username = st.text_input("Username")
                password = st.text_input("Password", type="password")
                submitted = st.form_submit_button(
                    "Sign In", type="primary", use_container_width=True
                )

            if submitted:
                if authenticate(username, password):
                    from utils.db import record_user_login  # type: ignore[import]

                    username = username.strip()
                    profile = sync_user_profile(username)
                    record_user_login(username)
                    st.session_state["logged_in"] = True
                    st.session_state["current_user"] = username
                    st.session_state["current_user_profile"] = profile
                    st.rerun()
                else:
                    st.error("Invalid credentials.")

        # ── Sign Up ────────────────────────────────────────────────────────
        with tab_signup:
            with st.form("signup_form"):
                new_user = st.text_input("Username*")
                full_name = st.text_input("Full Name")
                email = st.text_input("Email")
                new_pass = st.text_input("Password*", type="password")
                signup_btn = st.form_submit_button(
                    "Create Account", type="primary", use_container_width=True
                )

            if signup_btn:
                from utils.db import get_app_user  # type: ignore[import]
                from utils.db import (
                    upsert_app_user,
                )

                clean_user = new_user.strip()
                clean_pass = new_pass.strip()
                existing_user = get_app_user(clean_user) if clean_user else {}

                if not clean_user or not clean_pass:
                    st.error("Username and Password are required.")
                elif existing_user and existing_user.get("password_hash"):
                    st.error(
                        "Username already exists. Please choose a different username."
                    )
                else:
                    upsert_app_user(
                        username=clean_user,
                        full_name=full_name,
                        email=email,
                        password=clean_pass,
                    )
                    st.session_state["active_tab"] = "login"
                    st.session_state["signup_notice"] = (
                        "Account created successfully. Please sign in."
                    )
                    st.rerun()

        # ── Guest ──────────────────────────────────────────────────────────
        with tab_guest:
            st.write(
                "Explore the Fortress terminal with a temporary guest session. "
                "Note: Broker connections are saved per account."
            )
            if st.button(
                "Continue as Guest", type="secondary", use_container_width=True
            ):
                guest_profile = {
                    "username": "guest_user",
                    "full_name": "Guest Explorer",
                    "email": "",
                    "phone": "",
                    "account_status": "Trial",
                    "last_login_at": None,
                }
                st.session_state["logged_in"] = True
                st.session_state["current_user"] = "guest_user"
                st.session_state["current_user_profile"] = guest_profile
                st.rerun()
