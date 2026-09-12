"""Deterministic provider routing for the normalized options API."""

from datetime import datetime, timezone
from typing import Dict, Optional

from options_algo.analytics import summarize, to_analytics_frame
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
            expiries = provider.get_expiries(underlying)
            if not expiries:
                diagnostics[provider.name] = "NO_EXPIRIES"
                continue
            selected = expiry or expiries[0]
            if selected not in expiries:
                diagnostics[provider.name] = "EXPIRY_UNAVAILABLE"
                continue
            response = provider.get_chain(underlying, selected)
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

    @staticmethod
    def as_api_payload(
        response: OptionChainResponse,
        fallback_used: bool,
        diagnostics: Dict[str, str],
    ) -> dict:
        frame = to_analytics_frame(response)
        analytics = summarize(frame, response.spot)
        return {
            **response.dict(),
            "fallback_used": fallback_used,
            "analytics": analytics,
            "diagnostics": diagnostics,
            "chain": frame.where(frame.notna(), None).to_dict("records"),
        }


__all__ = ["OptionsProviderRouter"]
