from pathlib import Path


def test_indmoney_options_feasibility_is_conservative_and_explicit():
    document = Path(__file__).parents[2] / "docs/options/PROVIDER_FEASIBILITY.md"
    text = document.read_text()
    assert "INDMONEY_SESSION_ONLY / UNVERIFIED" in text
    assert "no safe, documented server-callable INDmoney" in text
    assert "must not be automated" in text
