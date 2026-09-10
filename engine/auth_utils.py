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

from utils.security_config import (
    DEFAULT_JWT_SECRET as _DEFAULT_DEV_SECRET,
    is_production_environment,
    validate_jwt_secret,
)

logger = logging.getLogger("fortress.auth")

# ── Configuration ─────────────────────────────────────────────────────────────
SECRET_KEY = os.environ.get("FORTRESS_JWT_SECRET", _DEFAULT_DEV_SECRET)

# FORTRESS-H3: production must fail to start rather than silently sign
# forgeable JWTs — see utils/security_config.py for what counts as
# "production" and what counts as an unsafe secret (never logged/raised
# with its actual value). Development keeps the pre-existing
# warn-and-continue behavior so the convenient hardcoded default still
# works for `FORTRESS_DB_BACKEND=sqlite` local runs.
if is_production_environment():
    validate_jwt_secret(SECRET_KEY)
elif not SECRET_KEY.strip() or SECRET_KEY.strip() == _DEFAULT_DEV_SECRET:
    logger.warning(
        "FORTRESS_JWT_SECRET is not set — using the hardcoded dev default, "
        "which is public in this repo's git history. Anyone who reads the "
        "source can forge a valid JWT (including admin) against any "
        "deployment still using this default. Set FORTRESS_JWT_SECRET to a "
        "unique random value in any non-local environment (e.g. "
        "`openssl rand -hex 32`)."
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
