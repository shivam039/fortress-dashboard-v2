"""
ui/views/history.py  —  Scan History view
==========================================
Delegates rendering to the engine's history.ui module.
"""

from __future__ import annotations

import importlib

import streamlit as st


def render() -> None:
    """Render the 🕐 Scan History module."""
    history_ui = importlib.import_module("history.ui")
    st.subheader("🕐 Scan History")
    history_ui.render()
