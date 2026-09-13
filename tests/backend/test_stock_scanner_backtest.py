import pandas as pd
import pytest

from stock_scanner.logic import _anchored_forward_return


def test_forward_return_is_anchored_to_scan_timestamp():
    dates = pd.date_range("2026-01-01", periods=5, freq="D")
    prices = pd.Series([100, 110, 120, 130, 140], index=dates)

    assert _anchored_forward_return(prices, "2026-01-02", 2) == pytest.approx(18.18181818181818)


def test_forward_return_is_nan_when_horizon_is_not_available():
    prices = pd.Series([100, 110], index=pd.date_range("2026-01-01", periods=2))

    assert pd.isna(_anchored_forward_return(prices, "2026-01-01", 7))
