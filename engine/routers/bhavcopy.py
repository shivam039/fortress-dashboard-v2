"""
engine/routers/bhavcopy.py
============================
FastAPI router for NSE Bhav Copy and the OHLCV/scan data-source toggle.

Endpoints:
  GET  /api/bhavcopy/status          today's fetch status + how much history is stored
  POST /api/bhavcopy/refresh         trigger a background fetch of today's Bhav Copy
  POST /api/bhavcopy/backfill        one-off historical catch-up (NOT part of the daily schedule)
  GET  /api/settings/data-provider   read the active OHLCV/scan data source
  POST /api/settings/data-provider   set it ("bhavcopy" | "indstocks")

The data-provider setting only affects OHLCV/scan data (see
utils.market_data_provider.get_ohlcv_provider_preference) — live price
(get_ltp) always goes INDstocks -> yfinance regardless, since Bhav Copy is
an end-of-day file with no intraday price to serve.
"""

import logging

from fastapi import APIRouter, BackgroundTasks, HTTPException
from pydantic import BaseModel

logger = logging.getLogger("fortress.routers.bhavcopy")
router = APIRouter(tags=["bhavcopy"])

_VALID_PROVIDERS = {"bhavcopy", "indstocks"}
_SETTING_KEY = "ohlcv_provider_preference"

# In-process guard against firing two overlapping backfills (e.g. a
# double-click, or a retry while the first attempt is still running). Not
# meant to survive a process restart — if the service restarts mid-backfill,
# bhavcopy_fetch_log's per-day dedup is what makes re-triggering safe, this
# flag just avoids two backfills hammering NSE concurrently in the common case.
_backfill_state: dict = {"in_progress": False, "started_at": None}


class RefreshRequest(BaseModel):
    force: bool = False


class BackfillRequest(BaseModel):
    days: int = 300


class DataProviderRequest(BaseModel):
    provider: str


@router.get("/api/bhavcopy/status")
def bhavcopy_refresh_status():
    """Return today's (IST) fetch attempt status, whether a backfill is
    currently running, and a coverage summary of what's actually stored in
    bhavcopy_eod (trading days covered, symbol count, earliest/latest date)
    — the practical way to watch backfill progress without polling NSE or
    the fetch log day-by-day."""
    from datetime import datetime

    import pytz

    from utils.db import get_bhavcopy_coverage_summary, get_bhavcopy_fetch_status

    today = datetime.now(pytz.timezone("Asia/Kolkata")).date().isoformat()
    status = get_bhavcopy_fetch_status(today)
    coverage = get_bhavcopy_coverage_summary()
    return {
        "trade_date": today,
        "status": status or "never_attempted",
        "backfill_in_progress": _backfill_state["in_progress"],
        "backfill_started_at": _backfill_state["started_at"],
        **coverage,
    }


@router.post("/api/bhavcopy/refresh", status_code=202)
async def refresh_bhavcopy_data(req: RefreshRequest, background_tasks: BackgroundTasks):
    """Trigger a background Bhav Copy fetch for today (IST).

    Stays `async def` — the body only schedules a background task and
    returns immediately, matching the /api/reit-invits/refresh convention.
    force=True bypasses the "already fetched today" dedup check.
    """
    from bhavcopy.jobs import run_bhavcopy_refresh_job

    def _run():
        result = run_bhavcopy_refresh_job(force=req.force)
        logger.info("Bhav Copy refresh job finished: %s", result)

    background_tasks.add_task(_run)
    return {"status": "accepted", "message": "Bhav Copy refresh started in background"}


@router.post("/api/bhavcopy/backfill", status_code=202)
async def backfill_bhavcopy_data(req: BackfillRequest, background_tasks: BackgroundTasks):
    """Trigger the one-off historical Bhav Copy backfill.

    This is the slow historical catch-up (walks backward up to `req.days`
    calendar days, ~1.5s between requests, skipping weekends) — it is NOT
    part of the daily schedule (see /api/bhavcopy/refresh and
    .github/workflows/bhavcopy-refresh.yml for that). Run it once when Bhav
    Copy is first activated, or again to fill a known gap.

    Safe to re-run or retry: bhavcopy_fetch_log's per-day dedup means an
    already-fetched day is skipped rather than re-downloaded, so an
    interrupted backfill (e.g. a deploy restart) just picks up where it
    left off on the next call.
    """
    if _backfill_state["in_progress"]:
        raise HTTPException(
            status_code=409,
            detail=(
                "A Bhav Copy backfill is already running. Check GET "
                "/api/bhavcopy/status for progress instead of starting another."
            ),
        )
    if not (1 <= req.days <= 3650):
        raise HTTPException(status_code=400, detail="days must be between 1 and 3650")

    from datetime import datetime, timezone

    from bhavcopy.jobs import backfill_bhavcopy

    def _run():
        _backfill_state["in_progress"] = True
        _backfill_state["started_at"] = datetime.now(timezone.utc).isoformat()
        try:
            result = backfill_bhavcopy(days=req.days)
            logger.info(
                "Bhav Copy backfill finished: %d fetched, %d no-data days, %d errors",
                len(result["done"]),
                len(result["skipped_no_data"]),
                len(result["errors"]),
            )
        except Exception:
            logger.exception("Bhav Copy backfill crashed")
        finally:
            _backfill_state["in_progress"] = False

    background_tasks.add_task(_run)
    return {
        "status": "accepted",
        "message": (
            f"Bhav Copy backfill started in background ({req.days} calendar days, "
            "weekends skipped without a network call). This can take a while — "
            "check progress via GET /api/bhavcopy/status."
        ),
    }


@router.get("/api/settings/data-provider")
def get_data_provider_setting():
    """Return the active OHLCV/scan data source preference."""
    from utils.market_data_provider import get_ohlcv_provider_preference

    provider = get_ohlcv_provider_preference()
    return {"provider": provider}


@router.post("/api/settings/data-provider")
def set_data_provider_setting(req: DataProviderRequest):
    """Set the OHLCV/scan data source preference ("bhavcopy" | "indstocks").

    Only affects get_ohlcv()/get_batch_ohlcv() — see the module docstring.
    """
    provider = req.provider.strip().lower()
    if provider not in _VALID_PROVIDERS:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid provider '{req.provider}'. Valid options: {sorted(_VALID_PROVIDERS)}",
        )

    from utils.db import set_setting
    from utils.market_data_provider import invalidate_ohlcv_provider_preference_cache

    set_setting(_SETTING_KEY, provider)
    invalidate_ohlcv_provider_preference_cache()
    logger.info("OHLCV/scan data provider preference set to '%s'", provider)
    return {"status": "ok", "provider": provider}
