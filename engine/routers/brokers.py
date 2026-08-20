# engine/routers/brokers.py — Broker connection management
"""
Broker connection CRUD.

- GET    /api/brokers              → list broker connections
- POST   /api/brokers              → connect/upsert broker token
- DELETE /api/brokers/{broker_name} → disconnect a broker
"""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from auth_utils import get_current_user

router = APIRouter(prefix="/api/brokers", tags=["brokers"])


class BrokerConnect(BaseModel):
    broker_name: str
    broker_client_id: str = ""
    access_token: str
    refresh_token: str = ""
    expires_at: Optional[str] = None


@router.get("")
async def list_brokers(user: dict = Depends(get_current_user)):
    """List broker connections for the authenticated user."""
    from utils.db import list_user_broker_connections

    username = user["sub"]
    if username == "guest_user":
        return []

    df = list_user_broker_connections(username)
    if df.empty:
        return []

    # Convert to records, masking sensitive fields
    records = df.to_dict(orient="records")
    for rec in records:
        rec.pop("access_token_encrypted", None)
        rec.pop("refresh_token_encrypted", None)
    return records


@router.post("", status_code=201)
async def connect_broker(
    body: BrokerConnect,
    user: dict = Depends(get_current_user),
):
    """Connect or update a broker token for the authenticated user."""
    from utils.db import upsert_user_broker_connection

    username = user["sub"]
    if username == "guest_user":
        raise HTTPException(status_code=403, detail="Guests cannot connect brokers")

    upsert_user_broker_connection(
        username=username,
        broker_name=body.broker_name,
        broker_client_id=body.broker_client_id.strip(),
        access_token=body.access_token.strip(),
        refresh_token=body.refresh_token.strip() if body.refresh_token else None,
        expires_at=body.expires_at or None,
    )

    return {
        "message": f"{body.broker_name} connected successfully.",
        "broker_name": body.broker_name,
    }


@router.delete("/{broker_name}")
async def disconnect_broker(
    broker_name: str,
    user: dict = Depends(get_current_user),
):
    """Disconnect a specific broker for the authenticated user."""
    from utils.db import delete_user_broker_connection

    username = user["sub"]
    if username == "guest_user":
        raise HTTPException(status_code=403, detail="Guests cannot manage brokers")

    delete_user_broker_connection(username, broker_name)
    return {"message": f"{broker_name} disconnected.", "broker_name": broker_name}
