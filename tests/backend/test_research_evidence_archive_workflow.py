"""FORTRESS-NEXT Epic 17: workflow failure visibility for
.github/workflows/research-evidence-archive.yml.

Same narrow validation style as test_auto_scan_eod_workflow.py (workflow
code itself isn't Python-unit-testable): YAML parses, the main archive
step's shell passes `bash -n`, and a final `if: failure()` step exists
that writes a clear, greppable log line so a failed run isn't silent in
the Actions UI even before any external notification is checked.
"""
import subprocess

import yaml

_WORKFLOW_PATH = ".github/workflows/research-evidence-archive.yml"


def _load_workflow(path):
    with open(path) as f:
        return yaml.safe_load(f)


def _steps(path):
    doc = _load_workflow(path)
    return doc["jobs"][next(iter(doc["jobs"]))]["steps"]


def test_workflow_yaml_parses_and_has_schedule_and_dispatch():
    doc = _load_workflow(_WORKFLOW_PATH)
    triggers = doc[True]  # PyYAML parses the `on:` key as boolean True
    assert "schedule" in triggers
    assert "workflow_dispatch" in triggers


def test_workflow_concurrency_never_cancels_in_flight_run():
    doc = _load_workflow(_WORKFLOW_PATH)
    concurrency = doc["concurrency"]
    assert concurrency["cancel-in-progress"] is False


def test_workflow_archive_step_shell_syntax_is_valid():
    steps = _steps(_WORKFLOW_PATH)
    archive_step = next(s for s in steps if "run" in s and "curl" in s["run"])
    result = subprocess.run(
        ["bash", "-n"], input=archive_step["run"], text=True, capture_output=True
    )
    assert result.returncode == 0, result.stderr


def test_workflow_has_a_failure_step_with_greppable_log_line():
    steps = _steps(_WORKFLOW_PATH)
    failure_steps = [s for s in steps if s.get("if") == "failure()"]
    assert len(failure_steps) == 1, "expected exactly one if: failure() step"
    assert "EVIDENCE ARCHIVE FAILED" in failure_steps[0]["run"]


def test_workflow_never_prints_the_api_key():
    steps = _steps(_WORKFLOW_PATH)
    for step in steps:
        run = step.get("run", "")
        for forbidden in ("-v ", "--verbose", "--trace", "echo $API_KEY", 'echo "$API_KEY"'):
            assert forbidden not in run
