# engine/routers/telegram.py — Telegram alert endpoints
"""
Telegram notification endpoints.

- POST /api/telegram/send-tip       → send stock tip alert
- POST /api/telegram/send-commodity → send commodity alert
- GET  /api/telegram/subscribers    → get subscriber list
- PUT  /api/telegram/subscribers    → update subscriber list
"""

import logging
import sys
from pathlib import Path
from typing import Any, Dict

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from auth_utils import get_current_user

logger = logging.getLogger("fortress.routers.telegram")
router = APIRouter(prefix="/api/telegram", tags=["telegram"])

_ENGINE_DIR = Path(__file__).resolve().parents[1]
_SCRIPTS_DIR = _ENGINE_DIR / "scripts"
_SUBS_FILE = _SCRIPTS_DIR / "telegram_subscribers.txt"


def _ensure_scripts_path() -> None:
    scripts_path = str(_SCRIPTS_DIR)
    if scripts_path not in sys.path:
        sys.path.append(scripts_path)


class TipPayload(BaseModel):
    """Stock tip data — matches the row dict from scan results."""
    symbol: str
    price: float = 0
    score: float = 0
    strategy: str = ""
    target_10d: float = 0
    stop_loss: float = 0
    raw_data: Dict[str, Any] = {}


class CommodityPayload(BaseModel):
    commodity_name: str
    data: Dict[str, Any] = {}


class SubscriberUpdate(BaseModel):
    chat_ids: str  # comma-separated chat IDs


@router.post("/send-tip")
async def send_tip(
    payload: TipPayload,
    user: dict = Depends(get_current_user),
):
    """Send a stock tip alert to Telegram subscribers."""
    _ensure_scripts_path()
    try:
        import telegram_bot
        from telegram_bot import format_telegram_message, send_telegram_message

        # Read subscribers
        subs = _read_subscribers()
        if subs:
            telegram_bot.TELEGRAM_CHAT_ID = subs

        row_data = payload.raw_data or {
            "Symbol": payload.symbol,
            "Price": payload.price,
            "Score": payload.score,
            "Strategy": payload.strategy,
            "Target_10D": payload.target_10d,
            "Stop_Loss": payload.stop_loss,
        }

        # format_telegram_message expects a Series-like object
        import pandas as pd
        row = pd.Series(row_data)
        msg = format_telegram_message(row)
        success = send_telegram_message(msg)

        if success:
            return {"message": f"Tip sent for {payload.symbol}"}
        raise HTTPException(status_code=500, detail="Failed to send Telegram message")

    except ImportError as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Telegram module not available: {exc}",
        ) from exc


@router.post("/send-commodity")
async def send_commodity(
    payload: CommodityPayload,
    user: dict = Depends(get_current_user),
):
    """Send a commodity alert to Telegram."""
    _ensure_scripts_path()
    try:
        import telegram_bot
        from telegram_bot import format_commodity_message, send_telegram_message

        subs = _read_subscribers()
        if subs:
            telegram_bot.TELEGRAM_CHAT_ID = subs

        msg = format_commodity_message(payload.data)
        success = send_telegram_message(msg)

        if success:
            return {"message": f"{payload.commodity_name} alert sent"}
        raise HTTPException(status_code=500, detail="Failed to send message")

    except ImportError as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Telegram module not available: {exc}",
        ) from exc


@router.get("/subscribers")
async def get_subscribers(user: dict = Depends(get_current_user)):
    """Return the current subscriber chat IDs."""
    return {"chat_ids": _read_subscribers()}


@router.put("/subscribers")
async def update_subscribers(
    body: SubscriberUpdate,
    user: dict = Depends(get_current_user),
):
    """Update the subscriber list."""
    if user.get("role") not in ("admin", "user"):
        raise HTTPException(status_code=403, detail="Guests cannot manage subscribers")

    try:
        _SUBS_FILE.write_text(body.chat_ids.strip(), encoding="utf-8")
        count = len([s for s in body.chat_ids.split(",") if s.strip()])
        return {"message": f"Saved {count} subscriber(s)", "chat_ids": body.chat_ids}
    except OSError as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Could not save subscriber file: {exc}",
        ) from exc


def _read_subscribers() -> str:
    """Read the subscriber file or return the default."""
    try:
        if _SUBS_FILE.exists():
            return _SUBS_FILE.read_text(encoding="utf-8").strip()
    except OSError:
        pass
    return "677141544,-1003933571318"
