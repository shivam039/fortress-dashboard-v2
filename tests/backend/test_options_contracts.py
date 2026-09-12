from datetime import datetime, timezone

from options_algo.contracts import (
    CapabilityState,
    OptionCapability,
    OptionChainResponse,
    OptionContract,
)


def test_missing_option_metrics_remain_unknown_not_zero():
    contract = OptionContract(
        underlying="RELIANCE.NS",
        expiry="2099-12-30",
        strike=2500,
        option_type="CE",
    )

    assert contract.open_interest is None
    assert contract.iv is None
    assert contract.ltp is None


def test_chain_contract_exposes_provider_capabilities():
    response = OptionChainResponse(
        underlying="RELIANCE.NS",
        underlying_symbol="RELIANCE.NS",
        provider="test",
        received_at=datetime.now(timezone.utc),
        capabilities={
            OptionCapability.LIVE_CHAIN: CapabilityState.UNSUPPORTED,
            OptionCapability.OI: CapabilityState.UNVERIFIED,
        },
    )

    assert response.capabilities[OptionCapability.OI] == CapabilityState.UNVERIFIED
    assert response.contracts == []
