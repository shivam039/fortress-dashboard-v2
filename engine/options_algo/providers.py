"""Options provider adapters and explicit capability reporting."""

from datetime import datetime, timezone
from typing import Dict, List, Optional

import pandas as pd

from options_algo import logic
from options_algo.contracts import (
    CapabilityState,
    OptionCapability,
    OptionChainResponse,
    OptionContract,
    OptionsProvider,
)


class YFinanceOptionsProvider:
    """Adapter around the existing yfinance-backed options implementation."""

    name = "yfinance"

    def get_capabilities(self) -> Dict[OptionCapability, CapabilityState]:
        return {
            OptionCapability.LIVE_CHAIN: CapabilityState.SUPPORTED,
            OptionCapability.EXPIRIES: CapabilityState.SUPPORTED,
            OptionCapability.SPOT: CapabilityState.SUPPORTED,
            OptionCapability.LTP: CapabilityState.SUPPORTED,
            OptionCapability.OI: CapabilityState.SUPPORTED,
            OptionCapability.VOLUME: CapabilityState.SUPPORTED,
            OptionCapability.IV: CapabilityState.SUPPORTED,
            OptionCapability.BID_ASK: CapabilityState.UNVERIFIED,
            OptionCapability.CHANGE_OI: CapabilityState.UNSUPPORTED,
            OptionCapability.GREEKS: CapabilityState.UNSUPPORTED,
            OptionCapability.HISTORICAL_CHAIN: CapabilityState.UNSUPPORTED,
            OptionCapability.HISTORICAL_OI: CapabilityState.UNSUPPORTED,
            OptionCapability.INTRADAY_HISTORY: CapabilityState.UNSUPPORTED,
        }

    def get_expiries(self, underlying: str) -> List[str]:
        return logic.get_available_expiries(underlying)

    def get_spot(self, underlying: str) -> Optional[float]:
        quote = logic.yf.download(underlying, period="2d", progress=False)
        if quote.empty or "Close" not in quote:
            return None
        closes = quote["Close"].dropna()
        return float(closes.iloc[-1]) if not closes.empty else None

    def get_chain(self, underlying: str, expiry: str) -> OptionChainResponse:
        frame, spot, _ = logic.fetch_option_chain(underlying, expiry)
        contracts = []
        for row in frame.to_dict("records"):
            try:
                contracts.append(_contract_from_row(underlying, expiry, row))
            except (KeyError, TypeError, ValueError):
                # Preserve valid contracts; malformed rows are never coerced.
                continue
        return OptionChainResponse(
            underlying=underlying,
            underlying_symbol=underlying,
            spot=spot or None,
            expiry=expiry,
            available_expiries=self.get_expiries(underlying),
            provider=self.name,
            received_at=datetime.now(timezone.utc),
            capabilities=self.get_capabilities(),
            contracts=contracts,
        )


def _nullable_int(value):
    if pd.isna(value):
        return None
    return int(value)


def _nullable_float(value):
    if pd.isna(value):
        return None
    return float(value)


def _contract_from_row(
    underlying: str, expiry: str, row: dict
) -> OptionContract:
    return OptionContract(
        underlying=underlying,
        expiry=expiry,
        strike=float(row["Strike"]),
        option_type=row["Type"],
        ltp=_nullable_float(row.get("LTP", row.get("Premium"))),
        bid=_nullable_float(row.get("Bid")),
        ask=_nullable_float(row.get("Ask")),
        volume=_nullable_int(row.get("Volume")),
        open_interest=_nullable_int(row.get("OI")),
        iv=_nullable_float(row.get("IV")),
        delta=_nullable_float(row.get("Delta")),
        gamma=_nullable_float(row.get("Gamma")),
        theta=_nullable_float(row.get("Theta")),
        vega=_nullable_float(row.get("Vega")),
    )


__all__ = ["OptionsProvider", "YFinanceOptionsProvider"]
