"""
AI Agent Protocol Module
Reference: /AI_AGENT_PROTOCOL.md

This module implements the logging infrastructure for the mandatory AI Agent Guardrails System.
Any AI agent modifying this codebase MUST ensure their changes are logged using `log_ai_change`.
"""

import json
import logging
import os
from datetime import datetime
from typing import Any, Dict, List

import pytz

logger = logging.getLogger(__name__)

AUDIT_LOG_FILE = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
    "logs",
    "ai_audit_log.jsonl",
)


def log_ai_change(
    agent_name: str,
    files_changed: List[str],
    summary: str,
    reason: str,
    commit_message: str,
    status: str = "Checklist Confirmed",
) -> bool:
    """
    Append a new change record to the AI Audit Log.

    Args:
        agent_name: Name of the AI Agent (e.g., "Jules", "Codex").
        files_changed: List of file paths modified.
        summary: Brief summary of the changes made.
        reason: Why the change was made (usually the user request).
        commit_message: The commit message used for the change.
        status: Confirmation status of the AI Protocol checklist.

    Returns:
        bool: True if logged successfully, False otherwise.
    """
    try:
        ist_tz = pytz.timezone("Asia/Kolkata")
        timestamp = datetime.now(ist_tz).isoformat()

        record = {
            "timestamp": timestamp,
            "agent": agent_name,
            "files_changed": files_changed,
            "summary": summary,
            "reason": reason,
            "commit_message": commit_message,
            "status": status,
        }

        # Ensure directory exists
        os.makedirs(os.path.dirname(AUDIT_LOG_FILE), exist_ok=True)

        with open(AUDIT_LOG_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(record) + "\n")

        logger.info(f"AI change logged by {agent_name}")
        return True
    except Exception as e:
        logger.error(f"Failed to log AI change: {e}")
        return False


def get_recent_ai_changes(limit: int = 20) -> List[Dict[str, Any]]:
    """
    Retrieve the most recent changes from the AI Audit Log.

    Args:
        limit: Maximum number of recent records to return.

    Returns:
        List[Dict]: List of parsed JSON log entries.
    """
    if not os.path.exists(AUDIT_LOG_FILE):
        return []

    try:
        records = []
        with open(AUDIT_LOG_FILE, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        records.append(json.loads(line))
                    except json.JSONDecodeError:
                        continue

        # Return the last 'limit' records in reverse chronological order (newest first)
        return list(reversed(records))[:limit]
    except Exception as e:
        logger.error(f"Failed to read AI audit log: {e}")
        return []
