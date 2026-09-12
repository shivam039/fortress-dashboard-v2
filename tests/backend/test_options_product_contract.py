from pathlib import Path


OPTIONS_PAGE = Path(__file__).parents[2] / "frontend/src/app/options/page.tsx"


def test_legacy_strategy_scanner_is_not_presented_as_decision_support():
    source = OPTIONS_PAGE.read_text()
    assert "Legacy Strategy Scanner" in source
    assert "not a recommendation or risk model" in source
    assert "Strategy Lab" in source
