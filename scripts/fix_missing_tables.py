#!/usr/bin/env python3
"""Ensure Fortress database tables exist for the configured backend.

This utility is intentionally small: it reuses the canonical database
initialization path instead of patching SQL definitions in-place. Run it after
setting the same environment variables used by the app, for example:

    FORTRESS_DB_BACKEND=sqlite python scripts/fix_missing_tables.py
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
ENGINE_DIR = ROOT_DIR / "engine"

for path in (ENGINE_DIR, ROOT_DIR):
    path_text = str(path)
    if path_text not in sys.path:
        sys.path.insert(0, path_text)

from engine.utils.db import get_db_backend, init_db  # noqa: E402


def main() -> int:
    """Initialize missing database tables for the active backend."""
    backend = get_db_backend()
    init_db()
    print(f"Database table check completed for backend: {backend}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
