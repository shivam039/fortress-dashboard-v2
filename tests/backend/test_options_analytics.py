import pandas as pd
from datetime import datetime, timezone

from options_algo.analytics import add_moneyness, max_pain, pcr, to_analytics_frame
from options_algo.contracts import OptionChainResponse, OptionContract


def _chain():
    return pd.DataFrame(
        [
            {"Strike": 90, "Type": "CE", "OI": 10, "Volume": 5},
            {"Strike": 100, "Type": "CE", "OI": 20, "Volume": 10},
            {"Strike": 110, "Type": "CE", "OI": 30, "Volume": 15},
            {"Strike": 90, "Type": "PE", "OI": 30, "Volume": 15},
            {"Strike": 100, "Type": "PE", "OI": 20, "Volume": 10},
            {"Strike": 110, "Type": "PE", "OI": 10, "Volume": 5},
        ]
    )


def test_moneyness_handles_calls_and_puts():
    result = add_moneyness(_chain(), 100)
    assert result[result["Strike"].eq(100)]["Moneyness"].tolist() == [
        "ATM",
        "ATM",
    ]
    call_90 = result[(result["Type"] == "CE") & (result["Strike"] == 90)]
    put_90 = result[(result["Type"] == "PE") & (result["Strike"] == 90)]
    assert call_90["Moneyness"].iloc[0] == "ITM"
    assert put_90["Moneyness"].iloc[0] == "OTM"


def test_pcr_is_explicit_and_missing_data_is_unknown():
    assert pcr(_chain(), "OI") == 1.0
    assert pcr(_chain().drop(columns="OI"), "OI") is None


def test_max_pain_requires_complete_call_and_put_oi():
    assert max_pain(_chain()) == 100
    assert max_pain(_chain().iloc[:-1]) is None


def test_canonical_contracts_convert_without_turning_unknown_oi_into_zero():
    response = OptionChainResponse(
        underlying="RELIANCE.NS",
        underlying_symbol="RELIANCE.NS",
        expiry="2099-12-30",
        provider="test",
        received_at=datetime.now(timezone.utc),
        contracts=[
            OptionContract(
                underlying="RELIANCE.NS",
                expiry="2099-12-30",
                strike=100,
                option_type="CE",
            )
        ],
    )

    frame = to_analytics_frame(response)

    assert frame.loc[0, "Strike"] == 100
    assert pd.isna(frame.loc[0, "OI"])
