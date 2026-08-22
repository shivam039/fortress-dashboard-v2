"""
engine/bhavcopy/jobs.py
=========================
Daily refresh job for NSE Bhav Copy, plus a one-off backfill helper.

run_bhavcopy_refresh_job() is what the scheduled GitHub Actions workflow
(.github/workflows/bhavcopy-refresh.yml) triggers via POST /api/bhavcopy/refresh
(see routers wiring in engine/main.py). It follows the same
"check the dedup log before touching the network" flow the plan calls for:
bhavcopy_fetch_log.status == "done" for today's IST trading date means this
call is a no-op.

backfill_bhavcopy() is a manual, one-off operation (run once when Bhav Copy
is first activated, or to fill a gap) — it is deliberately NOT wired into
the daily schedule.
"""

from __future__ import annotations

import logging
import time
from datetime import date, datetime, timedelta

import pytz

logger = logging.getLogger("fortress.bhavcopy.jobs")

IST = pytz.timezone("Asia/Kolkata")

# Small pause between backfill requests so a ~300-day backfill doesn't look
# like a scrape burst against NSE's edge.
_BACKFILL_REQUEST_DELAY_S = 1.5


def _today_ist() -> date:
    return datetime.now(IST).date()


def run_bhavcopy_refresh_job(
    trade_date: date | None = None, force: bool = False, session=None
) -> dict:
    """Fetch, parse, and persist one day's Bhav Copy (default: today, IST).

    Returns a summary dict: {"status": "done"|"skipped"|"not_yet_published"|"error",
    "trade_date": "YYYY-MM-DD", "symbol_count": int, "error": str|None}.

    `force=True` bypasses the bhavcopy_fetch_log dedup check (re-fetches even
    if today is already marked "done") — used for manual re-runs, not by the
    scheduled job. `session` lets a caller (e.g. backfill_bhavcopy) reuse one
    requests.Session across many days instead of re-doing the cookie warm-up
    per day.
    """
    from bhavcopy.logic import BhavCopyFormatError, BhavCopyUnavailable, fetch_bhavcopy
    from utils.db import get_bhavcopy_fetch_status, record_bhavcopy_fetch, upsert_bhavcopy_rows

    trade_date = trade_date or _today_ist()
    date_str = trade_date.isoformat()

    if not force:
        existing = get_bhavcopy_fetch_status(date_str)
        if existing == "done":
            logger.info("bhavcopy refresh: %s already fetched, skipping", date_str)
            return {"status": "skipped", "trade_date": date_str, "symbol_count": 0, "error": None}

    logger.info("bhavcopy refresh: fetching %s...", date_str)
    try:
        df = fetch_bhavcopy(trade_date, session=session)
    except BhavCopyUnavailable as exc:
        logger.info("bhavcopy refresh: %s not yet published: %s", date_str, exc)
        record_bhavcopy_fetch(date_str, status="not_yet_published", error_detail=str(exc))
        return {
            "status": "not_yet_published",
            "trade_date": date_str,
            "symbol_count": 0,
            "error": str(exc),
        }
    except (BhavCopyFormatError, Exception) as exc:
        logger.error("bhavcopy refresh: %s failed: %s", date_str, exc)
        record_bhavcopy_fetch(date_str, status="error", error_detail=str(exc))
        return {"status": "error", "trade_date": date_str, "symbol_count": 0, "error": str(exc)}

    written = upsert_bhavcopy_rows(df, date_str)
    record_bhavcopy_fetch(date_str, status="done", symbol_count=written)
    logger.info("bhavcopy refresh: %s done, %d symbols", date_str, written)
    return {"status": "done", "trade_date": date_str, "symbol_count": written, "error": None}


def backfill_bhavcopy(
    days: int = 300,
    start_from: date | None = None,
    max_fetches: int = 30,
    progress_cb=None,
) -> dict:
    """One-off backfill: walk backward from `start_from` (default: today,
    IST) over `days` calendar days, fetching and persisting each trading
    day's Bhav Copy. 404s (weekends/holidays) are skipped, not treated as
    errors. Not part of the daily schedule — run manually once when Bhav
    Copy is first activated (or to fill a known gap).

    `max_fetches` limits the number of actual network calls (days not already
    in the DB) to prevent the job from running too long and being killed by
    deployments. `progress_cb(processed, total)` is called per day to update
    visible state.

    Returns {"done": [...dates...], "skipped_no_data": [...dates...],
    "errors": {date: error_str}}.
    """
    from bhavcopy.logic import _new_session

    start_from = start_from or _today_ist()
    session = _new_session()

    done: list[str] = []
    skipped_no_data: list[str] = []
    errors: dict[str, str] = {}
    
    fetch_count = 0

    for offset in range(days):
        d = start_from - timedelta(days=offset)
        # Skip weekends outright — no network call needed, NSE never
        # publishes for Sat/Sun and this keeps the backfill from wasting
        # requests we already know will 404.
        if d.weekday() >= 5:
            if progress_cb:
                progress_cb(offset + 1, days)
            continue

        result = run_bhavcopy_refresh_job(trade_date=d, force=False, session=session)
        
        # Only count actual network calls against the chunk limit (dedup hits
        # are instantaneous).
        if result["status"] != "skipped":
            fetch_count += 1

        if result["status"] == "done" or result["status"] == "skipped":
            done.append(result["trade_date"])
        elif result["status"] == "not_yet_published":
            # For a past date this means "no trading that day" (holiday),
            # not "ask again later" — record it as such but don't error.
            skipped_no_data.append(result["trade_date"])
        else:
            errors[result["trade_date"]] = result["error"] or "unknown error"

        if progress_cb:
            progress_cb(offset + 1, days)

        if max_fetches > 0 and fetch_count >= max_fetches:
            logger.info("bhavcopy backfill chunk limit reached (%d fetches)", fetch_count)
            break

        time.sleep(_BACKFILL_REQUEST_DELAY_S)

    logger.info(
        "bhavcopy backfill complete: %d fetched/verified, %d no-data days, %d errors (chunk fetches: %d)",
        len(done),
        len(skipped_no_data),
        len(errors),
        fetch_count,
    )
    return {"done": done, "skipped_no_data": skipped_no_data, "errors": errors}
