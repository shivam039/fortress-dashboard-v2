"""
engine/utils/security_config.py — FORTRESS-H3 centralized production
security validation.

Single source of truth for "is this production?" and for validating the
handful of secrets/config values that must never be a known development
default once Fortress is actually serving traffic outside a developer's own
machine. `engine/auth_utils.py` (JWT secret) and `engine/routers/auth.py`
(admin password) call into the functions here at import time rather than
each duplicating their own "is this value unsafe?" comparison — this is
the one place that knows what "unsafe" means for each value, per
FORTRESS-H3's "prefer one centralized validation function, do not duplicate
checks across multiple routers".

Nothing in this module logs or raises with the actual secret/password
value in the message — every error here is safe to put in a log line, a
crash report, or a status page.
"""
from __future__ import annotations

import logging
import os
from typing import Iterable, Optional

logger = logging.getLogger("fortress.security")

# ── Known-unsafe values ──────────────────────────────────────────────────
# Anyone who has ever cloned this repo (or read its docs) knows these
# values, so a deployment still using one of them is trivially
# compromised — forge a JWT (including admin), or just log in as admin.
DEFAULT_JWT_SECRET = "fortress-dev-jwt-secret-change-in-production-2024"
DEFAULT_ADMIN_PASSWORD = "fortress123"

# Generic placeholders someone might type in manually (copy-pasted from a
# README example, or habit) rather than leaving the variable unset —
# rejected even though they were never this repo's actual default.
_GENERIC_UNSAFE_SECRETS = {"changeme", "change-me", "change_me", "secret", "your-secret-key", ""}
_GENERIC_UNSAFE_PASSWORDS = {"changeme", "change-me", "change_me", "password", "admin", "admin123", ""}

_KNOWN_UNSAFE_JWT_SECRETS = _GENERIC_UNSAFE_SECRETS | {DEFAULT_JWT_SECRET}
_KNOWN_UNSAFE_ADMIN_PASSWORDS = _GENERIC_UNSAFE_PASSWORDS | {DEFAULT_ADMIN_PASSWORD.lower()}


def is_production_environment() -> bool:
    """Fortress's single production-mode signal.

    Mirrors the convention `utils/db.py`'s `_sqlite_only_mode()` already
    established for the same underlying variable: local/dev must
    explicitly opt in via `FORTRESS_DB_BACKEND=sqlite` (or `"local"`).
    Anything else — unset, or `"neon"` — is treated as production, matching
    `db.py`'s own default-to-Neon behavior. This is the *only* flag
    Fortress uses to decide "production or not"; do not add another
    environment variable that means the same thing.
    """
    return os.getenv("FORTRESS_DB_BACKEND", "").strip().lower() not in {"sqlite", "local"}


def validate_jwt_secret(secret: Optional[str]) -> None:
    """Raise RuntimeError if `secret` is missing/blank or a known-unsafe
    value. Callers decide whether this applies (production only) — this
    function itself has no notion of dev vs. prod, it just says whether the
    value is safe. Never includes the secret's value in the message."""
    normalized = (secret or "").strip()
    if not normalized:
        raise RuntimeError(
            "FORTRESS_JWT_SECRET is not set (or is blank). Refusing to start "
            "in production without a real JWT signing secret — generate one "
            "with `openssl rand -hex 32` and set FORTRESS_JWT_SECRET."
        )
    if normalized in _KNOWN_UNSAFE_JWT_SECRETS:
        raise RuntimeError(
            "FORTRESS_JWT_SECRET is set to a known default/placeholder value "
            "(public in this repo's history or documentation). Refusing to "
            "start in production — anyone could forge a valid JWT, including "
            "admin, against this deployment. Generate a real secret with "
            "`openssl rand -hex 32`."
        )


def validate_admin_password(password: Optional[str]) -> None:
    """Raise RuntimeError if `password` is missing/blank or a known-unsafe
    value. Never includes the password's value in the message."""
    normalized = (password or "").strip()
    if not normalized:
        raise RuntimeError(
            "FORTRESS_APP_PASSWORD is not set (or is blank). Refusing to "
            "start in production without a real admin password — set "
            "FORTRESS_APP_PASSWORD (and consider FORTRESS_APP_USERNAME too)."
        )
    if normalized.lower() in _KNOWN_UNSAFE_ADMIN_PASSWORDS:
        raise RuntimeError(
            "FORTRESS_APP_PASSWORD is set to a known default/placeholder "
            "value (public in this repo's history or documentation). "
            "Refusing to start in production — set it to a real password."
        )


def validate_cors_origins(origins: Iterable[str]) -> None:
    """Raise RuntimeError if the resolved CORS allow-list contains a
    wildcard. Fortress's CORS middleware runs with allow_credentials=True;
    browsers already refuse a wildcard origin combined with credentials,
    but an operator could still set FORTRESS_CORS_ORIGINS=* by mistake and
    get a deployment that silently does nothing useful (or worse, on a
    browser/proxy that doesn't enforce the combination) — reject it
    explicitly rather than rely on browser behavior alone."""
    if any(o.strip() == "*" for o in origins):
        raise RuntimeError(
            "FORTRESS_CORS_ORIGINS resolves to a wildcard ('*') origin. "
            "Refusing to start in production with an unrestricted CORS "
            "origin — set FORTRESS_CORS_ORIGINS to the exact trusted "
            "frontend origin(s), comma-separated."
        )


def validate_security_configuration(
    jwt_secret: Optional[str],
    admin_password: Optional[str],
    cors_origins: Iterable[str],
    production: Optional[bool] = None,
) -> None:
    """The centralized entry point: validates every production-sensitive
    security value together, so there is exactly one place documenting
    what "safe" means for each of them (FORTRESS-H3).

    `production` defaults to `is_production_environment()`. It's accepted
    as a parameter — rather than always read from the environment inside
    this function — purely so tests can exercise both branches
    deterministically without monkeypatching env vars and reloading
    modules.

    Development (production=False): logs a warning for each unsafe value,
    never raises — the existing convenient-defaults workflow keeps working.
    Production (production=True): raises RuntimeError on the first unsafe
    value found (JWT secret, then admin password, then CORS), so startup
    fails clearly instead of serving requests with a known-forgeable
    session or open admin login.
    """
    if production is None:
        production = is_production_environment()

    if not production:
        jwt_normalized = (jwt_secret or "").strip()
        if not jwt_normalized or jwt_normalized in _KNOWN_UNSAFE_JWT_SECRETS:
            logger.warning(
                "FORTRESS_JWT_SECRET is unset or a known dev default — fine for "
                "local development, but this deployment will refuse to start "
                "with it once FORTRESS_DB_BACKEND is not sqlite/local."
            )
        pwd_normalized = (admin_password or "").strip()
        if not pwd_normalized or pwd_normalized.lower() in _KNOWN_UNSAFE_ADMIN_PASSWORDS:
            logger.warning(
                "FORTRESS_APP_PASSWORD is unset or a known dev default — fine "
                "for local development, but this deployment will refuse to "
                "start with it once FORTRESS_DB_BACKEND is not sqlite/local."
            )
        return

    validate_jwt_secret(jwt_secret)
    validate_admin_password(admin_password)
    validate_cors_origins(cors_origins)
