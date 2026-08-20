# engine/routers/picks.py — Pick tracker endpoints
"""
Pick tracking for the stock screener.

- GET  /api/picks          → list user's tracked picks
- POST /api/picks          → record a new pick
- GET  /api/picks/summary  → win rate, avg P&L, best pick
"""

from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from auth_utils import get_current_user

router = APIRouter(prefix="/api/picks", tags=["picks"])


class PickRecord(BaseModel):
    symbol: str
    entry_price: float = 0
    target_price: float = 0
    stop_loss: float = 0
    strategy: str = ""
    raw_data: Optional[Dict[str, Any]] = None


@router.get("")
async def list_picks(
    pick_status: Optional[str] = Query(None, alias="status"),
    user: dict = Depends(get_current_user),
):
    """List tracked picks for the authenticated user."""
    from utils.db import get_user_id_by_username, get_user_picks

    username = user["sub"]
    if username == "guest_user":
        return []

    uid = get_user_id_by_username(username)
    if not uid:
        return []

    df = get_user_picks(uid, status=pick_status)
    return df.to_dict(orient="records") if not df.empty else []


@router.post("", status_code=201)
async def record_pick(
    pick: PickRecord,
    user: dict = Depends(get_current_user),
):
    """Record a new stock pick to track."""
    from utils.db import get_user_id_by_username
    from scripts.pick_tracker import record_pick as _record_pick

    username = user["sub"]
    if username == "guest_user":
        raise HTTPException(status_code=403, detail="Guests cannot track picks")

    uid = get_user_id_by_username(username)
    if not uid:
        raise HTTPException(status_code=404, detail="User not found")

    row_dict = pick.raw_data or {
        "Symbol": pick.symbol,
        "Price": pick.entry_price,
        "Target_10D": pick.target_price,
        "Stop_Loss": pick.stop_loss,
        "Strategy": pick.strategy,
    }

    _record_pick(uid, row_dict)
    return {"message": f"Pick tracked for {pick.symbol}.", "symbol": pick.symbol}


@router.get("/summary")
async def pick_summary(user: dict = Depends(get_current_user)):
    """Return pick outcome statistics."""
    from utils.db import get_user_id_by_username, get_pick_outcome_summary

    username = user["sub"]
    if username == "guest_user":
        return {"hit_rate": 0, "hits": 0, "misses": 0, "avg_pnl": 0, "avg_days": 0, "best_pnl": 0}

    uid = get_user_id_by_username(username)
    if not uid:
        return {"hit_rate": 0, "hits": 0, "misses": 0, "avg_pnl": 0, "avg_days": 0, "best_pnl": 0}

    return get_pick_outcome_summary(uid)
