"""Deterministic provider routing for the normalized options API."""

from datetime import datetime, timezone
from typing import Dict, Optional

from options_algo.analytics import add_moneyness, summarize, to_analytics_frame
from options_algo.contracts import OptionChainResponse
from options_algo.providers import YFinanceOptionsProvider


class OptionsProviderRouter:
    """Select a provider explicitly and preserve provenance in the result."""

    def __init__(self, providers=None):
        self.providers = providers or [YFinanceOptionsProvider()]

    def get_chain(
        self, underlying: str, expiry: Optional[str] = None
    ) -> tuple[OptionChainResponse, bool, Dict[str, str]]:
        diagnostics: Dict[str, str] = {}
        for provider in self.providers:
            try:
                expiries = provider.get_expiries(underlying)
            except Exception as exc:
                diagnostics[provider.name] = classify_provider_error(exc)
                continue
            if not expiries:
                diagnostics[provider.name] = "NO_EXPIRIES"
                continue
            selected = expiry or expiries[0]
            if selected not in expiries:
                diagnostics[provider.name] = "EXPIRY_UNAVAILABLE"
                continue
            try:
                response = provider.get_chain(underlying, selected)
            except Exception as exc:
                diagnostics[provider.name] = classify_provider_error(exc)
                continue
            if response.contracts:
                return response, provider is not self.providers[0], diagnostics
            diagnostics[provider.name] = "EMPTY_CHAIN"
        return (
            OptionChainResponse(
                underlying=underlying,
                underlying_symbol=underlying,
                expiry=expiry,
                provider="unavailable",
                received_at=datetime.now(timezone.utc),
            ),
            False,
            diagnostics,
        )

    def get_expiries(
        self, underlying: str
    ) -> tuple[list, str, Dict[str, str]]:
        """Discover expiries through the same provider order as chain reads."""
        diagnostics: Dict[str, str] = {}
        for provider in self.providers:
            try:
                expiries = provider.get_expiries(underlying)
            except Exception as exc:
                diagnostics[provider.name] = classify_provider_error(exc)
                continue
            if expiries:
                return expiries, provider.name, diagnostics
            diagnostics[provider.name] = "NO_EXPIRIES"
        return [], "unavailable", diagnostics

    @staticmethod
    def as_api_payload(
        response: OptionChainResponse,
        fallback_used: bool,
        diagnostics: Dict[str, str],
    ) -> dict:
        frame = add_moneyness(to_analytics_frame(response), response.spot)
        analytics = summarize(frame, response.spot)
        capabilities = dict(response.capabilities)
        for field, capability in (("LTP", "LTP"), ("OI", "OI"),
                                  ("ChangeOI", "CHANGE_OI"), ("Volume", "VOLUME"),
                                  ("IV", "IV"), ("Bid", "BID_ASK"),
                                  ("Delta", "GREEKS")):
            values = frame[field].notna() if field in frame else None
            capabilities[capability] = "SUPPORTED" if values is not None and values.any() else "UNAVAILABLE"
        return {
            **response.dict(),
            "fallback_used": fallback_used,
            "analytics": analytics,
            "diagnostics": diagnostics,
            "capabilities": capabilities,
            "chain": frame.where(frame.notna(), None).to_dict("records"),
        }


__all__ = ["OptionsProviderRouter"]


def classify_provider_error(error: Exception) -> str:
    """Map provider failures to safe, stable diagnostics."""
    message = str(error).lower()
    if "429" in message or "rate" in message or "thrott" in message:
        return "RATE_LIMIT"
    if "timeout" in message or "timed out" in message:
        return "TIMEOUT"
    if "401" in message or "403" in message or "unauthor" in message:
        return "UPSTREAM_AUTH"
    if "404" in message or "unsupported" in message:
        return "UNSUPPORTED_SYMBOL"
    if "5xx" in message or "500" in message:
        return "UPSTREAM_5XX"
    return "TRANSIENT_FAILURE"
