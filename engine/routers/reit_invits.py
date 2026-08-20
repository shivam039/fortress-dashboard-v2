"""
engine/routers/reit_invits.py
==============================
FastAPI router for REITs & InvITs module.

Endpoints:
  GET  /api/reit-invits              list all instruments
  GET  /api/reit-invits/{symbol}     single instrument detail
  POST /api/reit-invits/refresh      trigger background refresh
  GET  /api/reit-invits/status       last refresh job status
"""

import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, BackgroundTasks, HTTPException, Query
from pydantic import BaseModel

logger = logging.getLogger("fortress.routers.reit_invits")
router = APIRouter(prefix="/api/reit-invits", tags=["reit-invits"])

_cached_frame: Optional[List[Dict[str, Any]]] = None
_cache_ts: Optional[str] = None


class RefreshRequest(BaseModel):
    force: bool = False


def _get_or_fetch_frame() -> List[Dict[str, Any]]:
    global _cached_frame, _cache_ts
    from datetime import datetime, timezone

    if _cached_frame and _cache_ts:
        from datetime import datetime as _dt
        try:
            age_h = (datetime.now(timezone.utc) - _dt.fromisoformat(_cache_ts)).total_seconds() / 3600
            if age_h < 4:
                return _cached_frame
        except Exception:
            pass

    from reit_invits.logic import build_reit_frame
    _cached_frame = build_reit_frame()
    _cache_ts = datetime.now(timezone.utc).isoformat()
    return _cached_frame


@router.get("", response_model=List[Dict[str, Any]])
async def list_reit_invits(
    type_filter: Optional[str] = Query(None, alias="type"),
    sort_by: str = Query("conviction_score", description="Field to sort by"),
    desc: bool = Query(True),
):
    """Return all REITs and InvITs with conviction scores."""
    try:
        frame = _get_or_fetch_frame()
    except Exception as exc:
        logger.error("REIT list failed: %s", exc)
        raise HTTPException(status_code=500, detail="Failed to fetch REIT/InvIT data")

    if type_filter:
        frame = [r for r in frame if r.get("asset_class", "").upper() == type_filter.upper()]

    # Sort safely — None values go last
    def _sort_key(r: Dict) -> float:
        v = r.get(sort_by)
        if v is None:
            return -float("inf") if desc else float("inf")
        try:
            return float(v)
        except (TypeError, ValueError):
            return 0.0

    frame.sort(key=_sort_key, reverse=desc)
    return frame


@router.get("/status")
async def reit_refresh_status():
    """Return the last refresh job status."""
    try:
        from utils.db import get_last_refresh_job
        job = get_last_refresh_job("reit_invits")
        return job or {"status": "never_run", "job_type": "reit_invits"}
    except Exception:
        return {"status": "unknown", "job_type": "reit_invits"}


@router.get("/{symbol}")
async def get_reit_detail(symbol: str):
    """Return detailed metrics for a single REIT/InvIT."""
    from reit_invits.logic import get_reit_detail
    result = get_reit_detail(symbol.upper())
    if result is None:
        raise HTTPException(status_code=404, detail=f"Symbol '{symbol}' not found in REIT/InvIT universe")
    return result


@router.post("/refresh", status_code=202)
async def refresh_reit_data(req: RefreshRequest, background_tasks: BackgroundTasks):
    """Trigger a background refresh of all REIT/InvIT data."""
    global _cached_frame, _cache_ts

    if req.force:
        _cached_frame = None
        _cache_ts = None

    from reit_invits.jobs import run_reit_refresh_job

    def _refresh_and_update():
        global _cached_frame, _cache_ts
        from datetime import datetime, timezone
        run_reit_refresh_job()
        from reit_invits.logic import build_reit_frame
        _cached_frame = build_reit_frame()
        _cache_ts = datetime.now(timezone.utc).isoformat()
        logger.info("REIT in-memory cache refreshed (%d instruments)", len(_cached_frame))

    background_tasks.add_task(_refresh_and_update)
    return {"status": "accepted", "message": "REIT/InvIT refresh started in background"}
