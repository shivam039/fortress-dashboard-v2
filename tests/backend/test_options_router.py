from datetime import datetime, timezone

from options_algo.contracts import OptionChainResponse, OptionContract
from options_algo.router import OptionsProviderRouter


class FakeProvider:
    name = "fake"

    def get_expiries(self, underlying):
        return ["2026-10-01"]

    def get_chain(self, underlying, expiry):
        return OptionChainResponse(
            underlying=underlying,
            underlying_symbol=underlying,
            spot=100,
            expiry=expiry,
            available_expiries=[expiry],
            provider=self.name,
            received_at=datetime.now(timezone.utc),
            contracts=[
                OptionContract(
                    underlying=underlying,
                    expiry=expiry,
                    strike=100,
                    option_type="CE",
                    ltp=2.5,
                    open_interest=None,
                )
            ],
        )


def test_router_selects_real_expiry_and_preserves_unknown_values():
    response, fallback, diagnostics = OptionsProviderRouter(
        providers=[FakeProvider()]
    ).get_chain("RELIANCE.NS")

    assert response.expiry == "2026-10-01"
    assert response.contracts[0].open_interest is None
    assert fallback is False
    assert diagnostics == {}


def test_router_reports_no_expiries_without_fabricating_data():
    class EmptyProvider(FakeProvider):
        def get_expiries(self, underlying):
            return []

    response, _, diagnostics = OptionsProviderRouter(
        providers=[EmptyProvider()]
    ).get_chain("NIFTY")

    assert response.provider == "unavailable"
    assert response.contracts == []
    assert diagnostics == {"fake": "NO_EXPIRIES"}


def test_router_isolates_provider_exception():
    class BrokenProvider(FakeProvider):
        def get_expiries(self, underlying):
            raise TimeoutError("provider timeout")

    response, _, diagnostics = OptionsProviderRouter(
        providers=[BrokenProvider()]
    ).get_chain("NIFTY")

    assert response.provider == "unavailable"
    assert diagnostics == {"fake": "TIMEOUT"}
