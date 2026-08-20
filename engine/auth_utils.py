# engine/auth_utils.py — JWT token utilities for the Fortress API
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
SECRET_KEY = os.environ.get(
    "FORTRESS_JWT_SECRET",
    "fortress-dev-jwt-secret-change-in-production-2024",
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
