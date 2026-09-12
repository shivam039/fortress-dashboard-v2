from qa_auto.evidence import build_result, redact


def test_evidence_redacts_credentials():
    assert "secret" not in redact("Authorization: secret")


def test_build_result_keeps_structured_evidence():
    result = build_result(run_id="r", agent="qa", provider="manual",
                          environment="LOCAL", surface="Dashboard",
                          scenario="loads", status="PASS", severity="QA3",
                          evidence={"route": "/dashboard"}, duration=1)
    assert result["evidence"]["route"] == "/dashboard"
