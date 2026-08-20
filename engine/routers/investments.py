"""
engine/routers/investments.py
==============================
Shared watchlist, portfolio, and refresh-status endpoints.

All endpoints require JWT authentication.

Endpoints:
  GET    /api/investments/watchlist
  POST   /api/investments/watchlist
  DELETE /api/investments/watchlist/{symbol}
  GET    /api/investments/portfolio
  POST   /api/investments/portfolio
  DELETE /api/investments/portfolio/{symbol}
  GET    /api/investments/refresh-status
"""

import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel

from auth_utils import get_current_username

logger = logging.getLogger("fortress.routers.investments")
router = APIRouter(prefix="/api/investments", tags=["investments"])


# ── Request models ────────────────────────────────────────────────────────────

class WatchlistAddRequest(BaseModel):
    symbol: str
    asset_class: str
    name: Optional[str] = None
    notes: Optional[str] = None


class PortfolioUpsertRequest(BaseModel):
    symbol: str
    asset_class: str
    name: Optional[str] = None
    quantity: float = 0.0
    avg_price: float = 0.0
    currency: str = "INR"
    allocation_pct: Optional[float] = None
    notes: Optional[str] = None


# ── Watchlist ─────────────────────────────────────────────────────────────────

@router.get("/watchlist", response_model=List[Dict[str, Any]])
async def get_watchlist(username: str = Depends(get_current_username)):
    """Return the authenticated user's watchlist."""
    try:
        from utils.db import get_watchlist
        return get_watchlist(username)
    except Exception as exc:
        logger.error("get_watchlist failed: %s", exc)
        raise HTTPException(status_code=500, detail="Failed to retrieve watchlist")


@router.post("/watchlist", status_code=201)
async def add_to_watchlist(
    req: WatchlistAddRequest,
    username: str = Depends(get_current_username),
):
    """Add an instrument to the user's watchlist."""
    try:
        from utils.db import add_to_watchlist
        add_to_watchlist(
            username=username,
            symbol=req.symbol.upper(),
            asset_class=req.asset_class,
            name=req.name,
            notes=req.notes,
        )
        return {"status": "added", "symbol": req.symbol.upper()}
    except Exception as exc:
        logger.error("add_to_watchlist failed: %s", exc)
        raise HTTPException(status_code=500, detail="Failed to add to watchlist")


@router.delete("/watchlist/{symbol}", status_code=200)
async def remove_from_watchlist(
    symbol: str,
    username: str = Depends(get_current_username),
):
    """Remove an instrument from the user's watchlist."""
    try:
        from utils.db import remove_from_watchlist
        removed = remove_from_watchlist(username=username, symbol=symbol.upper())
        if not removed:
            raise HTTPException(status_code=404, detail="Symbol not in watchlist")
        return {"status": "removed", "symbol": symbol.upper()}
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("remove_from_watchlist failed: %s", exc)
        raise HTTPException(status_code=500, detail="Failed to remove from watchlist")


# ── Portfolio ─────────────────────────────────────────────────────────────────

@router.get("/portfolio", response_model=List[Dict[str, Any]])
async def get_portfolio(username: str = Depends(get_current_username)):
    """Return the authenticated user's portfolio holdings."""
    try:
        from utils.db import get_portfolio
        return get_portfolio(username)
    except Exception as exc:
        logger.error("get_portfolio failed: %s", exc)
        raise HTTPException(status_code=500, detail="Failed to retrieve portfolio")


@router.post("/portfolio", status_code=201)
async def upsert_portfolio_holding(
    req: PortfolioUpsertRequest,
    username: str = Depends(get_current_username),
):
    """Add or update a portfolio holding."""
    try:
        from utils.db import upsert_portfolio_holding
        upsert_portfolio_holding(
            username=username,
            symbol=req.symbol.upper(),
            asset_class=req.asset_class,
            name=req.name,
            quantity=req.quantity,
            avg_price=req.avg_price,
            currency=req.currency,
            allocation_pct=req.allocation_pct,
            notes=req.notes,
        )
        return {"status": "saved", "symbol": req.symbol.upper()}
    except Exception as exc:
        logger.error("upsert_portfolio_holding failed: %s", exc)
        raise HTTPException(status_code=500, detail="Failed to save portfolio holding")


@router.delete("/portfolio/{symbol}", status_code=200)
async def remove_portfolio_holding(
    symbol: str,
    username: str = Depends(get_current_username),
):
    """Remove a holding from the user's portfolio."""
    try:
        from utils.db import remove_portfolio_holding
        removed = remove_portfolio_holding(username=username, symbol=symbol.upper())
        if not removed:
            raise HTTPException(status_code=404, detail="Symbol not in portfolio")
        return {"status": "removed", "symbol": symbol.upper()}
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("remove_portfolio_holding failed: %s", exc)
        raise HTTPException(status_code=500, detail="Failed to remove from portfolio")


# ── Refresh status ────────────────────────────────────────────────────────────

@router.get("/refresh-status")
async def get_refresh_status(job_type: Optional[str] = Query(None)):
    """Return last refresh job(s) status."""
    try:
        from utils.db import get_last_refresh_job, get_all_refresh_jobs
        if job_type:
            return get_last_refresh_job(job_type) or {"status": "never_run", "job_type": job_type}
        return get_all_refresh_jobs()
    except Exception as exc:
        logger.error("refresh_status failed: %s", exc)
        return {"status": "unavailable", "error": str(exc)}
