from options_algo.providers import YFinanceOptionsProvider, _contract_from_row

import pandas as pd


def test_yfinance_row_normalization_preserves_missing_values():
    contract = _contract_from_row(
        "RELIANCE.NS",
        "2099-12-30",
        {"Strike": 100, "Type": "CE", "OI": float("nan"), "IV": float("nan")},
    )

    assert contract.open_interest is None
    assert contract.iv is None
    assert contract.option_type == "CE"


def test_provider_capability_matrix_is_explicit():
    capabilities = YFinanceOptionsProvider().get_capabilities()

    assert capabilities["LIVE_CHAIN"].value == "SUPPORTED"
    assert capabilities["CHANGE_OI"].value == "UNSUPPORTED"


def test_get_spot_uses_quote_path(monkeypatch):
    def fail_if_chain_called(*args, **kwargs):
        raise AssertionError("spot lookup must not fetch an option chain")

    monkeypatch.setattr(
        "options_algo.providers.logic.fetch_option_chain", fail_if_chain_called
    )
    monkeypatch.setattr(
        "options_algo.providers.logic.yf.download",
        lambda *args, **kwargs: pd.DataFrame({"Close": [101.25]}),
    )

    assert YFinanceOptionsProvider().get_spot("RELIANCE.NS") == 101.25
