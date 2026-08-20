# engine/routers/auth.py — Authentication endpoints (login, signup, guest)
"""
JWT-based auth router.

- POST /api/auth/login    → verify credentials, return JWT
- POST /api/auth/signup   → create account, return JWT
- POST /api/auth/guest    → issue guest JWT
- GET  /api/auth/me       → return current user profile from JWT
"""

import logging
import os
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel, Field

from auth_utils import (
    COOKIE_NAME,
    create_access_token,
    get_current_user,
)

logger = logging.getLogger("fortress.routers.auth")
router = APIRouter(prefix="/api/auth", tags=["auth"])


# ── Request / response models ────────────────────────────────────────────────

class LoginRequest(BaseModel):
    username: str
    password: str


class SignupRequest(BaseModel):
    username: str
    password: str
    full_name: Optional[str] = ""
    email: Optional[str] = ""


class AuthResponse(BaseModel):
    token: str
    username: str
    role: str
    message: str = "Success"


# ── Helpers ───────────────────────────────────────────────────────────────────

def _set_cookie(response: Response, token: str) -> None:
    """Set the JWT as an httpOnly, SameSite cookie."""
    response.set_cookie(
        key=COOKIE_NAME,
        value=token,
        httponly=True,
        samesite="none",
        secure=os.environ.get("FORTRESS_SECURE_COOKIE", "true").lower() == "true",
        max_age=60 * 60 * 24,  # 24 hours
        path="/",
    )


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.post("/login", response_model=AuthResponse)
async def login(req: LoginRequest, response: Response):
    """Verify credentials and return a JWT token."""
    from utils.db import verify_user_credentials, record_user_login, get_app_user
    from utils.db import upsert_app_user

    username = req.username.strip()
    admin_username = os.environ.get("FORTRESS_APP_USERNAME", "admin")

    # Admin login
    if username == admin_username:
        admin_pwd = os.environ.get("FORTRESS_APP_PASSWORD", "fortress123")
        if req.password != admin_pwd:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid credentials",
            )
        role = "admin"
    else:
        # DB user login
        if not verify_user_credentials(username, req.password):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid credentials",
            )
        role = "user"

    # Sync profile and record login
    upsert_app_user(username=username)
    record_user_login(username)

    token = create_access_token(username, role=role)
    _set_cookie(response, token)

    return AuthResponse(token=token, username=username, role=role)


@router.post("/signup", response_model=AuthResponse, status_code=201)
async def signup(req: SignupRequest, response: Response):
    """Create a new account and return a JWT token."""
    from utils.db import get_app_user, upsert_app_user

    username = req.username.strip()
    password = req.password.strip()

    if not username or not password:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Username and password are required.",
        )

    existing = get_app_user(username)
    if existing and existing.get("password_hash"):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Username already exists.",
        )

    upsert_app_user(
        username=username,
        full_name=req.full_name or "",
        email=req.email or "",
        password=password,
    )

    token = create_access_token(username, role="user")
    _set_cookie(response, token)

    return AuthResponse(
        token=token,
        username=username,
        role="user",
        message="Account created successfully.",
    )


@router.post("/guest", response_model=AuthResponse)
async def guest_login(response: Response):
    """Issue a guest JWT with limited scope."""
    token = create_access_token("guest_user", role="guest")
    _set_cookie(response, token)

    return AuthResponse(
        token=token,
        username="guest_user",
        role="guest",
        message="Guest session started.",
    )


@router.get("/me")
async def get_me(user: dict = Depends(get_current_user)):
    """Return the current user's profile."""
    from utils.db import get_app_user

    username = user["sub"]
    if username == "guest_user":
        return {
            "username": "guest_user",
            "full_name": "Guest Explorer",
            "email": "",
            "phone": "",
            "account_status": "Trial",
            "role": "guest",
            "last_login_at": None,
        }

    profile = get_app_user(username)
    profile["role"] = user.get("role", "user")
    return profile


@router.post("/logout")
async def logout(response: Response):
    """Clear the auth cookie."""
    response.delete_cookie(COOKIE_NAME, path="/")
    return {"message": "Logged out"}
