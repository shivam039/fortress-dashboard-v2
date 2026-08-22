"""
engine/routers/bhavcopy.py
============================
FastAPI router for NSE Bhav Copy and the OHLCV/scan data-source toggle.

Endpoints:
  GET  /api/bhavcopy/status          last refresh job status
  POST /api/bhavcopy/refresh         trigger a background Bhav Copy fetch
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


class RefreshRequest(BaseModel):
    force: bool = False


class DataProviderRequest(BaseModel):
    provider: str


@router.get("/api/bhavcopy/status")
def bhavcopy_refresh_status():
    """Return the most recent Bhav Copy fetch attempt for today's (IST)
    trading date, plus the last refresh_jobs entry for context."""
    from datetime import datetime

    import pytz

    from utils.db import get_bhavcopy_fetch_status

    today = datetime.now(pytz.timezone("Asia/Kolkata")).date().isoformat()
    status = get_bhavcopy_fetch_status(today)
    return {
        "trade_date": today,
        "status": status or "never_attempted",
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
