"""Regression coverage for provider truthfulness in the options foundation."""

import pandas as pd

from options_algo import logic


def test_nse_chain_without_provider_expiries_is_explicitly_unavailable(monkeypatch):
    """Do not manufacture quotes when Yahoo exposes no NSE option chain."""

    class EmptyTicker:
        options = []

        def option_chain(self, _expiry):  # pragma: no cover - must not run
            raise AssertionError("option_chain must not run without expiries")

    monkeypatch.setattr(logic.yf, "Ticker", lambda _symbol: EmptyTicker())
    monkeypatch.setattr(
        "utils.db.fetch_options_chain_cache", lambda *_args, **_kwargs: None
    )
    monkeypatch.setattr("utils.db.upsert_options_chain_cache", lambda *args: None)

    chain, spot, _time_to_expiry = logic.fetch_option_chain(
        "RELIANCE.NS", "2099-12-30"
    )

    assert isinstance(chain, pd.DataFrame)
    assert chain.empty
    assert spot == 0.0
    assert set(chain.columns) == {
        "Strike",
        "Type",
        "IV",
        "Delta",
        "Gamma",
        "Theta",
        "Vega",
        "OI",
        "Premium",
        "contractSymbol",
    }


def test_nse_expiries_without_provider_data_are_not_invented(monkeypatch):
    class EmptyTicker:
        options = []

    monkeypatch.setattr(logic.yf, "Ticker", lambda _symbol: EmptyTicker())

    assert logic.get_available_expiries("NIFTY.NS") == []
