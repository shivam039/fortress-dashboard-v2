# engine/routers/users.py — User profile endpoints
"""
User profile management.

- GET  /api/users/profile   → get authenticated user's profile
- PUT  /api/users/profile   → update profile fields
- DELETE /api/users/delete   → delete account and cascade
"""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from auth_utils import get_current_user

router = APIRouter(prefix="/api/users", tags=["users"])


class ProfileUpdate(BaseModel):
    full_name: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None


@router.get("/profile")
async def get_profile(user: dict = Depends(get_current_user)):
    """Return the authenticated user's profile."""
    from utils.db import get_app_user

    username = user["sub"]
    if username == "guest_user":
        return {
            "username": "guest_user",
            "full_name": "Guest Explorer",
            "email": "",
            "phone": "",
            "account_status": "Trial",
            "last_login_at": None,
        }

    profile = get_app_user(username)
    if not profile:
        raise HTTPException(status_code=404, detail="User not found")
    return profile


@router.put("/profile")
async def update_profile(
    update: ProfileUpdate,
    user: dict = Depends(get_current_user),
):
    """Update profile fields for the authenticated user."""
    from utils.db import upsert_app_user, get_app_user

    username = user["sub"]
    if username == "guest_user":
        raise HTTPException(status_code=403, detail="Guests cannot update profiles")

    kwargs = {}
    if update.full_name is not None:
        kwargs["full_name"] = update.full_name
    if update.email is not None:
        kwargs["email"] = update.email
    if update.phone is not None:
        kwargs["phone"] = update.phone

    if kwargs:
        upsert_app_user(username=username, **kwargs)

    return get_app_user(username)


@router.delete("/delete")
async def delete_account(user: dict = Depends(get_current_user)):
    """Permanently delete the authenticated user's account."""
    from utils.db import delete_app_user

    username = user["sub"]
    if username == "guest_user":
        raise HTTPException(status_code=403, detail="Cannot delete guest account")

    delete_app_user(username)
    return {"message": f"Account '{username}' deleted permanently."}
