"""
ui/utils/error_handling.py  —  Error display helpers
=====================================================
Consistent error boundaries and loading-state helpers for all views.
Import these instead of writing raw ``try/except: st.error(...)`` blocks.
"""

from __future__ import annotations

import contextlib
import logging
from typing import Any, Callable, Generator, TypeVar

import streamlit as st

logger = logging.getLogger("fortress.ui.errors")

_F = TypeVar("_F", bound=Callable[..., Any])


@contextlib.contextmanager
def error_boundary(
    label: str = "section",
    show_traceback: bool = False,
) -> Generator[None, None, None]:
    """
    Context manager that catches and displays any exception as a Streamlit error.

    Usage::

        with error_boundary("Scan Results"):
            _render_results_table(df)

    Args:
        label:          Human-readable name for this section (used in the message).
        show_traceback: If True, show the full exception detail to the user.
    """
    try:
        yield
    except Exception as exc:
        msg = f"⚠️ **{label}** encountered an error."
        if show_traceback:
            msg += f"\n\n```\n{exc}\n```"
        else:
            msg += " Check the server logs for details."
        logger.exception("Error in '%s': %s", label, exc)
        st.error(msg)


def safe_render(fn: _F) -> _F:
    """
    Decorator that wraps a render function in an error_boundary.

    Usage::

        @safe_render
        def render(username: str) -> None:
            ...
    """
    import functools

    @functools.wraps(fn)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        with error_boundary(fn.__name__):
            return fn(*args, **kwargs)

    return wrapper  # type: ignore[return-value]


def show_loading_error(label: str, exc: Exception) -> None:
    """Render a user-friendly loading error with a retry hint."""
    st.warning(
        f"**{label}** could not load data.\n\n"
        f"> `{type(exc).__name__}: {exc}`\n\n"
        "Refresh the page or check backend connectivity.",
        icon="⚠️",
    )


def require_data(df_or_list: Any, empty_message: str = "No data available.") -> bool:
    """
    Return True if *df_or_list* is non-empty; else render *empty_message* and return False.

    Use at the top of any data-driven render function::

        if not require_data(df, "Run a scan first."):
            return
    """
    import pandas as pd

    is_empty = (isinstance(df_or_list, pd.DataFrame) and df_or_list.empty) or (
        isinstance(df_or_list, (list, dict)) and not df_or_list
    )
    if is_empty:
        st.info(empty_message)
        return False
    return True
