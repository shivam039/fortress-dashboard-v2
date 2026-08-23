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

# In-process TTL. Below this fraction of a freshly-fetched frame having a
# usable price, the fetch is treated as degraded (provider outage, rate
# limit) and NOT written to the DB cache — same reasoning as
# reit_invits' _is_degraded_frame/_DEGRADED_FRAME_THRESHOLD (see
# routers/reit_invits.py): a degraded fetch answers the request that
# triggered it, but persisting it would overwrite a still-good previous
# snapshot with blanks for every viewer until the next TTL expiry.
_CACHE_MAX_AGE_HOURS = 4
_DEGRADED_FRAME_THRESHOLD = 0.3


class RefreshRequest(BaseModel):
    force: bool = False
    include_inr: bool = True


def _is_degraded_frame(frame: List[Dict[str, Any]]) -> bool:
    if not frame:
        return True
    bad = sum(1 for r in frame if r.get("price") is None)
    return (bad / len(frame)) > _DEGRADED_FRAME_THRESHOLD


def _get_or_fetch_frame(include_inr: bool = True) -> List[Dict[str, Any]]:
    """Three-tier cache, same shape as reit_invits' _get_or_fetch_frame
    (routers/reit_invits.py): in-process dict (fastest, doesn't survive a
    restart) -> DB cache (utils.db.fetch_us_cache/upsert_us_cache, survives
    a restart) -> live fetch. Previously this was a single in-process tier
    only with no DB persistence at all (upsert_us_cache was a no-op
    placeholder) — every process restart meant the next request paid the
    full live-fetch cost across all 31 symbols with nothing served in the
    meantime. See US_INVESTING_SCORING.md §6.
    """
    global _cached_frame, _cache_ts
    from datetime import datetime, timezone

    if _cached_frame and _cache_ts:
        try:
            age_h = (datetime.now(timezone.utc) - datetime.fromisoformat(_cache_ts)).total_seconds() / 3600
            if age_h < _CACHE_MAX_AGE_HOURS:
                return _cached_frame
        except Exception:
            pass

    from us_investing.universe import FULL_UNIVERSE
    from utils.db import fetch_us_cache

    try:
        cached_records = fetch_us_cache(max_age_hours=_CACHE_MAX_AGE_HOURS)
    except Exception as exc:
        logger.warning("us_investing_cache read failed, falling back to live fetch: %s", exc)
        cached_records = []

    if cached_records and len(cached_records) >= len(FULL_UNIVERSE):
        _cached_frame = cached_records
        _cache_ts = datetime.now(timezone.utc).isoformat()
        return _cached_frame

    from us_investing.logic import build_us_frame
    from utils.db import upsert_us_cache

    fresh_frame = build_us_frame(include_inr=include_inr)
    _cached_frame = fresh_frame
    _cache_ts = datetime.now(timezone.utc).isoformat()

    if _is_degraded_frame(fresh_frame):
        logger.warning(
            "us_investing_cache: live fetch returned mostly priceless data — "
            "serving it but NOT writing it to the DB cache so a still-good "
            "previous snapshot (if any) survives instead of being "
            "overwritten with blanks"
        )
        return fresh_frame

    try:
        upsert_us_cache(fresh_frame)
    except Exception as exc:
        logger.warning("us_investing_cache write failed (non-fatal): %s", exc)
    return _cached_frame


@router.get("", response_model=List[Dict[str, Any]])
def list_us_instruments(
    asset_type: Optional[str] = Query(None, description="stock | etf"),
    sector: Optional[str] = Query(None),
    include_inr: bool = Query(True),
    sort_by: str = Query("conviction_score"),
    desc: bool = Query(True),
):
    """Return all US stocks and ETFs with conviction scores.

    Declared as a plain `def`, not `async def`: this does synchronous,
    potentially slow work on a cache miss (a live fetch across the whole
    universe). An `async def` route with no real `await` inside runs
    directly on uvicorn's single event loop and freezes request handling
    for the *entire app*, not just this endpoint — the same bug pattern
    already fixed for the stock scanner, sector pulse, MF analysis, and
    REIT/InvIT routes (this one was missed at the time). A plain `def`
    route lets FastAPI dispatch it to a worker thread instead.
    """
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
def get_us_detail(symbol: str, include_inr: bool = Query(True)):
    """Return detailed metrics for a single US stock or ETF — looked up
    from the same cached, full-universe-scored frame GET /api/us-investing
    serves, so this instrument's conviction score is ranked against its
    real peers.

    Previously this called us_investing.logic.get_us_detail() directly,
    which scores the one requested instrument against a "peer group"
    containing only itself — _pct_rank(value, [value]) is mathematically
    always 100%, so every single-symbol detail lookup returned a perfect
    score on every dimension regardless of the instrument's actual metrics
    (see US_INVESTING_SCORING.md §7). Declared as a plain `def` for the
    same reason as list_us_instruments above — a cache miss here does the
    same synchronous full-universe fetch.
    """
    from us_investing.universe import FULL_UNIVERSE

    symbol = symbol.upper()
    if symbol not in FULL_UNIVERSE:
        raise HTTPException(status_code=404, detail=f"Symbol '{symbol}' not found in US universe")

    try:
        frame = _get_or_fetch_frame(include_inr=include_inr)
    except Exception as exc:
        logger.error("US detail fetch failed: %s", exc)
        raise HTTPException(status_code=500, detail="Failed to fetch US Investing data")

    for r in frame:
        if r.get("symbol") == symbol:
            return r
    raise HTTPException(status_code=404, detail=f"Symbol '{symbol}' not found in the current US Investing scan")


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

        from utils.db import fetch_us_cache

        # run_us_refresh_job() already does a live build_us_frame() call
        # plus upsert_us_cache() and refresh-job bookkeeping — fetching
        # live again here would just double the provider load and the wait
        # for every manual refresh (this used to do exactly that). Read the
        # freshly-written DB cache back instead of re-fetching, same
        # pattern as routers/reit_invits.py's refresh flow.
        run_us_refresh_job(include_inr=req.include_inr)
        _cached_frame = fetch_us_cache(max_age_hours=_CACHE_MAX_AGE_HOURS) or _cached_frame
        _cache_ts = datetime.now(timezone.utc).isoformat()
        logger.info("US Investing cache refreshed (%d instruments)", len(_cached_frame or []))

    background_tasks.add_task(_refresh_and_update)
    return {"status": "accepted", "message": "US Investing refresh started in background"}
