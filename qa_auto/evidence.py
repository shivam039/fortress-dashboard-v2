"""Redacted, machine-readable QA evidence helpers."""
import re
from typing import Any, Dict

_SECRET = re.compile(r"(?i)(authorization|cookie|api[-_]?key|token|password)\s*[:=]\s*[^\s,;]+")


def redact(value: Any) -> Any:
    if isinstance(value, str):
        return _SECRET.sub(r"\1=[REDACTED]", value)
    if isinstance(value, dict):
        return {str(key): redact(item) for key, item in value.items()}
    if isinstance(value, list):
        return [redact(item) for item in value]
    return value


def build_result(**fields: Any) -> Dict[str, Any]:
    from qa_auto.contract import validate_result
    return validate_result(redact(fields))
