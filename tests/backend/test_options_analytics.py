import pandas as pd

from options_algo.analytics import add_moneyness, max_pain, pcr


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
    assert result[result["Strike"].eq(100)]["Moneyness"].tolist() == ["ATM", "ATM"]
    assert result[(result["Type"] == "CE") & (result["Strike"] == 90)]["Moneyness"].iloc[0] == "ITM"
    assert result[(result["Type"] == "PE") & (result["Strike"] == 90)]["Moneyness"].iloc[0] == "OTM"


def test_pcr_is_explicit_and_missing_data_is_unknown():
    assert pcr(_chain(), "OI") == 1.0
    assert pcr(_chain().drop(columns="OI"), "OI") is None


def test_max_pain_requires_complete_call_and_put_oi():
    assert max_pain(_chain()) == 100
    assert max_pain(_chain().iloc[:-1]) is None
