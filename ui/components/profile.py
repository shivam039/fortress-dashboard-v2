"""
ui/components/profile.py  —  User profile display components
=============================================================
Renders the compact sidebar profile snapshot and the full profile page.
"""

from __future__ import annotations

from typing import Any, Dict

import streamlit as st

from ui.utils.formatting import format_timestamp  # type: ignore[import]


def render_profile_section(profile: Dict[str, Any]) -> None:
    """Compact profile card for the sidebar expander."""
    st.markdown("### 👤 Profile")
    with st.container(border=True):
        st.markdown(f"#### {profile.get('full_name') or 'Fortress User'}")
        st.caption(f"📧 {profile.get('email') or 'N/A'}")
        st.caption(f"📱 {profile.get('phone') or 'N/A'}")
        st.divider()
        st.caption("Account Details")
        st.write(f"**Status:** {profile.get('account_status') or 'Active'}")
        st.write(f"**Joined:** {format_timestamp(profile.get('created_at'))}")
        st.write(f"**Last Login:** {format_timestamp(profile.get('last_login_at'))}")


def render_profile_page(profile: Dict[str, Any], username: str) -> None:
    """Full profile page rendered in the main content area."""
    st.subheader("👤 Profile")
    st.caption("Professional account summary and sign-in details.")
    card_data = [
        ("Name", profile.get("full_name") or username),
        ("Email", profile.get("email") or "N/A"),
        ("Account Created", format_timestamp(profile.get("created_at"))),
        ("Last Login", format_timestamp(profile.get("last_login_at"))),
        ("Status", profile.get("account_status") or "Active"),
    ]
    row1 = st.columns(2)
    row2 = st.columns(3)
    card_cols = [row1[0], row1[1], row2[0], row2[1], row2[2]]
    for idx, (label, value) in enumerate(card_data):
        with card_cols[idx]:
            with st.container(border=True):
                st.caption(label)
                st.markdown(f"**{value}**")
