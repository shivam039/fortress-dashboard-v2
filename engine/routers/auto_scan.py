"""
engine/routers/auto_scan.py
============================
FORTRESS-E3 — the HTTP surface a scheduled job (GitHub Actions cron, same
shape as .github/workflows/bhavcopy-refresh.yml) uses to trigger the daily
automated multi-universe scan -> E1 -> T1 -> E2 -> maturation pipeline
without any manual browser action.

Endpoints:
  POST /api/auto-scan/run           trigger today's run in the background
  GET  /api/auto-scan/status        latest run's summary (never fabricated)
  GET  /api/auto-scan/runs/{run_id} one specific run's full audit record
"""
import logging
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, HTTPException
from pydantic import BaseModel

logger = logging.getLogger("fortress.routers.auto_scan")
router = APIRouter(prefix="/api/auto-scan", tags=["auto-scan"])


class AutoScanRunRequest(BaseModel):
    trading_date: Optional[str] = None


@router.post("/run", status_code=202)
async def trigger_auto_scan(req: AutoScanRunRequest, background_tasks: BackgroundTasks):
    """Fire-and-forget, matching the /api/bhavcopy/refresh convention (a
    full multi-universe scan is long-running work — see engine/CLAUDE.md's
    'never block a request > 5s' rule). Returns the run_id immediately so
    the caller (a cron workflow, or a manual retry) can poll
    GET /api/auto-scan/runs/{run_id} for status."""
    import uuid

    from research.auto_scan import run_daily_auto_scan

    run_id = str(uuid.uuid4())

    def _run():
        try:
            result = run_daily_auto_scan(trading_date=req.trading_date, run_id=run_id)
            logger.info("auto-scan run %s finished: %s", run_id, result)
        except Exception as e:
            logger.error("auto-scan run %s failed: %s", run_id, e)

    background_tasks.add_task(_run)
    return {"status": "accepted", "run_id": run_id, "message": "Automated multi-universe scan started in background"}


@router.get("/status")
def auto_scan_status():
    """Most recent run's compact summary — never fabricates a metric the DB
    doesn't have; returns null fields if no run has ever completed."""
    from utils.db import fetch_latest_auto_scan_run

    latest = fetch_latest_auto_scan_run()
    if latest is None:
        return {"status": "NO_RUNS_YET"}
    return latest


@router.get("/runs/{run_id}")
def get_auto_scan_run(run_id: str):
    from utils.db import fetch_auto_scan_run

    run = fetch_auto_scan_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")
    return run


@router.get("/health")
def auto_scan_health(trading_date: Optional[str] = None):
    """FORTRESS-O1: operational monitoring only — detects FAILED/DEGRADED/
    missing/stale runs. Read-only (no scan, no evidence write). A watchdog
    workflow polls this to decide whether to alert; it never fabricates a
    status. Config booleans only — no secret values."""
    from research.auto_scan import check_pipeline_health, check_production_config

    return {
        "pipeline": check_pipeline_health(trading_date=trading_date),
        "production_config": check_production_config(),
    }
