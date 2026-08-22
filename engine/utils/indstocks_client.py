"""
engine/utils/indstocks_client.py
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Thin, production-grade REST client for the INDstocks Trading API.
https://api-docs.indstocks.com/

Design decisions:
- One client instance per application (singleton via module-level helper).
- Minimum 0.2 s gap between requests to stay under the 5 req/s Data/Quote limit.
- Three retries with exponential back-off on 5xx and 429.
- Raises ``INDstocksError`` for all API-level failures so callers can catch one type.
- **Auto-refresh**: if INDSTOCKS_CLIENT_ID + INDSTOCKS_MPIN + INDSTOCKS_TOTP_SECRET
  are set, the client generates tokens automatically (no manual copy-paste).
  On 403 TokenException the token is refreshed once and the request is retried.

Env vars
--------
Auto-refresh (preferred) — set all three::

    INDSTOCKS_CLIENT_ID   = dX03OgVqr0Cgc8x7fJQ0   # from dashboard
    INDSTOCKS_MPIN        = <your mpin>              # never commit
    INDSTOCKS_TOTP_SECRET = <base32 setup key>       # from dashboard QR, never commit

Static token (fallback, expires every 24 h)::

    INDSTOCKS_TOKEN = eyJ...   # from dashboard

Usage::

    from engine.utils.indstocks_client import get_client

    client = get_client()                          # auto-refreshes token if TOTP creds set
    ltp_data = client.get_ltp(["NSE_2885"])        # {"NSE_2885": {"live_price": 1426.0}}
"""

from __future__ import annotations

import logging
import os
import time
from typing import Any

import requests

logger = logging.getLogger(__name__)

BASE_URL = "https://api.indstocks.com"

# INDstocks Data/Quote API: 5 req/s → enforce 0.2 s minimum gap
_MIN_REQUEST_GAP_S = 0.20
_MAX_RETRIES = 3


class INDstocksError(Exception):
    """Raised for any non-2xx response from the INDstocks API."""

    def __init__(self, status_code: int, message: str) -> None:
        self.status_code = status_code
        self.message = message
        super().__init__(f"[{status_code}] {message}")


# ---------------------------------------------------------------------------
# TOTP helpers
# ---------------------------------------------------------------------------

def _totp_env_available() -> bool:
    """Return True if all three TOTP env vars are set."""
    return all(
        os.getenv(k, "").strip()
        for k in ("INDSTOCKS_CLIENT_ID", "INDSTOCKS_MPIN", "INDSTOCKS_TOTP_SECRET")
    )


def _generate_totp_code() -> str:
    """Generate the current 6-digit TOTP code from INDSTOCKS_TOTP_SECRET.

    Base32 secrets only contain ``A-Z`` and ``2-7``. Dashboards commonly
    *display* the setup key in space-separated groups (e.g. ``"ABCD EFGH
    IJKL..."``) for readability, and it's easy to copy that formatting along
    with the secret. ``.strip()`` alone only removes leading/trailing
    whitespace, so an internal space survives and ``pyotp`` rejects it with
    an opaque ``"Non-base32 digit found"`` error. Strip *all* whitespace and
    normalize case before handing it to pyotp.
    """
    import re

    import pyotp

    raw = os.environ["INDSTOCKS_TOTP_SECRET"]
    secret = re.sub(r"\s+", "", raw).upper()
    if not secret:
        raise EnvironmentError("INDSTOCKS_TOTP_SECRET is set but empty after stripping whitespace.")
    if not re.fullmatch(r"[A-Z2-7]+=*", secret):
        raise EnvironmentError(
            "INDSTOCKS_TOTP_SECRET does not look like a valid base32 TOTP secret "
            "(only A-Z and 2-7 are valid). Double-check you copied the setup key "
            "exactly as shown on the INDstocks/IndMoney dashboard, with no extra "
            "characters or line breaks."
        )
    return pyotp.TOTP(secret).now()


def _fetch_new_token() -> str:
    """Call POST /generate/token with TOTP creds and return the fresh access token.

    Reads from env:
        INDSTOCKS_CLIENT_ID   — the static client ID from the dashboard
        INDSTOCKS_MPIN        — your account MPIN
        INDSTOCKS_TOTP_SECRET — base32 setup key from the dashboard QR code

    Returns:
        Fresh access token string.

    Raises:
        INDstocksError: If the API rejects the request (wrong MPIN, lockout, etc.).
        EnvironmentError: If required env vars are not set.
    """
    client_id = os.environ.get("INDSTOCKS_CLIENT_ID", "").strip()
    mpin = os.environ.get("INDSTOCKS_MPIN", "").strip()
    if not client_id or not mpin:
        raise EnvironmentError(
            "INDSTOCKS_CLIENT_ID and INDSTOCKS_MPIN must be set for TOTP token generation."
        )

    totp_code = _generate_totp_code()
    logger.info("Requesting new INDstocks token via TOTP...")

    resp = requests.post(
        f"{BASE_URL}/generate/token",
        headers={"x-api-key": client_id, "Content-Type": "application/json"},
        json={"mpin": mpin, "totp": totp_code},
        timeout=10,
    )

    if resp.status_code == 200:
        body = resp.json()
        # INDstocks returns the token in a field named "token"
        token = body.get("token") or body.get("access_token") or body.get("data", {}).get("token")
        if token:
            logger.info("INDstocks token refreshed successfully.")
            # Persist to env so other processes/imports can read it
            os.environ["INDSTOCKS_TOKEN"] = token
            return token
        raise INDstocksError(200, f"token field missing in response: {body}")

    try:
        msg = resp.json().get("message") or resp.text[:200]
    except Exception:
        msg = resp.text[:200]
    raise INDstocksError(resp.status_code, f"Token generation failed: {msg}")


class INDstocksClient:
    """REST client for the INDstocks Trading API v1.

    Token resolution order on startup:

    1. **TOTP auto-refresh** (preferred): if ``INDSTOCKS_CLIENT_ID``,
       ``INDSTOCKS_MPIN``, and ``INDSTOCKS_TOTP_SECRET`` are all set, a fresh
       token is generated automatically via ``POST /generate/token``. The token
       is also auto-refreshed whenever a ``403 TokenException`` is received.

    2. **Static token** (fallback): reads ``INDSTOCKS_TOKEN`` from env.
       Expires every 24 hours — must be manually updated.

    Args:
        token: Override token. If ``None``, the resolution order above applies.
    """

    def __init__(self, token: str | None = None) -> None:
        if token:
            self._token = token
        elif _totp_env_available():
            # Auto-generate via TOTP on startup
            try:
                self._token = _fetch_new_token()
            except Exception as exc:
                logger.warning(
                    "TOTP token generation failed (%s), falling back to INDSTOCKS_TOKEN env.", exc
                )
                self._token = os.getenv("INDSTOCKS_TOKEN", "")
        else:
            self._token = os.getenv("INDSTOCKS_TOKEN", "")

        if not self._token:
            raise EnvironmentError(
                "INDstocks token not available. Either set:\n"
                "  • INDSTOCKS_CLIENT_ID + INDSTOCKS_MPIN + INDSTOCKS_TOTP_SECRET  (auto-refresh)\n"
                "  • INDSTOCKS_TOKEN  (static, expires 24h)"
            )

        self._session = requests.Session()
        self._session.headers.update(
            {
                "Authorization": self._token,
                "Content-Type": "application/json",
            }
        )
        self._last_request_at: float = 0.0

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _update_token(self, new_token: str) -> None:
        """Swap in a new token without recreating the session."""
        self._token = new_token
        self._session.headers["Authorization"] = new_token

    def _try_refresh_token(self) -> bool:
        """Attempt a TOTP token refresh. Returns True if successful."""
        if not _totp_env_available():
            return False
        try:
            new_token = _fetch_new_token()
            self._update_token(new_token)
            return True
        except Exception as exc:
            logger.error("Token refresh failed: %s", exc)
            return False

    def _throttle(self) -> None:
        """Enforce the minimum gap between consecutive requests."""
        elapsed = time.monotonic() - self._last_request_at
        if elapsed < _MIN_REQUEST_GAP_S:
            time.sleep(_MIN_REQUEST_GAP_S - elapsed)

    def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json: dict[str, Any] | None = None,
        raw: bool = False,
        _token_refreshed: bool = False,
    ) -> Any:
        """Make a throttled, retried HTTP request.

        Args:
            method: HTTP verb (``"GET"``, ``"POST"``).
            path: API path, e.g. ``"/market/quotes/ltp"``.
            params: Query-string parameters.
            json: JSON request body (for POST).
            raw: If ``True``, return the raw ``Response`` object (e.g. CSV downloads).
            _token_refreshed: Internal flag — prevents infinite refresh loops.

        Returns:
            Parsed JSON dict/list, or raw ``Response`` if ``raw=True``.

        Raises:
            INDstocksError: On non-2xx responses after retries exhausted.
        """
        url = BASE_URL + path
        attempt = 0
        while True:
            self._throttle()
            try:
                resp = self._session.request(
                    method, url, params=params, json=json, timeout=10
                )
                self._last_request_at = time.monotonic()

                if resp.status_code == 200:
                    if raw:
                        return resp
                    return resp.json()

                # 403 → expired / revoked token → try auto-refresh once
                if resp.status_code == 403 and not _token_refreshed:
                    logger.warning("403 TokenException — attempting auto-refresh...")
                    if self._try_refresh_token():
                        return self._request(
                            method, path,
                            params=params, json=json, raw=raw,
                            _token_refreshed=True,
                        )

                if resp.status_code == 429 or resp.status_code >= 500:
                    attempt += 1
                    if attempt >= _MAX_RETRIES:
                        raise INDstocksError(
                            resp.status_code,
                            f"Exhausted retries: {resp.text[:200]}",
                        )
                    wait = 2**attempt
                    logger.warning(
                        "INDstocks %s %s → %d, retrying in %ds (attempt %d/%d)",
                        method, path, resp.status_code, wait, attempt, _MAX_RETRIES,
                    )
                    time.sleep(wait)
                    continue

                # 4xx (non-429, non-403) — not retryable
                try:
                    body = resp.json()
                    msg = body.get("message") or body.get("error") or resp.text[:200]
                except Exception:
                    msg = resp.text[:200]
                raise INDstocksError(resp.status_code, msg)

            except requests.exceptions.RequestException as exc:
                attempt += 1
                if attempt >= _MAX_RETRIES:
                    raise INDstocksError(0, f"Network error: {exc}") from exc
                wait = 2**attempt
                logger.warning(
                    "INDstocks network error (%s), retrying in %ds (attempt %d/%d)",
                    exc, wait, attempt, _MAX_RETRIES,
                )
                time.sleep(wait)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get_profile(self) -> dict[str, Any]:
        """Fetch the authenticated user's profile. Useful for token validation.

        Returns:
            Profile dict with ``user_id``, ``email``, ``first_name``, etc.
        """
        data = self._request("GET", "/user/profile")
        return data.get("data", data)

    def get_ltp(self, scrip_codes: list[str]) -> dict[str, dict[str, Any]]:
        """Get the Last Traded Price for one or more instruments.

        Args:
            scrip_codes: List of ``"EXCHANGE_SECURITY_ID"`` strings, e.g.
                         ``["NSE_2885", "NSE_11536"]``.

        Returns:
            Dict keyed by scrip code, each value ``{"live_price": float}``.

        Example::

            client.get_ltp(["NSE_2885"])
            # → {"NSE_2885": {"live_price": 1426.0}}
        """
        codes_str = ",".join(scrip_codes)
        data = self._request("GET", "/market/quotes/ltp", params={"scrip-codes": codes_str})
        return data.get("data", {})

    def get_full_quote(self, scrip_codes: list[str]) -> dict[str, dict[str, Any]]:
        """Get comprehensive market snapshot (OHLC, volume, circuit limits, depth).

        Args:
            scrip_codes: List of ``"EXCHANGE_SECURITY_ID"`` strings (max 1000).

        Returns:
            Dict keyed by scrip code with full market data per instrument.
        """
        codes_str = ",".join(scrip_codes)
        data = self._request("GET", "/market/quotes/full", params={"scrip-codes": codes_str})
        return data.get("data", {})

    def get_historical(
        self,
        scrip_codes: list[str],
        interval: str,
        start_ms: int,
        end_ms: int,
    ) -> dict[str, dict[str, Any]]:
        """Fetch historical OHLCV candles.

        Args:
            scrip_codes: List of ``"EXCHANGE_SECURITY_ID"`` strings. Unlike
                ``get_ltp``/``get_full_quote`` (documented up to 1000/call),
                this endpoint is undocumented for batch size and was found
                empirically to reject 6+ codes with a generic
                ``{"debug_info":"Invalid scrip codes","message":"Bad
                Request"}`` — 5 or fewer per call is the confirmed-working
                limit. Callers batching many symbols must chunk to 5 or fewer
                (``market_data_provider._BATCH_CHUNK_SIZE`` does this).
            interval: One of ``"1minute"``, ``"5minute"``, ``"15minute"``,
                      ``"30minute"``, ``"60minute"``, ``"1day"``, ``"1week"``,
                      ``"1month"`` etc. See INDstocks docs for full list.
            start_ms: Start timestamp, Unix epoch **milliseconds** (IST).
            end_ms: End timestamp, Unix epoch **milliseconds** (IST).

        Returns:
            Dict keyed by scrip code. Each value has a ``"candles"`` list of
            ``{"ts": int, "o": float, "h": float, "l": float, "c": float, "v": int}``
            where ``ts`` is Unix epoch **seconds**.

        Note:
            Max fetch range depends on interval (7 days for minute, 1 year for daily).
        """
        params = {
            "scrip-codes": ",".join(scrip_codes),
            "start_time": start_ms,
            "end_time": end_ms,
        }
        data = self._request("GET", f"/market/historical/{interval}", params=params)
        return data.get("data", {})

    def get_instruments(self, source: str = "equity") -> bytes:
        """Download the instruments master CSV.

        Args:
            source: One of ``"equity"``, ``"fno"``, ``"index"``.

        Returns:
            Raw CSV bytes. Parse with ``pandas.read_csv(io.BytesIO(csv_bytes))``.
        """
        resp = self._request(
            "GET",
            "/market/instruments",
            params={"source": source},
            raw=True,
        )
        return resp.content

    def get_option_chain(
        self,
        exchange: str,
        segment: str,
        underlying_scrip: str,
        expiry: str,
        strike_count: int = 10,
    ) -> dict[str, Any]:
        """Fetch the option chain for an underlying and expiry.

        Args:
            exchange: ``"NSE"`` or ``"BSE"``.
            segment: ``"INDEX"`` or ``"EQUITY"``.
            underlying_scrip: SECURITY_ID of the underlying (e.g. ``"40000001"``
                              for NIFTY 50, ``"2885"`` for RELIANCE).
            expiry: Contract expiry in ``"YYYY-MM-DD"`` format.
            strike_count: Number of strikes per side of ATM (default 10 → 21 total).

        Returns:
            Full option chain dict with ``underlying_ltp``, ``expiry``, and
            ``strikes`` keyed by strike price string.
        """
        params = {
            "exchange": exchange,
            "segment": segment,
            "underlying-scrip": underlying_scrip,
            "expiry": expiry,
            "strike_count": strike_count,
        }
        data = self._request("GET", "/market/option-chain", params=params)
        return data.get("data", data)

    # ------------------------------------------------------------------
    # Static helpers
    # ------------------------------------------------------------------

    @staticmethod
    def build_scrip_code(exchange: str, security_id: str) -> str:
        """Build a scrip code string for the REST quote/historical endpoints.

        Args:
            exchange: ``"NSE"`` or ``"BSE"``.
            security_id: Numeric security ID string (e.g. ``"2885"``).

        Returns:
            ``"NSE_2885"`` — the ``SEGMENT_TOKEN`` format.
        """
        return f"{exchange}_{security_id}"


# ------------------------------------------------------------------
# Module-level singleton
# ------------------------------------------------------------------
_client: INDstocksClient | None = None


def get_client() -> INDstocksClient:
    """Return the module-level singleton INDstocksClient.

    The client is created on first call, reading ``INDSTOCKS_TOKEN`` from env.
    Subsequent calls return the same instance.

    Raises:
        EnvironmentError: If ``INDSTOCKS_TOKEN`` is not set.
    """
    global _client
    if _client is None:
        _client = INDstocksClient()
    return _client
