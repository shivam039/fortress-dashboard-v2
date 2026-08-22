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
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, BackgroundTasks, HTTPException, Query
from pydantic import BaseModel

logger = logging.getLogger("fortress.routers.reit_invits")
router = APIRouter(prefix="/api/reit-invits", tags=["reit-invits"])

# In-process fast path: avoids a DB round trip on every request within the
# same server process. The DB-backed cache (utils.db.fetch_reit_cache /
# upsert_reit_cache) is the real persistence layer — it's what survives a
# dev-server restart, which this in-memory dict never did on its own.
_cached_frame: Optional[List[Dict[str, Any]]] = None
_cache_ts: Optional[str] = None

# How stale the cache is allowed to be before a fresh live fetch is forced.
_CACHE_MAX_AGE_HOURS = 4


class RefreshRequest(BaseModel):
    force: bool = False


def _get_or_fetch_frame() -> List[Dict[str, Any]]:
    global _cached_frame, _cache_ts

    if _cached_frame and _cache_ts:
        try:
            age_h = (datetime.now(timezone.utc) - datetime.fromisoformat(_cache_ts)).total_seconds() / 3600
            if age_h < _CACHE_MAX_AGE_HOURS:
                return _cached_frame
        except Exception:
            pass

    # Second tier: the DB-backed cache. This is what makes the REIT/InvIT
    # tab load instantly after a dev-server restart instead of re-running
    # the full live yfinance fetch for every symbol on the very next
    # request — previously `upsert_reit_cache` was a no-op placeholder, so
    # this tier didn't exist at all and every restart meant a full live
    # fetch on the next visit.
    from reit_invits.universe import REIT_INVIT_UNIVERSE
    from utils.db import fetch_reit_cache

    try:
        cached_records = fetch_reit_cache(max_age_hours=_CACHE_MAX_AGE_HOURS)
    except Exception as exc:
        logger.warning("reit_cache read failed, falling back to live fetch: %s", exc)
        cached_records = []

    if cached_records and len(cached_records) >= len(REIT_INVIT_UNIVERSE):
        _cached_frame = cached_records
        _cache_ts = datetime.now(timezone.utc).isoformat()
        return _cached_frame

    # Third tier: live fetch, then persist for next time.
    from reit_invits.logic import build_reit_frame
    from utils.db import upsert_reit_cache

    _cached_frame = build_reit_frame()
    _cache_ts = datetime.now(timezone.utc).isoformat()
    try:
        upsert_reit_cache(_cached_frame)
    except Exception as exc:
        logger.warning("reit_cache write failed (non-fatal): %s", exc)
    return _cached_frame


@router.get("", response_model=List[Dict[str, Any]])
def list_reit_invits(
    type_filter: Optional[str] = Query(None, alias="type"),
    sort_by: str = Query("conviction_score", description="Field to sort by"),
    desc: bool = Query(True),
):
    """Return all REITs and InvITs with conviction scores.

    Declared as a plain `def`, not `async def`: this ends up doing
    synchronous, potentially slow work (a live yfinance fetch across the
    whole universe on a cache miss). An `async def` route with no real
    `await` inside runs directly on uvicorn's single event loop and freezes
    request handling for the *entire app*, not just this endpoint, for as
    long as it takes — which is the same bug pattern already fixed for the
    stock scanner, sector pulse, and MF analysis routes. A plain `def`
    route lets FastAPI dispatch it to a worker thread instead.
    """
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
def reit_refresh_status():
    """Return the last refresh job status."""
    try:
        from utils.db import get_last_refresh_job
        job = get_last_refresh_job("reit_invits")
        return job or {"status": "never_run", "job_type": "reit_invits"}
    except Exception:
        return {"status": "unknown", "job_type": "reit_invits"}


@router.get("/{symbol}")
def get_reit_detail(symbol: str):
    """Return detailed metrics for a single REIT/InvIT."""
    from reit_invits.logic import get_reit_detail
    result = get_reit_detail(symbol.upper())
    if result is None:
        raise HTTPException(status_code=404, detail=f"Symbol '{symbol}' not found in REIT/InvIT universe")
    return result


@router.post("/refresh", status_code=202)
async def refresh_reit_data(req: RefreshRequest, background_tasks: BackgroundTasks):
    """Trigger a background refresh of all REIT/InvIT data.

    This route itself stays `async def` — its body only schedules a
    background task and returns immediately, no blocking work runs inline.
    """
    global _cached_frame, _cache_ts

    if req.force:
        _cached_frame = None
        _cache_ts = None

    from reit_invits.jobs import run_reit_refresh_job

    def _refresh_and_update():
        global _cached_frame, _cache_ts
        from utils.db import fetch_reit_cache

        # run_reit_refresh_job() already does a live build_reit_frame() call
        # plus upsert_reit_cache() and refresh-job bookkeeping — fetching
        # live again here would just double the yfinance load and the wait
        # for every manual refresh. Read the freshly-written cache back
        # instead of re-fetching.
        run_reit_refresh_job()
        _cached_frame = fetch_reit_cache(max_age_hours=_CACHE_MAX_AGE_HOURS) or _cached_frame
        _cache_ts = datetime.now(timezone.utc).isoformat()
        logger.info("REIT cache refreshed (%d instruments)", len(_cached_frame or []))

    background_tasks.add_task(_refresh_and_update)
    return {"status": "accepted", "message": "REIT/InvIT refresh started in background"}
