"""Validation and safety rules for agent-driven product QA."""
from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, List


class Status(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"
    BLOCKED = "BLOCKED"
    NOT_APPLICABLE = "NOT_APPLICABLE"


class ActionClass(str, Enum):
    READ_ONLY = "READ_ONLY"
    SAFE_TEST_MUTATION = "SAFE_TEST_MUTATION"
    FORBIDDEN_PRODUCTION_MUTATION = "FORBIDDEN_PRODUCTION_MUTATION"


class Severity(str, Enum):
    QA0 = "QA0"
    QA1 = "QA1"
    QA2 = "QA2"
    QA3 = "QA3"


@dataclass
class Scenario:
    target_area: str
    route: str
    environment: str
    expected_behavior: str
    allowed_actions: List[ActionClass]
    forbidden_actions: List[ActionClass]


def assert_action_allowed(action: ActionClass, environment: str) -> None:
    if environment == "PRODUCTION" and action != ActionClass.READ_ONLY:
        raise PermissionError("QA mutations are forbidden in production")
    if action == ActionClass.FORBIDDEN_PRODUCTION_MUTATION:
        raise PermissionError("forbidden QA action")


def validate_result(result: Dict[str, Any]) -> Dict[str, Any]:
    required = {"run_id", "agent", "provider", "environment", "surface", "scenario", "status", "severity", "evidence", "duration"}
    missing = required - result.keys()
    if missing:
        raise ValueError(f"missing QA result fields: {sorted(missing)}")
    if result["status"] not in {item.value for item in Status}:
        raise ValueError("invalid QA status")
    if result["severity"] not in {item.value for item in Severity}:
        raise ValueError("invalid QA severity")
    return result
