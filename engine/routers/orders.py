# engine/routers/orders.py — Order management endpoints
"""
Fortress order tracking.

- GET  /api/orders       → list orders (with filters)
- POST /api/orders       → create an order
- GET  /api/orders/stats → order summary metrics
"""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from auth_utils import get_current_user

router = APIRouter(prefix="/api/orders", tags=["orders"])


class OrderCreate(BaseModel):
    symbol: str
    stock_name: str = ""
    order_type: str = "Buy"
    quantity: float = 1
    price: float = 0
    status: str = "Pending"
    broker_name: str = "Zerodha"
    notes: str = ""


@router.get("")
async def list_orders(
    status_filter: Optional[str] = Query(None, alias="status"),
    broker_name: Optional[str] = Query(None, alias="broker"),
    date_from: Optional[str] = Query(None),
    date_to: Optional[str] = Query(None),
    limit: int = Query(100, ge=1, le=500),
    user: dict = Depends(get_current_user),
):
    """List orders for the authenticated user with optional filters."""
    from utils.db import fetch_fortress_orders

    username = user["sub"]
    df = fetch_fortress_orders(
        username=username,
        status=status_filter if status_filter != "All" else None,
        broker_name=broker_name if broker_name != "All" else None,
        date_from=date_from or None,
        date_to=date_to or None,
    )

    records = df.head(limit).to_dict(orient="records") if not df.empty else []
    return records


@router.post("", status_code=201)
async def create_order(
    order: OrderCreate,
    user: dict = Depends(get_current_user),
):
    """Create a new order for the authenticated user."""
    from utils.db import create_fortress_order

    username = user["sub"]
    if username == "guest_user":
        raise HTTPException(status_code=403, detail="Guests cannot create orders")

    create_fortress_order(
        username=username,
        symbol=order.symbol,
        stock_name=order.stock_name or order.symbol,
        order_type=order.order_type,
        quantity=order.quantity,
        price=order.price,
        status=order.status,
        broker_name=order.broker_name,
        notes=order.notes,
    )

    return {"message": f"Order for {order.symbol} created.", "symbol": order.symbol}


@router.get("/stats")
async def order_stats(user: dict = Depends(get_current_user)):
    """Return order summary metrics for the authenticated user."""
    from utils.db import fetch_fortress_orders

    username = user["sub"]
    df = fetch_fortress_orders(username=username)

    total = len(df)
    executed = int((df["status"] == "Executed").sum()) if not df.empty else 0
    pending = int((df["status"] == "Pending").sum()) if not df.empty else 0
    rejected = int((df["status"] == "Rejected").sum()) if not df.empty else 0
    # The Orders page's status filter offers "Cancelled" as an option
    # (frontend/src/app/orders/page.tsx) but this endpoint never counted
    # it, so a cancelled order silently vanished from every stat here
    # while still showing up in the (separately-fetched) orders list.
    cancelled = int((df["status"] == "Cancelled").sum()) if not df.empty else 0

    return {
        "total": total,
        "executed": executed,
        "pending": pending,
        "rejected": rejected,
        "cancelled": cancelled,
    }
