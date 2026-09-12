import pytest

from qa_auto.contract import ActionClass, assert_action_allowed, validate_result


def test_production_qa_allows_read_only_only():
    assert_action_allowed(ActionClass.READ_ONLY, "PRODUCTION")
    with pytest.raises(PermissionError):
        assert_action_allowed(ActionClass.SAFE_TEST_MUTATION, "PRODUCTION")


def test_structured_result_requires_contract_fields():
    result = {"run_id": "r1", "agent": "qa", "provider": "manual",
              "environment": "STAGING", "surface": "Dashboard",
              "scenario": "loads", "status": "PASS", "severity": "QA3",
              "evidence": [], "duration": 0.1}
    assert validate_result(result)["status"] == "PASS"
