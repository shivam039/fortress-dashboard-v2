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
from datetime import date, datetime, timedelta, timezone

import pytz

logger = logging.getLogger("fortress.bhavcopy.jobs")

IST = pytz.timezone("Asia/Kolkata")

# Small pause between backfill requests so a ~300-day backfill doesn't look
# like a scrape burst against NSE's edge. Only applied after an actual
# network attempt — see backfill_bhavcopy, which skips this for dedup hits.
_BACKFILL_REQUEST_DELAY_S = 1.5

# How long to leave a "fatal_error" day alone before retrying it. Without
# this, backfill_bhavcopy always resumes at the OLDEST unprocessed day, so a
# single date that fatally fails (NSE serving an HTML block page instead of
# a zip — see BhavCopyFormatError/BadZipFile handling below) gets re-requested
# as the very first live fetch of *every* subsequent chunk, forever, with no
# chance for the earlier chunks' already-covered days to matter. Observed in
# production: the exact same date (2026-06-26) failed identically across
# multiple chunks run minutes apart, and a direct fetch of that same URL from
# an unrelated network also came back blocked ("Service Temporarily
# Unavailable ... not accessible in your region") while an adjacent date
# fetched cleanly — strong evidence NSE's edge is suppressing that specific,
# repeatedly-hit URL rather than mounting a blanket IP ban. Backing off
# before retrying it, and not blocking progress on every other date in the
# meantime (see _MAX_CONSECUTIVE_FATAL_ERRORS), addresses both.
_FATAL_ERROR_RETRY_COOLDOWN_S = 2 * 60 * 60

# Abort the whole backfill run only after this many *consecutive* fatal
# errors — a real signal of a sustained block, as opposed to one stubborn
# date that other, untouched dates around it are unaffected by.
_MAX_CONSECUTIVE_FATAL_ERRORS = 3


def _today_ist() -> date:
    return datetime.now(IST).date()


def _seconds_since(fetched_at) -> float | None:
    """Best-effort seconds elapsed since `fetched_at` (a datetime from Neon,
    or a "YYYY-MM-DD HH:MM:SS" text timestamp from SQLite's CURRENT_TIMESTAMP,
    both naive-UTC). Returns None if it can't be parsed rather than raising —
    a cooldown check that can't tell how old an entry is should fail open
    (treat it as retryable) rather than crash the backfill."""
    if fetched_at is None:
        return None
    if isinstance(fetched_at, str):
        try:
            fetched_at = datetime.strptime(fetched_at, "%Y-%m-%d %H:%M:%S")
        except ValueError:
            return None
    if fetched_at.tzinfo is None:
        fetched_at = fetched_at.replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - fetched_at).total_seconds()


def run_bhavcopy_refresh_job(
    trade_date: date | None = None, force: bool = False, session=None
) -> dict:
    """Fetch, parse, and persist one day's Bhav Copy (default: today, IST).

    Returns a summary dict: {"status": "done"|"skipped"|"skipped_recent_fatal_error"|
    "not_yet_published"|"error"|"fatal_error", "trade_date": "YYYY-MM-DD",
    "symbol_count": int, "error": str|None}.

    `force=True` bypasses the bhavcopy_fetch_log dedup check (re-fetches even
    if today is already marked "done", and ignores the fatal_error cooldown
    below) — used for manual re-runs, not by the scheduled job. `session`
    lets a caller (e.g. backfill_bhavcopy) reuse one requests.Session across
    many days instead of re-doing the cookie warm-up per day.
    """
    from bhavcopy.logic import BhavCopyFormatError, BhavCopyUnavailable, fetch_bhavcopy
    from utils.db import (
        get_bhavcopy_fetch_log_entry,
        get_bhavcopy_fetch_status,
        record_bhavcopy_fetch,
        upsert_bhavcopy_rows,
    )
    import zipfile

    trade_date = trade_date or _today_ist()
    date_str = trade_date.isoformat()

    if not force:
        # Two calls rather than one get_bhavcopy_fetch_log_entry() lookup:
        # the plain status check covers the common "done"/never-attempted
        # cases with the same call this function has always made, and only
        # a "fatal_error" status pays for the extra detail lookup needed to
        # evaluate the retry cooldown below.
        existing_status = get_bhavcopy_fetch_status(date_str)
        if existing_status == "done":
            logger.info("bhavcopy refresh: %s already fetched, skipping", date_str)
            return {"status": "skipped", "trade_date": date_str, "symbol_count": 0, "error": None}
        if existing_status == "fatal_error":
            entry = get_bhavcopy_fetch_log_entry(date_str) or {}
            age_s = _seconds_since(entry.get("fetched_at"))
            if age_s is not None and age_s < _FATAL_ERROR_RETRY_COOLDOWN_S:
                logger.info(
                    "bhavcopy refresh: %s fatally failed %ds ago (< %ds cooldown), deferring retry",
                    date_str, int(age_s), _FATAL_ERROR_RETRY_COOLDOWN_S,
                )
                return {
                    "status": "skipped_recent_fatal_error",
                    "trade_date": date_str,
                    "symbol_count": 0,
                    "error": entry.get("error_detail"),
                }

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
    except (BhavCopyFormatError, zipfile.BadZipFile) as exc:
        logger.error("bhavcopy refresh: %s failed fatally: %s", date_str, exc)
        record_bhavcopy_fetch(date_str, status="fatal_error", error_detail=str(exc))
        return {"status": "fatal_error", "trade_date": date_str, "symbol_count": 0, "error": str(exc)}
    except Exception as exc:
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
    consecutive_fatal_errors = 0

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
        # and the fatal_error cooldown skip below don't touch NSE at all).
        made_network_call = result["status"] not in ("skipped", "skipped_recent_fatal_error")
        if made_network_call:
            fetch_count += 1

        if result["status"] == "done":
            done.append(result["trade_date"])
            consecutive_fatal_errors = 0
        elif result["status"] == "skipped":
            done.append(result["trade_date"])
        elif result["status"] == "skipped_recent_fatal_error":
            # Still cooling down from a recent fatal error on this exact
            # date — recorded as an error for visibility, but deliberately
            # NOT re-requested this run so we don't keep hammering the same
            # NSE URL every single chunk. A later run (once the cooldown in
            # _FATAL_ERROR_RETRY_COOLDOWN_S has passed) will retry it.
            errors[result["trade_date"]] = result["error"] or "recently failed fatally, deferring retry"
        elif result["status"] == "not_yet_published":
            # For a past date this means "no trading that day" (holiday),
            # not "ask again later" — record it as such but don't error.
            skipped_no_data.append(result["trade_date"])
            consecutive_fatal_errors = 0
        elif result["status"] == "fatal_error":
            errors[result["trade_date"]] = result["error"] or "fatal error"
            consecutive_fatal_errors += 1
            logger.error(
                "bhavcopy backfill: fatal error on %s (%d consecutive)",
                result["trade_date"], consecutive_fatal_errors,
            )
        else:
            errors[result["trade_date"]] = result["error"] or "unknown error"
            consecutive_fatal_errors = 0

        if progress_cb:
            progress_cb(offset + 1, days)

        if consecutive_fatal_errors >= _MAX_CONSECUTIVE_FATAL_ERRORS:
            logger.error(
                "bhavcopy backfill aborting: %d consecutive fatal errors (likely a sustained NSE block, "
                "not just one bad date) — most recently %s",
                consecutive_fatal_errors, result["trade_date"],
            )
            break

        if max_fetches > 0 and fetch_count >= max_fetches:
            logger.info("bhavcopy backfill chunk limit reached (%d fetches)", fetch_count)
            break

        # Only pace ourselves after an actual NSE request — a dedup hit or a
        # cooldown-deferred fatal_error day made no network call at all, so
        # sleeping here just makes re-walking already-covered ground slower
        # for no benefit (this was previously unconditional and made every
        # chunk spend most of its time re-confirming already-"done" days
        # before ever reaching new territory).
        if made_network_call:
            time.sleep(_BACKFILL_REQUEST_DELAY_S)

    logger.info(
        "bhavcopy backfill complete: %d fetched/verified, %d no-data days, %d errors (chunk fetches: %d)",
        len(done),
        len(skipped_no_data),
        len(errors),
        fetch_count,
    )
    return {"done": done, "skipped_no_data": skipped_no_data, "errors": errors}
