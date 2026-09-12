"""Provider-neutral contracts for truthful options data.

Provider adapters may support only a subset of these capabilities.  Nullable
quote fields deliberately distinguish an unknown value from a measured zero.
"""

from datetime import datetime
from enum import Enum
from typing import List, Optional, Protocol

from pydantic import BaseModel, Field


class CapabilityState(str, Enum):
    SUPPORTED = "SUPPORTED"
    UNSUPPORTED = "UNSUPPORTED"
    SESSION_ONLY = "SESSION_ONLY"
    UNVERIFIED = "UNVERIFIED"
    DEGRADED = "DEGRADED"


class OptionCapability(str, Enum):
    LIVE_CHAIN = "LIVE_CHAIN"
    EXPIRIES = "EXPIRIES"
    SPOT = "SPOT"
    LTP = "LTP"
    BID_ASK = "BID_ASK"
    OI = "OI"
    CHANGE_OI = "CHANGE_OI"
    VOLUME = "VOLUME"
    IV = "IV"
    GREEKS = "GREEKS"
    HISTORICAL_CHAIN = "HISTORICAL_CHAIN"
    HISTORICAL_OI = "HISTORICAL_OI"
    INTRADAY_HISTORY = "INTRADAY_HISTORY"


class OptionContract(BaseModel):
    underlying: str
    expiry: str
    strike: float
    option_type: str
    ltp: Optional[float] = None
    bid: Optional[float] = None
    ask: Optional[float] = None
    volume: Optional[int] = None
    open_interest: Optional[int] = None
    change_in_open_interest: Optional[int] = None
    iv: Optional[float] = None
    delta: Optional[float] = None
    gamma: Optional[float] = None
    theta: Optional[float] = None
    vega: Optional[float] = None
    lot_size: Optional[int] = None


class OptionChainResponse(BaseModel):
    underlying: str
    underlying_symbol: str
    spot: Optional[float] = None
    expiry: Optional[str] = None
    available_expiries: List[str] = Field(default_factory=list)
    provider: str
    provider_timestamp: Optional[datetime] = None
    received_at: datetime
    freshness: Optional[str] = None
    capabilities: dict[OptionCapability, CapabilityState] = Field(
        default_factory=dict
    )
    contracts: List[OptionContract] = Field(default_factory=list)


class OptionsProvider(Protocol):
    """Minimal adapter surface; historical methods remain optional."""

    def get_capabilities(self) -> dict[OptionCapability, CapabilityState]: ...

    def get_expiries(self, underlying: str) -> List[str]: ...

    def get_chain(
        self, underlying: str, expiry: str
    ) -> OptionChainResponse: ...

    def get_spot(self, underlying: str) -> Optional[float]: ...
