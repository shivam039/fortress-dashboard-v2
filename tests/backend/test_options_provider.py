from options_algo.providers import YFinanceOptionsProvider, _contract_from_row


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
