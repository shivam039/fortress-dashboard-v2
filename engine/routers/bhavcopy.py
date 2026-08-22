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
_backfill_state: dict = {
    "in_progress": False,
    "started_at": None,
    "days_processed": 0,
    "target_days": 0,
}


class RefreshRequest(BaseModel):
    force: bool = False


class BackfillRequest(BaseModel):
    days: int = 300
    max_fetches: int = 30


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
    from utils.market_data_provider import get_ohlcv_source_call_counts

    today = datetime.now(pytz.timezone("Asia/Kolkata")).date().isoformat()
    status = get_bhavcopy_fetch_status(today)
    coverage = get_bhavcopy_coverage_summary()
    return {
        "trade_date": today,
        "status": status or "never_attempted",
        "backfill_in_progress": _backfill_state["in_progress"],
        "backfill_started_at": _backfill_state["started_at"],
        "backfill_days_processed": _backfill_state.get("days_processed", 0),
        "backfill_target_days": _backfill_state.get("target_days", 0),
        # Cumulative, since process start or the last POST
        # /api/bhavcopy/reset-stats — what actually served OHLCV calls,
        # independent of the ohlcv_provider_preference *setting* (which
        # /api/market-data-status's ohlcv_source reflects). If bhavcopy
        # stays at 0 here while your preference is "bhavcopy", Bhav Copy
        # has no data yet for anything you've scanned (e.g. the backfill
        # hasn't reached those symbols/dates) and everything is silently
        # falling back.
        "ohlcv_calls_by_source": get_ohlcv_source_call_counts(),
        **coverage,
    }


@router.post("/api/bhavcopy/reset-stats")
def reset_bhavcopy_stats():
    """Zero the ohlcv_calls_by_source counters — call this right before a
    scan so the counts GET /api/bhavcopy/status shows afterward reflect
    just that scan instead of everything since the process started."""
    from utils.market_data_provider import reset_ohlcv_source_call_counts

    reset_ohlcv_source_call_counts()
    return {"status": "ok"}


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
    left off on the next call — this is also how `req.max_fetches` chunking
    (below) is meant to be driven: call this endpoint repeatedly (see
    .github/workflows/bhavcopy-backfill.yml, which now loops automatically)
    rather than once with an unbounded `days`.

    `req.max_fetches` caps how many actual NSE network requests a single
    call makes (already-fetched days are skipped near-instantly and don't
    count against this) — added after a full 300-day backfill in one
    BackgroundTask was found to reliably outlive a Render deploy and get
    silently killed mid-run, well before reaching its target. `0` means no
    cap (run the full `days` range in one call) — fine for a short range or
    a host that won't redeploy mid-run, but not the default for that reason.
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
    if not (0 <= req.max_fetches <= 300):
        raise HTTPException(status_code=400, detail="max_fetches must be between 0 and 300 (0 = no cap)")

    from datetime import datetime, timezone

    from bhavcopy.jobs import backfill_bhavcopy

    def _run():
        _backfill_state["in_progress"] = True
        _backfill_state["started_at"] = datetime.now(timezone.utc).isoformat()
        _backfill_state["days_processed"] = 0
        _backfill_state["target_days"] = req.days

        def _on_progress(processed: int, total: int):
            _backfill_state["days_processed"] = processed
            _backfill_state["target_days"] = total

        try:
            result = backfill_bhavcopy(
                days=req.days,
                max_fetches=req.max_fetches,
                progress_cb=_on_progress,
            )
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
