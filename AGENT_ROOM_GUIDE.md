# Agent Room Integration Guide

## Overview

The `create-agent-room` package has been seamlessly integrated into this project to provide governance, session logging, and safety guardrails when AI agents interact with the codebase. This guarantees a safe working environment without obstructing the standard human-driven development workflow.

The core of this system resides in the `.agent-room` directory.

## Features Added

1. **Safety Guardrails (`.agent-room/guardrails.json`)**: Prevents commits that touch highly sensitive paths or introduce hardcoded secrets.
    *   *Protected Paths:* `.env`, databases (`.db`, `.sqlite`), log files, and configuration files.
    *   *Forbidden Actions:* Blocks commits containing hardcoded AWS keys, private keys, API keys, slack tokens, passwords, secrets, or raw database URLs.
2. **Pre-commit Hook (`.git/hooks/pre-commit`)**: The safety guardrails are checked *before* a commit is allowed.
3. **Continuous Integration (`.github/workflows/agent-room-validate.yml`)**: A workflow has been created to ensure that any push to `main` (or PR) structurally conforms to the Agent Room's validity standards and that any session logs are properly formatted.
4. **Python Dashboard Skill (`.agent-room/skills/python-dashboard-security.md`)**: A custom agent skill created specifically for Streamlit & FastAPI security, best practices, caching, state management, and avoiding common anti-patterns within this dashboard.

## How to Use This Going Forward

### For Human Developers

*   **Standard Git Flow is Unchanged**: You can continue committing code exactly as you did before.
*   **Guardrail Blocks**: If you attempt to commit a file matching a forbidden pattern (e.g., adding an API key to a file), the pre-commit hook will block the commit with a detailed error message explaining why.
*   **Emergency Bypass**: If you genuinely need to bypass the security check (for example, intentionally adding a dummy API key to a test suite), prepend your commit command like so:
    ```bash
    GUARDRAILS_BYPASS=1 git commit -m "Intentionally commit test key"
    ```

### For AI Agents

*   **AGENTS.md**: Agents entering the repository will immediately read `AGENTS.md` and inherit context regarding the `create-agent-room` structure.
*   **Skills**: Agents will dynamically adopt the rules in `.agent-room/skills/python-dashboard-security.md` when tasked with editing the UI or the backend APIs.
*   **Session Logging**: For agents that support logging (like Cursor or custom bots), they will be forced to log decisions and anti-patterns they encounter into `.agent-room/decisions.md` and `.agent-room/anti-patterns.md`. The Claude Code Stop hook enforces this before they end their turn.

## Administration & Tweaks

*   **Need to change what is protected?** Edit `.agent-room/guardrails.json`.
*   **Need to add more agent capabilities?** Add new markdown files to `.agent-room/skills/` with the appropriate frontmatter.
*   **Check health:** If you manually change `.agent-room` files and want to ensure everything is valid, run:
    ```bash
    npx create-agent-room doctor .
    ```

    If npm registry policy blocks the package with `E403 Forbidden`, record the failure in the validation summary and rerun once registry access is restored. The project files can still be linted and tested locally.


## Repository Hygiene Notes

* Keep generated logs out of Git; `logs/` and `*.jsonl` are intentionally ignored.
* Keep one-off maintenance utilities in the root `scripts/` directory, and convert useful bug repros into pytest tests under `tests/`.
* Do not commit local virtual environments, caches, coverage output, SQLite databases, or Streamlit secrets.
