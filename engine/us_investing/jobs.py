"""
us_investing/jobs.py
====================
Background refresh job for US Investing data.
"""

import logging

logger = logging.getLogger("fortress.us_investing.jobs")


def run_us_refresh_job(include_inr: bool = True) -> dict:
    """Fetch all US symbols, cache results, update refresh_jobs table."""
    from us_investing.logic import build_us_frame

    job_id = None
    try:
        from utils.db import record_refresh_job_start
        job_id = record_refresh_job_start("us_investing", source="yfinance")
    except Exception:
        pass

    try:
        logger.info("Starting US Investing refresh job...")
        records = build_us_frame(include_inr=include_inr)
        count = len([r for r in records if r.get("price")])
        logger.info("US Investing refresh done: %d instruments with data", count)

        try:
            from utils.db import record_refresh_job_done, upsert_us_cache
            upsert_us_cache(records)
            if job_id:
                record_refresh_job_done(job_id, status="done", records_refreshed=count)
        except Exception as exc:
            logger.debug("Cache upsert skipped: %s", exc)

        return {"status": "done", "records_refreshed": count}

    except Exception as exc:
        logger.error("US Investing refresh failed: %s", exc)
        try:
            from utils.db import record_refresh_job_done
            if job_id:
                record_refresh_job_done(job_id, status="error", error_detail=str(exc))
        except Exception:
            pass
        return {"status": "error", "error": str(exc)}
