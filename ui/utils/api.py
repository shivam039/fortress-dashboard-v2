"""
ui/utils/api.py  —  Centralized FastAPI client
================================================
All HTTP calls to the backend FastAPI server go through this module.
UI code must never call ``requests`` directly — use these typed helpers.

Separation of concerns:
  - This module owns the HTTP transport layer only
  - View files own UI rendering
  - ``ui.utils.scan`` owns in-process engine fallbacks
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

import requests
import streamlit as st

logger = logging.getLogger("fortress.ui.api")

# Default timeout for most calls; scan gets a longer budget
_DEFAULT_TIMEOUT: int = 10
_SCAN_TIMEOUT: int = 180


# ---------------------------------------------------------------------------
# Generic caller
# ---------------------------------------------------------------------------


class APIError(Exception):
    """Raised when the backend returns a non-2xx response or is unreachable."""

    def __init__(self, message: str, status_code: Optional[int] = None) -> None:
        super().__init__(message)
        self.status_code = status_code


def _api_url() -> str:
    """Return the current FastAPI base URL from session state."""
    return str(st.session_state.get("fastapi_url", "http://127.0.0.1:8000")).rstrip("/")


def is_reachable() -> bool:
    """
    Quickly probe the backend health endpoint.

    Returns ``True`` if the backend responds with HTTP 200, ``False`` otherwise.
    Does NOT raise — safe to call as a connectivity check.
    """
    try:
        res = requests.get(f"{_api_url()}/health", timeout=2)
        return res.status_code == 200
    except Exception:
        return False


def get(endpoint: str, *, timeout: int = _DEFAULT_TIMEOUT, **kwargs: Any) -> Any:
    """
    GET *endpoint* on the configured API base URL.

    Returns the parsed JSON body.
    Raises ``APIError`` on failure.
    """
    url = f"{_api_url()}{endpoint}"
    try:
        res = requests.get(url, timeout=timeout, **kwargs)
        res.raise_for_status()
        return res.json()
    except requests.exceptions.ConnectionError as exc:
        raise APIError(f"Backend unreachable: {exc}") from exc
    except requests.exceptions.HTTPError as exc:
        raise APIError(
            f"HTTP {exc.response.status_code}: {exc}", exc.response.status_code
        ) from exc
    except requests.exceptions.RequestException as exc:
        raise APIError(str(exc)) from exc


def post(
    endpoint: str,
    payload: Dict[str, Any],
    *,
    timeout: int = _DEFAULT_TIMEOUT,
    **kwargs: Any,
) -> Any:
    """
    POST *payload* to *endpoint* on the configured API base URL.

    Returns the parsed JSON body.
    Raises ``APIError`` on failure.
    """
    url = f"{_api_url()}{endpoint}"
    try:
        res = requests.post(url, json=payload, timeout=timeout, **kwargs)
        res.raise_for_status()
        return res.json()
    except requests.exceptions.ConnectionError as exc:
        raise APIError(f"Backend unreachable: {exc}") from exc
    except requests.exceptions.HTTPError as exc:
        raise APIError(
            f"HTTP {exc.response.status_code}: {exc}", exc.response.status_code
        ) from exc
    except requests.exceptions.RequestException as exc:
        raise APIError(str(exc)) from exc


# ---------------------------------------------------------------------------
# Domain-specific typed callers
# ---------------------------------------------------------------------------


def fetch_universes() -> List[str]:
    """
    Fetch the list of scan universes from the backend.

    Falls back to the local ``fortress_config.TICKER_GROUPS`` on error.
    """
    try:
        data = get("/api/universes", timeout=3)
        if isinstance(data, list):
            return data
    except APIError as exc:
        logger.debug("Universe fetch from API failed (%s); using local config.", exc)
    from fortress_config import TICKER_GROUPS  # type: ignore[import]

    return list(TICKER_GROUPS.keys())


def trigger_scan(payload: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    POST a scan payload to ``/api/scan``.

    Returns the list of result dicts.
    Raises ``APIError`` on failure (caller should fall back to in-process).
    """
    data = post("/api/scan", payload, timeout=_SCAN_TIMEOUT)
    if not isinstance(data, list):
        raise APIError("Unexpected scan response format")
    return data


def trigger_mf_job(payload: Dict[str, Any]) -> str:
    """
    POST to ``/mf/trigger-job``.

    Returns the server's message string on acceptance (HTTP 202).
    Raises ``APIError`` otherwise.
    """
    url = f"{_api_url()}/mf/trigger-job"
    try:
        res = requests.post(url, json=payload, timeout=_DEFAULT_TIMEOUT)
        if res.status_code == 202:
            return res.json().get("message", "Job triggered successfully.")
        try:
            detail = res.json().get("detail", res.text)
        except ValueError:
            detail = res.text
        raise APIError(f"Server rejected: {detail}", res.status_code)
    except requests.exceptions.ConnectionError as exc:
        raise APIError(f"Backend unreachable: {exc}") from exc
    except requests.exceptions.RequestException as exc:
        raise APIError(str(exc)) from exc
