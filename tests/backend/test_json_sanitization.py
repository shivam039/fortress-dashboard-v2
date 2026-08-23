"""Tests for `_sanitize_json_value` in engine/main.py.

Context: this function exists because pandas/numpy readily produce values —
NaN, +/-Infinity, NaT, pd.NA — that are not valid JSON and make FastAPI's
default encoder blow up (or silently emit invalid JSON) whenever a scan or
scoring result is serialized in an API response. Two ad hoc root-level
scripts (test_nan.py, test_nan_bypasser.py) were used to manually poke at
this during debugging but never became real regression coverage — this file
replaces them with proper pytest assertions per the Agent Room repository
hygiene notes ("convert useful bug repros into pytest tests under tests/").
"""

import math

import numpy as np
import pandas as pd

from main import _sanitize_json_value


def test_none_stays_none():
    assert _sanitize_json_value(None) is None


def test_nan_becomes_none():
    assert _sanitize_json_value(float("nan")) is None


def test_positive_and_negative_infinity_become_none():
    assert _sanitize_json_value(float("inf")) is None
    assert _sanitize_json_value(float("-inf")) is None


def test_pandas_na_and_nat_become_none():
    assert _sanitize_json_value(pd.NA) is None
    assert _sanitize_json_value(pd.NaT) is None


def test_numpy_nan_and_inf_become_none():
    assert _sanitize_json_value(np.nan) is None
    assert _sanitize_json_value(np.float64("inf")) is None


def test_ordinary_numbers_pass_through_unchanged():
    assert _sanitize_json_value(42) == 42
    assert _sanitize_json_value(3.14) == 3.14
    assert _sanitize_json_value(0) == 0
    assert _sanitize_json_value(-17.5) == -17.5


def test_numpy_scalar_types_convert_to_python_types():
    result = _sanitize_json_value(np.float64(2.5))
    assert result == 2.5
    assert isinstance(result, float)

    result_int = _sanitize_json_value(np.int64(7))
    assert result_int == 7


def test_booleans_are_not_mistaken_for_numbers():
    # bool is a subclass of int in Python — make sure True/False survive
    # as booleans rather than being coerced to 1/0 or dropped.
    assert _sanitize_json_value(True) is True
    assert _sanitize_json_value(False) is False


def test_nested_dict_with_mixed_bad_values():
    value = {
        "a": 1.0,
        "b": float("nan"),
        "c": float("inf"),
        "d": pd.NA,
        "e": pd.NaT,
        "f": None,
    }
    result = _sanitize_json_value(value)
    assert result == {"a": 1.0, "b": None, "c": None, "d": None, "e": None, "f": None}


def test_nested_list_with_mixed_bad_values():
    value = [1.0, float("nan"), float("-inf"), pd.NA, 5]
    result = _sanitize_json_value(value)
    assert result == [1.0, None, None, None, 5]


def test_deeply_nested_structure_is_fully_sanitized():
    value = {"a": 1.0, "g": {"h": float("-inf"), "i": [1.0, float("nan")]}}
    result = _sanitize_json_value(value)
    assert result == {"a": 1.0, "g": {"h": None, "i": [1.0, None]}}


def test_dataframe_records_round_trip_is_json_safe():
    """Reproduces the exact shape from the original debug script: a
    DataFrame with every kind of bad value in one row, converted to
    records and sanitized the way an API response handler would."""
    df = pd.DataFrame(
        [
            {
                "a": 1.0,
                "b": np.nan,
                "c": float("inf"),
                "d": pd.NA,
                "e": pd.NaT,
                "f": [1.0, np.nan],
                "g": {"h": float("-inf")},
                "i": None,
            }
        ]
    )
    records = df.to_dict(orient="records")
    sanitized = [_sanitize_json_value(r) for r in records]

    assert sanitized[0]["a"] == 1.0
    assert sanitized[0]["b"] is None
    assert sanitized[0]["c"] is None
    assert sanitized[0]["d"] is None
    assert sanitized[0]["e"] is None
    assert sanitized[0]["f"] == [1.0, None]
    assert sanitized[0]["g"] == {"h": None}
    assert sanitized[0]["i"] is None

    # The whole point: json.dumps must not raise and must not emit the
    # bare NaN/Infinity tokens that are invalid per the JSON spec.
    import json

    encoded = json.dumps(sanitized)
    assert "NaN" not in encoded
    assert "Infinity" not in encoded
