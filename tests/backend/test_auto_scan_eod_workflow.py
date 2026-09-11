"""FORTRESS-E3 scheduler reliability patch: narrowest useful validation of
the GitHub Actions workflow shell/JSON logic (workflow code itself isn't
Python-unit-testable). See docs/research/AUTO_SCAN_SCHEDULER_RELIABILITY.md.

Covers: YAML parses, the extracted shell passes `bash -n`, concurrency is
configured to never cancel an in-flight run, workflow_dispatch is present,
retry/poll loops are bounded, secrets are never echoed/traced, and the
run_id/status JSON-parsing logic behaves correctly for accepted+run_id,
missing run_id, empty run_id, and each terminal/non-terminal status.
"""
import subprocess

import yaml

_WORKFLOW_PATH = ".github/workflows/auto-scan-eod.yml"
_BHAVCOPY_WORKFLOW_PATH = ".github/workflows/bhavcopy-refresh.yml"


def _load_workflow(path):
    with open(path) as f:
        return yaml.safe_load(f)


def _script(path):
    doc = _load_workflow(path)
    return doc["jobs"][next(iter(doc["jobs"]))]["steps"][-1]["run"]


def test_workflow_yaml_parses_and_has_workflow_dispatch():
    doc = _load_workflow(_WORKFLOW_PATH)
    triggers = doc[True]  # PyYAML parses the `on:` key as boolean True
    assert "workflow_dispatch" in triggers
    assert "schedule" in triggers


def test_workflow_concurrency_never_cancels_in_flight_run():
    doc = _load_workflow(_WORKFLOW_PATH)
    concurrency = doc["concurrency"]
    assert concurrency["group"] == "fortress-auto-scan-eod"
    assert concurrency["cancel-in-progress"] is False


def test_workflow_shell_syntax_is_valid():
    script = _script(_WORKFLOW_PATH)
    result = subprocess.run(["bash", "-n"], input=script, text=True, capture_output=True)
    assert result.returncode == 0, result.stderr


def test_workflow_never_prints_the_api_key_and_uses_no_curl_trace_flags():
    script = _script(_WORKFLOW_PATH)
    for forbidden in ("-v ", "--verbose", "--trace", "echo $API_KEY", 'echo "$API_KEY"'):
        assert forbidden not in script


def test_workflow_retry_and_poll_loops_are_bounded():
    script = _script(_WORKFLOW_PATH)
    # Every loop is a bounded `seq 1 N`, never `while true`/`until false`.
    assert "while true" not in script
    assert "until false" not in script
    assert "WAKE_ATTEMPTS=12" in script
    assert "TRIGGER_ATTEMPTS=5" in script
    assert "MAX_POLLS=60" in script
    assert "POLL_INTERVAL_SECONDS=30" in script


def test_workflow_curl_calls_have_explicit_timeouts():
    script = _script(_WORKFLOW_PATH)
    assert "--connect-timeout" in script
    assert "--max-time" in script


def _run_id_from(json_body: str) -> str:
    result = subprocess.run(
        ["bash", "-c", 'jq -er \'.run_id // empty\' 2>/dev/null || echo ""'],
        input=json_body, text=True, capture_output=True,
    )
    return result.stdout.strip()


def test_run_id_extraction_accepted_response():
    assert _run_id_from('{"status": "accepted", "run_id": "abc-123"}') == "abc-123"


def test_run_id_extraction_missing_run_id_is_empty():
    assert _run_id_from('{"status": "accepted"}') == ""


def test_run_id_extraction_empty_run_id_string_is_empty():
    assert _run_id_from('{"status": "accepted", "run_id": ""}') == ""


def test_run_id_extraction_malformed_json_is_empty():
    assert _run_id_from("not json") == ""


def _status_from(json_body: str) -> str:
    result = subprocess.run(
        ["bash", "-c", 'jq -er \'.status // empty\' 2>/dev/null || echo ""'],
        input=json_body, text=True, capture_output=True,
    )
    return result.stdout.strip()


def test_status_extraction_terminal_and_non_terminal_states():
    assert _status_from('{"status": "COMPLETE"}') == "COMPLETE"
    assert _status_from('{"status": "DEGRADED"}') == "DEGRADED"
    assert _status_from('{"status": "FAILED"}') == "FAILED"
    assert _status_from('{"status": "RUNNING"}') == "RUNNING"
    assert _status_from("") == ""


def test_bhavcopy_workflow_also_has_wake_retry_and_bounded_poll_is_not_required():
    """Bhav Copy refresh is a fast, synchronous-enough job (unlike the
    ~30-minute multi-universe scan) — Part 8 asks only for the shared
    wake/retry pattern, not a durable-run poll loop it has no equivalent
    of."""
    script = _script(_BHAVCOPY_WORKFLOW_PATH)
    assert "while true" not in script
    assert "WAKE_ATTEMPTS=12" in script
    assert "--connect-timeout" in script
    assert "--max-time" in script


def test_bhavcopy_workflow_shell_syntax_is_valid():
    result = subprocess.run(["bash", "-n"], input=_script(_BHAVCOPY_WORKFLOW_PATH), text=True, capture_output=True)
    assert result.returncode == 0, result.stderr
