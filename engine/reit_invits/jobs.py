"""
reit_invits/jobs.py
===================
Background refresh job for REIT/InvIT data.
Records job status to the refresh_jobs table.
"""

import logging

logger = logging.getLogger("fortress.reit_invits.jobs")


def run_reit_refresh_job() -> dict:
    """
    Fetch all REIT/InvIT symbols, cache results, and update refresh_jobs table.
    Returns a summary dict.
    """
    from reit_invits.logic import build_reit_frame

    job_id = None
    try:
        from utils.db import record_refresh_job_done, record_refresh_job_start

        job_id = record_refresh_job_start("reit_invits", source="yfinance")
    except Exception:
        pass

    try:
        logger.info("Starting REIT/InvIT refresh job...")
        records = build_reit_frame()
        count = len([r for r in records if r.get("price")])
        logger.info("REIT/InvIT refresh done: %d instruments with data", count)

        try:
            from utils.db import record_refresh_job_done, upsert_reit_cache
            upsert_reit_cache(records)
            if job_id:
                record_refresh_job_done(job_id, status="done", records_refreshed=count)
        except Exception as exc:
            logger.debug("Cache upsert skipped: %s", exc)

        return {"status": "done", "records_refreshed": count}

    except Exception as exc:
        logger.error("REIT/InvIT refresh failed: %s", exc)
        try:
            from utils.db import record_refresh_job_done
            if job_id:
                record_refresh_job_done(job_id, status="error", error_detail=str(exc))
        except Exception:
            pass
        return {"status": "error", "error": str(exc)}
