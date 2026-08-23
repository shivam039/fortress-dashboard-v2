"""Tests for engine/mf_lab/logic.py's classify_category().

Context: two real gaps were reported against the live MF Lab UI:
  1. Flexi Cap and Multi Cap funds (distinct SEBI categories with different
     equity-allocation mandates) were both lumped into one "Flexi/Multi Cap"
     sub-category.
  2. Hybrid funds almost never landed in a specific sub-category (Multi
     Asset / Conservative / Balanced / Aggressive) because the keyword list
     only matched scheme names that spelled those terms out verbatim
     ("aggressive hybrid", "conservative hybrid") — most real AMC scheme
     names don't ("Equity & Debt Fund", "Balanced Fund", "Multi-Asset
     Allocation Fund"), so nearly everything fell into "General Hybrid".

Along the way, a related latent bug was found and fixed: primary-category
detection checked Debt keywords before Hybrid keywords, so a name like
"XYZ Debt Hybrid Fund" (which contains both "debt" and "hybrid") was
classified Debt instead of Hybrid. These tests lock in the fix.
"""

from mf_lab.logic import classify_category


def test_flexi_cap_and_multi_cap_are_separate_sub_categories():
    assert classify_category("Parag Parikh Flexi Cap Fund") == ("Equity", "Flexi Cap")
    assert classify_category("Kotak Multicap Fund") == ("Equity", "Multi Cap")
    assert classify_category("HDFC Multi Cap Fund") == ("Equity", "Multi Cap")


def test_flexi_cap_hyphenated_name_still_matches():
    assert classify_category("XYZ Flexi-Cap Fund") == ("Equity", "Flexi Cap")


def test_large_mid_small_cap_unaffected_by_flexi_multi_split():
    assert classify_category("XYZ Large Cap Fund") == ("Equity", "Large Cap")
    assert classify_category("XYZ Mid Cap Fund") == ("Equity", "Mid Cap")
    assert classify_category("XYZ Small Cap Fund") == ("Equity", "Small Cap")


def test_hybrid_aggressive_from_generic_balanced_name():
    # SEBI's 2018 recategorization folded plain "Balanced Fund" naming into
    # Aggressive Hybrid; this is the most common real-world hybrid name.
    assert classify_category("ICICI Prudential Balanced Fund") == ("Hybrid", "Aggressive Hybrid")


def test_hybrid_aggressive_from_equity_and_debt_name():
    assert classify_category("ICICI Prudential Equity & Debt Fund") == ("Hybrid", "Aggressive Hybrid")


def test_hybrid_conservative_from_generic_conservative_name():
    assert classify_category("XYZ Conservative Fund") == ("Hybrid", "Conservative Hybrid")


def test_hybrid_multi_asset_hyphenated_name_matches():
    assert classify_category("XYZ Multi-Asset Allocation Fund") == ("Hybrid", "Multi Asset")


def test_hybrid_balanced_advantage_not_shadowed_by_generic_balanced():
    # "balanced advantage" must win over the generic "balanced" catch-all.
    assert classify_category("HDFC Balanced Advantage Fund") == ("Hybrid", "Balanced Advantage")


def test_hybrid_balanced_hybrid_is_distinct_from_aggressive_hybrid():
    assert classify_category("XYZ Balanced Hybrid Fund") == ("Hybrid", "Balanced Hybrid")


def test_hybrid_equity_savings_is_its_own_sub_category():
    assert classify_category("XYZ Equity Savings Fund") == ("Hybrid", "Equity Savings")


def test_hybrid_arbitrage_unaffected():
    assert classify_category("XYZ Arbitrage Fund") == ("Hybrid", "Arbitrage")


def test_debt_hybrid_name_classifies_as_hybrid_not_debt():
    # Regression: "debt" and "hybrid" both appear in this name; Hybrid
    # signals must be checked first so this doesn't get swallowed into Debt.
    assert classify_category("XYZ Debt Hybrid Fund") == ("Hybrid", "Conservative Hybrid")


def test_conservative_hybrid_name_classifies_as_hybrid_not_debt():
    assert classify_category("Canara Robeco Conservative Hybrid Fund") == ("Hybrid", "Conservative Hybrid")


def test_pure_debt_funds_still_classify_as_debt():
    assert classify_category("XYZ Liquid Fund") == ("Debt", "Liquid")
    assert classify_category("XYZ Corporate Bond Fund") == ("Debt", "Corporate/Dynamic Bond")
    assert classify_category("XYZ Gilt Fund") == ("Debt", "Gilt")


def test_pure_equity_funds_still_classify_as_equity():
    assert classify_category("XYZ ELSS Tax Saver Fund") == ("Equity", "ELSS (Tax Saver)")
    assert classify_category("XYZ Nifty Index Fund") == ("Equity", "Index Fund")
