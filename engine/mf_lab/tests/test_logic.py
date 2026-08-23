import unittest

import numpy as np
import pandas as pd
from mf_lab.logic import detect_integrity_issues, enrich_mf_records_with_conviction


def test_enrich_mf_records_aliases_v1_fields_unambiguously():
    """The API returned v1's score/label under plain "Conviction Score"/
    "Conviction Label" and v2's under snake_case conviction_score_v2, with
    no v1-specific name at all — a new API consumer had no unambiguous way
    to ask for "the v1 score" without already knowing that distinction
    (see MF_SCORING.md §2/§10). enrich_mf_records_with_conviction now also
    aliases the v1 fields under explicit _v1-suffixed names, additively —
    the original keys must still be present and unchanged."""
    records = [
        {
            "Scheme": "Test Fund",
            "Conviction Score": 72.5,
            "Conviction Label": "BUY",
            "Conviction Emoji": "✅",
            "Sharpe": 1.1,
        }
    ]
    enriched = enrich_mf_records_with_conviction(records)
    r = enriched[0]
    assert r["conviction_score_v1"] == 72.5
    assert r["conviction_label_v1"] == "BUY"
    assert r["conviction_emoji_v1"] == "✅"
    # Originals untouched, for any existing consumer.
    assert r["Conviction Score"] == 72.5
    assert r["Conviction Label"] == "BUY"
    assert "conviction_score_v2" in r  # v2 still computed as before


class TestMFLabLogic(unittest.TestCase):
    def test_detect_integrity_issues(self):
        # Create mock data
        dates = pd.date_range(start="2020-01-01", periods=300)

        # Benchmark returns (random normal)
        np.random.seed(42)
        b_ret = np.random.normal(0.0005, 0.01, 300)
        benchmark_df = pd.DataFrame({"ret": b_ret}, index=dates)

        # Fund returns (slightly better than benchmark)
        f_ret = b_ret * 1.1 + 0.0001
        fund_df = pd.DataFrame({"date": dates, "ret": f_ret})

        # Run function
        result = detect_integrity_issues(fund_df, benchmark_df, "Large Cap")

        # Assertions
        self.assertIsNotNone(result)
        self.assertIn("alpha", result)
        self.assertIn("beta", result)
        self.assertIn("sortino", result)
        self.assertIn("upside", result)
        self.assertIn("downside", result)

        # Sanity checks
        self.assertGreater(result["beta"], 0.9)  # Should be close to 1.1
        self.assertGreater(result["alpha"], 0)  # Should be positive
        self.assertEqual(
            result["drift"], "✅ Stable"
        )  # Should be stable as beta 1.1 < 1.15

    def test_insufficient_data(self):
        dates = pd.date_range(start="2024-01-01", periods=50)
        b_ret = np.random.normal(0.0005, 0.01, 50)
        benchmark_df = pd.DataFrame({"ret": b_ret}, index=dates)
        fund_df = pd.DataFrame({"date": dates, "ret": b_ret})

        result = detect_integrity_issues(fund_df, benchmark_df, "Large Cap")
        self.assertIsNone(result)


if __name__ == "__main__":
    unittest.main()
