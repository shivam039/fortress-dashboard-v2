"""
engine/routers/us_investing.py
===============================
FastAPI router for US Investing module.

Endpoints:
  GET  /api/us-investing             list all instruments
  GET  /api/us-investing/search      search by symbol/name
  GET  /api/us-investing/status      last refresh job status
  GET  /api/us-investing/{symbol}    single instrument detail
  POST /api/us-investing/refresh     trigger background refresh
"""

import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, BackgroundTasks, HTTPException, Query
from pydantic import BaseModel

logger = logging.getLogger("fortress.routers.us_investing")
router = APIRouter(prefix="/api/us-investing", tags=["us-investing"])

_cached_frame: Optional[List[Dict[str, Any]]] = None
_cache_ts: Optional[str] = None


class RefreshRequest(BaseModel):
    force: bool = False
    include_inr: bool = True


def _get_or_fetch_frame(include_inr: bool = True) -> List[Dict[str, Any]]:
    global _cached_frame, _cache_ts
    from datetime import datetime, timezone

    if _cached_frame and _cache_ts:
        try:
            age_h = (datetime.now(timezone.utc) - datetime.fromisoformat(_cache_ts)).total_seconds() / 3600
            if age_h < 4:
                return _cached_frame
        except Exception:
            pass

    from us_investing.logic import build_us_frame
    _cached_frame = build_us_frame(include_inr=include_inr)
    _cache_ts = datetime.now(timezone.utc).isoformat()
    return _cached_frame


@router.get("", response_model=List[Dict[str, Any]])
async def list_us_instruments(
    asset_type: Optional[str] = Query(None, description="stock | etf"),
    sector: Optional[str] = Query(None),
    include_inr: bool = Query(True),
    sort_by: str = Query("conviction_score"),
    desc: bool = Query(True),
):
    """Return all US stocks and ETFs with conviction scores."""
    try:
        frame = _get_or_fetch_frame(include_inr=include_inr)
    except Exception as exc:
        logger.error("US list failed: %s", exc)
        raise HTTPException(status_code=500, detail="Failed to fetch US Investing data")

    if asset_type:
        target_class = "US_ETF" if asset_type.lower() == "etf" else "US_STOCK"
        frame = [r for r in frame if r.get("asset_class") == target_class]

    if sector:
        frame = [r for r in frame if sector.lower() in (r.get("sector") or "").lower()]

    def _key(r: Dict) -> float:
        v = r.get(sort_by)
        if v is None:
            return -float("inf") if desc else float("inf")
        try:
            return float(v)
        except (TypeError, ValueError):
            return 0.0

    frame.sort(key=_key, reverse=desc)
    return frame


@router.get("/search")
async def search_us(q: str = Query(..., min_length=1)):
    """Quick symbol/name search (static metadata, no price fetch)."""
    from us_investing.logic import search_us_universe
    return search_us_universe(q)


@router.get("/status")
async def us_refresh_status():
    """Return last refresh job status."""
    try:
        from utils.db import get_last_refresh_job
        job = get_last_refresh_job("us_investing")
        return job or {"status": "never_run", "job_type": "us_investing"}
    except Exception:
        return {"status": "unknown", "job_type": "us_investing"}


@router.get("/{symbol}")
async def get_us_detail(symbol: str, include_inr: bool = Query(True)):
    """Return detailed metrics for a single US stock or ETF."""
    from us_investing.logic import get_us_detail
    result = get_us_detail(symbol.upper(), include_inr=include_inr)
    if result is None:
        raise HTTPException(status_code=404, detail=f"Symbol '{symbol}' not found in US universe")
    return result


@router.post("/refresh", status_code=202)
async def refresh_us_data(req: RefreshRequest, background_tasks: BackgroundTasks):
    """Trigger a background refresh of all US instrument data."""
    global _cached_frame, _cache_ts

    if req.force:
        _cached_frame = None
        _cache_ts = None

    from us_investing.jobs import run_us_refresh_job

    def _refresh_and_update():
        global _cached_frame, _cache_ts
        from datetime import datetime, timezone
        run_us_refresh_job(include_inr=req.include_inr)
        from us_investing.logic import build_us_frame
        _cached_frame = build_us_frame(include_inr=req.include_inr)
        _cache_ts = datetime.now(timezone.utc).isoformat()
        logger.info("US in-memory cache refreshed (%d instruments)", len(_cached_frame))

    background_tasks.add_task(_refresh_and_update)
    return {"status": "accepted", "message": "US Investing refresh started in background"}
