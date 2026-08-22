# engine/auth_utils.py — JWT token utilities for the Fortress API
# AI agents modifying this file: see /AI_AGENT_PROTOCOL.md — log every change
# via engine/utils/ai_audit.py:log_ai_change().
"""
JWT token creation and validation for the Fortress API.

Tokens are issued as httpOnly cookies and/or Authorization headers.
"""

import os
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import Cookie, Depends, HTTPException, Request, status
from jose import JWTError, jwt

logger = logging.getLogger("fortress.auth")

# ── Configuration ─────────────────────────────────────────────────────────────
_DEFAULT_DEV_SECRET = "fortress-dev-jwt-secret-change-in-production-2024"
SECRET_KEY = os.environ.get("FORTRESS_JWT_SECRET", _DEFAULT_DEV_SECRET)


def _looks_like_local_dev() -> bool:
    # Mirrors engine/utils/db.py's _sqlite_only_mode(): the codebase's
    # established convention is that local dev must explicitly opt in via
    # FORTRESS_DB_BACKEND=sqlite (or "local") — see DEPLOYMENT.md / README.md.
    # Anything else (unset, or "neon") is treated as production-like, since
    # that's also db.py's own default-to-Neon behavior.
    return os.getenv("FORTRESS_DB_BACKEND", "").strip().lower() in {"sqlite", "local"}


if SECRET_KEY == _DEFAULT_DEV_SECRET:
    if _looks_like_local_dev():
        logger.warning(
            "FORTRESS_JWT_SECRET is not set — using the hardcoded dev default, "
            "which is public in this repo's git history. Anyone who reads the "
            "source can forge a valid JWT (including admin) against any "
            "deployment still using this default. Set FORTRESS_JWT_SECRET to a "
            "unique random value in any non-local environment (e.g. "
            "`openssl rand -hex 32`)."
        )
    else:
        # FORTRESS_DB_BACKEND isn't explicitly sqlite/local, so this looks
        # like a real deployment (Render, or anything pointed at Neon) —
        # refuse to start rather than silently serving forgeable JWTs.
        # Local dev is unaffected: DEPLOYMENT.md/README.md already have
        # everyone running locally set FORTRESS_DB_BACKEND=sqlite, and
        # tests/conftest.py sets it too.
        raise RuntimeError(
            "FORTRESS_JWT_SECRET is not set and this doesn't look like local "
            "dev (FORTRESS_DB_BACKEND is not 'sqlite'/'local'). Refusing to "
            "start with the hardcoded dev JWT secret, which is public in "
            "this repo's git history — anyone could forge a valid admin JWT "
            "against this deployment. Set FORTRESS_JWT_SECRET to a unique "
            "random value (e.g. `openssl rand -hex 32`), or set "
            "FORTRESS_DB_BACKEND=sqlite if this really is a local/dev run."
        )
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = int(
    os.environ.get("FORTRESS_JWT_EXPIRE_MINUTES", "1440")  # 24 hours default
)
COOKIE_NAME = "fortress_token"


# ── Token creation ────────────────────────────────────────────────────────────

def create_access_token(
    username: str,
    role: str = "user",
    expires_delta: Optional[timedelta] = None,
) -> str:
    """Create a signed JWT access token."""
    expire = datetime.now(timezone.utc) + (
        expires_delta or timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    )
    payload = {
        "sub": username,
        "role": role,
        "exp": expire,
        "iat": datetime.now(timezone.utc),
    }
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)


# ── Token validation ──────────────────────────────────────────────────────────

def decode_token(token: str) -> dict:
    """Decode and validate a JWT token. Raises HTTPException on failure."""
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        username: str = payload.get("sub", "")
        if not username:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid token: missing subject",
            )
        return payload
    except JWTError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Invalid or expired token: {exc}",
        ) from exc


async def get_current_user(
    request: Request,
    fortress_token: Optional[str] = Cookie(None),
) -> dict:
    """
    Extract the current user from:
      1. httpOnly cookie ``fortress_token``  (primary — used by Next.js frontend)
      2. ``Authorization: Bearer <token>`` header  (fallback — for API clients)

    Returns the decoded JWT payload dict with keys: sub, role, exp, iat.
    """
    token: Optional[str] = None

    # 1. Cookie
    if fortress_token:
        token = fortress_token

    # 2. Authorization header
    if not token:
        auth_header = request.headers.get("Authorization", "")
        if auth_header.startswith("Bearer "):
            token = auth_header[7:]

    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated. Provide a token via cookie or Authorization header.",
        )

    return decode_token(token)


async def get_current_username(user: dict = Depends(get_current_user)) -> str:
    """Convenience dependency — returns just the username string."""
    return user["sub"]
