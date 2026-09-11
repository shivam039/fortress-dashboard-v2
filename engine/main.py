# engine/main.py
# AI agents modifying this file: see /AI_AGENT_PROTOCOL.md — log every change
# via engine/utils/ai_audit.py:log_ai_change().
import asyncio
import os
import sys
import uuid
from typing import Any, Callable, Dict, List, Optional

import pandas as pd
import uvicorn
from fastapi import APIRouter, BackgroundTasks, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

# Ensure engine directory is in path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

import logging
import traceback
import math
import resource
import time
from datetime import datetime

from commodities.logic import build_commodities_frame
from fortress_config import TICKER_GROUPS
from mf_lab.jobs import run_mf_background_job
from mf_lab.logic import run_full_mf_scan
from stock_scanner.logic import (
    DEFAULT_SCORING_CONFIG,
    FORTRESS_SCAN_LOGIC_VERSION,
    apply_advanced_scoring,
    check_institutional_fortress,
    fetch_ohlcv_fallback_chunk,
    get_stock_data,
    prefetch_metadata,
    _ohlcv_fallback_workers,
)
from options_algo.logic import fetch_option_chain, get_available_expiries, scan_strategies
from fortress_config import INDEX_BENCHMARKS
from utils.broker_mappings import generate_dhan_url, generate_zerodha_url
from utils.security_config import (
    is_production_environment,
    validate_cors_origins,
    validate_staging_database_isolation,
)
from utils.db import (
    complete_scan_job,
    create_scan_job,
    fail_scan_job,
    fetch_history_data,
    fetch_mf_cached_results,
    fetch_scan_history_list,
    get_scan_job,
    heartbeat_scan_job,
    mark_stale_scan_jobs_failed,
    record_signal_ledger_entries,
    register_scan,
    save_scan_results,
    update_scan_job_progress,
)


import numpy as np


def _sanitize_json_value(value):
    if value is None:
        return None
    try:
        import pandas as pd
        if pd.isna(value):
            return None
    except Exception:
        pass
        
    if isinstance(value, bool):
        return value
        
    if isinstance(value, (float, int)):
        if isinstance(value, float):
            if math.isnan(value) or math.isinf(value):
                return None
        return value
        
    try:
        import numpy as np
        if isinstance(value, np.floating):
            if np.isnan(value) or np.isinf(value):
                return None
            return float(value)
        if isinstance(value, np.integer):
            return int(value)
    except Exception:
        pass

    if isinstance(value, dict):
        return {str(k): _sanitize_json_value(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_sanitize_json_value(v) for v in value]
        
    # Catch any remaining float-like objects
    try:
        if math.isnan(float(value)) or math.isinf(float(value)):
            return None
    except Exception:
        pass

    return value

def generate_action_link(row, broker_choice):
    qty = row.get("Position_Qty", 0)
    symbol = row["Symbol"]
    price = row.get("Price", 0)

    if broker_choice == "Zerodha":
        url = generate_zerodha_url(symbol, qty)
    else:
        url = generate_dhan_url(symbol, qty, price)

    if not url:
        return "-"

    return f"<a href='{url}' target='_blank' style='text-decoration:none;' class='px-3 py-1 bg-blue-600/20 text-blue-400 hover:bg-blue-600/40 rounded border border-blue-500/30 text-[10px] font-black uppercase tracking-widest transition-colors'>⚡ Buy</a>"

# Configure logging
logging.basicConfig(level=logging.INFO)
logging.getLogger("yfinance").setLevel(logging.CRITICAL)
logger = logging.getLogger("fortress-api")


def _get_process_rss_mb() -> Optional[float]:
    """Return process max RSS in MB without making telemetry a hard dependency."""
    try:
        rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        divisor = 1024 * 1024 if sys.platform == "darwin" else 1024
        return round(rss / divisor, 1)
    except (AttributeError, OSError, TypeError, ValueError):
        return None


def _log_scan_stage(
    job_id: str, stage: str, started_at: float, rss_start_mb: Optional[float] = None
) -> None:
    rss_mb = _get_process_rss_mb()
    delta = (
        round(rss_mb - rss_start_mb, 1)
        if rss_mb is not None and rss_start_mb is not None
        else None
    )
    logger.info(
        "scan_stage job=%s stage=%s duration_s=%.3f rss_mb=%s rss_delta_mb=%s",
        job_id,
        stage,
        time.monotonic() - started_at,
        rss_mb if rss_mb is not None else "unavailable",
        delta if delta is not None else "unavailable",
    )

# Optional startup diagnostics for deployment debugging.
# Enable by setting environment variable FORTRESS_LOG_STARTUP=1 (or 'true').
# This avoids leaving noisy logs enabled by default while providing
# an easy way to confirm working directory and import paths on Render.
if os.environ.get("FORTRESS_LOG_STARTUP", "").strip().lower() in ("1", "true", "yes"):
    logger.info("Startup diagnostics: CWD=%s", os.getcwd())
    # Log only the first 20 sys.path entries to avoid overly large logs
    logger.info("Startup diagnostics: sys.path (first 20)=%s", sys.path[:20])

# API key auth — set FORTRESS_API_KEY env var to enable. Unset = local dev (no auth).
#
# FORTRESS-H3: deliberately NOT required in production, unlike
# FORTRESS_JWT_SECRET/FORTRESS_APP_PASSWORD. Every endpoint that returns
# user/account data already requires a valid JWT (cookie or Bearer token —
# see api_key_auth_middleware below and auth_utils.get_current_user), which
# is the actual authentication boundary; FORTRESS_API_KEY is a *supplementary*
# gate for non-browser/machine clients hitting the API directly. Forcing it
# on would change the authentication model (a non-goal for this story) for
# no additional safety on the JWT-protected surface. If a deployment wants
# to lock out unauthenticated read-only endpoints too, set FORTRESS_API_KEY —
# this stays a warning, not a startup failure, either way.
_FORTRESS_API_KEY = os.environ.get("FORTRESS_API_KEY", "")
if not _FORTRESS_API_KEY:
    logger.warning(
        "FORTRESS_API_KEY is not set — FastAPI endpoints are unauthenticated. Set this env var in production."
    )

app = FastAPI(title="Fortress API", version="2.0")
mf_router = APIRouter(prefix="/mf", tags=["mutual-funds"])
ENABLE_NEW_FEATURES = (
    os.environ.get("FORTRESS_ENABLE_NEW_FEATURES", "false").strip().lower() == "true"
)

# ── New REST routers for the Next.js frontend ────────────────────────────────
from routers.auth import router as auth_router
from routers.users import router as users_router
from routers.orders import router as orders_router
from routers.brokers import router as brokers_router
from routers.picks import router as picks_router
from routers.telegram import router as telegram_router
from routers.reit_invits import router as reit_invits_router
from routers.us_investing import router as us_investing_router
from routers.investments import router as investments_router
from routers.bhavcopy import router as bhavcopy_router
from routers.research_evidence import router as research_evidence_router
from routers.paper_trading import router as paper_trading_router
from routers.auto_scan import router as auto_scan_router


@app.middleware("http")
async def api_key_auth_middleware(request, call_next):
    """Require X-API-Key header when FORTRESS_API_KEY env var is configured.

    Auth-router endpoints (/api/auth/*) are excluded — they issue tokens.
    JWT-protected endpoints handle their own auth via FastAPI Depends().
    """
    if _FORTRESS_API_KEY:
        path = request.url.path
        # Skip auth for: health, CORS preflight, auth endpoints, and JWT-protected routes
        skip_paths = path in ("/api/health",) or path.startswith("/api/auth/")
        if not skip_paths and request.method != "OPTIONS":
            provided_key = request.headers.get("X-API-Key", "")
            # Also accept JWT Bearer token (new routers handle their own auth)
            has_jwt = request.headers.get("Authorization", "").startswith("Bearer ")
            has_cookie = "fortress_token" in request.cookies
            if provided_key != _FORTRESS_API_KEY and not has_jwt and not has_cookie:
                return JSONResponse(
                    status_code=401,
                    content={
                        "error": "Unauthorized. Provide a valid X-API-Key header or JWT token."
                    },
                )
    return await call_next(request)


@app.middleware("http")
async def catch_exceptions_middleware(request, call_next):
    try:
        return await call_next(request)
    except Exception as exc:
        # Full traceback is logged server-side — never exposed to the client
        logger.error(
            f"Unhandled exception on {request.method} {request.url.path}: {exc}"
        )
        logger.error(traceback.format_exc())
        return JSONResponse(
            status_code=500,
            content={
                "error": "An internal server error occurred. Please try again or contact support.",
                "path": str(request.url.path),
                # Error ID helps correlate with server logs without leaking internals
                "error_id": f"{hash(str(exc)) & 0xFFFFFF:06X}",
            },
        )


_cors_origins = [
    origin.strip()
    for origin in os.environ.get(
        "FORTRESS_CORS_ORIGINS",
        "http://localhost:3000,http://127.0.0.1:3000",
    ).split(",")
    if origin.strip()
]
# FORTRESS-H3: refuse to start in production with an unrestricted ("*")
# CORS origin — see utils/security_config.validate_cors_origins. The
# unset default above is already restricted to localhost, never a
# wildcard; this only catches an operator explicitly (mis)configuring
# FORTRESS_CORS_ORIGINS=*.
if is_production_environment():
    validate_cors_origins(_cors_origins)

validate_staging_database_isolation(
    os.environ.get("FORTRESS_ENV"),
    os.environ.get("DATABASE_URL"),
    os.environ.get("FORTRESS_PRODUCTION_DB_MARKERS"),
)

# FORTRESS-V4 / Blocker D: refuse to start in production if Neon/Postgres
# is misconfigured or unreachable — see utils/db.validate_database_
# configuration. Previously _can_use_neon() silently fell back to
# ephemeral local SQLite in this exact case, which is unsafe in production
# (that storage can disappear on restart). Dev/local (sqlite/local) is
# unaffected.
from utils.db import validate_database_configuration

validate_database_configuration()

app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class ScanRequest(BaseModel):
    universe: str
    portfolio_val: float = 1000000
    risk_pct: float = 0.01
    weights: Optional[Dict[str, float]] = None
    enable_regime: bool = True
    liquidity_cr_min: float = 8.0
    market_cap_cr_min: float = 1500.0
    price_min: float = 80.0
    broker: str = "Zerodha"


class MFJobRequest(BaseModel):
    """Request body for async MF background jobs."""

    job_type: str = Field(
        ...,
        examples=[
            "refresh_nav",
            "update_metrics",
            "full_refresh",
            "recalculate_rankings",
        ],
    )
    force_refresh: bool = False
    scheme_codes: Optional[List[str]] = None


@app.get("/api/health")
def health_check():
    return {
        "status": "healthy",
        "version": "2.0",
        "enable_new_features": ENABLE_NEW_FEATURES,
    }


@app.get("/api/universes")
def get_universes():
    return list(TICKER_GROUPS.keys())


@app.get("/api/market-data-status")
def get_market_data_status():
    """Report which market data provider is actually active right now.

    Surfaces `market_data_provider.provider_status()` over HTTP so the
    frontend can show the live data source (e.g. an "INDmoney" badge) instead
    of just assuming the docs are accurate. Also reports the stock universe
    sizes currently configured, since universes are scanned through the same
    provider chain.
    """
    from utils.market_data_provider import provider_status

    status = provider_status()
    return {
        **status,
        "universes": {name: len(tickers) for name, tickers in TICKER_GROUPS.items()},
    }


def _noop_progress(stage: str, current: Optional[int] = None, total: Optional[int] = None, message: Optional[str] = None) -> None:
    pass


def execute_scan(
    req: ScanRequest,
    progress_cb: Optional[Callable[..., None]] = None,
    tickers_override: Optional[List[str]] = None,
    run_meta: Optional[Dict[str, Any]] = None,
    universe_membership: Optional[Dict[str, List[str]]] = None,
    job_id: Optional[str] = None,
) -> Any:
    """Run one full stock scan: universe resolution, metadata prefetch,
    market-data fetch, per-ticker indicator calc/scoring, scoring
    normalization, and scan-history persistence — then return the exact
    same JSON-serializable response shape `POST /api/scan` has always
    returned (a bare list of scored records, or the aborted-early/
    no-results dict).

    Extracted out of the `POST /api/scan` route (FORTRESS-P3) so the exact
    same scan logic — nothing about scoring, retries, or the circuit
    breaker changed — can run either synchronously on the request path (the
    existing `run_scan` route below) or off it, from a background task
    driven by `POST /api/scan/jobs` (see `_run_scan_job`). `progress_cb`,
    when given, is called at each real stage boundary (universe, metadata,
    market_data, indicators, scoring, persistence) plus periodically during
    the per-ticker loop; the synchronous route passes no callback at all
    (`_noop_progress` is dependency-free and costs nothing extra).
    """
    if progress_cb is None:
        progress_cb = _noop_progress

    from stock_scanner.pulse import get_current_regime

    # FORTRESS-E3: an automated multi-universe run passes its own
    # deduplicated symbol union in directly (req.universe is then just a
    # descriptive label for scan_history/signal_ledger, not a TICKER_GROUPS
    # lookup key) — every other caller leaves this None and keeps the
    # original universe-name resolution unchanged.
    if tickers_override is not None:
        tickers = list(tickers_override)
    else:
        tickers = TICKER_GROUPS.get(req.universe)
        if not tickers:
            raise HTTPException(status_code=404, detail="Universe not found")

    progress_cb("universe", current=0, total=len(tickers), message=f"Resolved {len(tickers)} tickers for {req.universe}")

    # FORTRESS-P2 instrumentation: lightweight per-stage timings, logged as
    # one structured line at the end of the scan (see below) so before/after
    # comparisons don't need ad-hoc profiling. Never included in the HTTP
    # response — this is server-side observability only, not an API change.
    _t_scan_start = time.monotonic()
    _scan_job_id = job_id or "sync"
    scan_timings = {}

    # ── Fetch live market regime ONCE for the entire scan ──────────────────────
    try:
        regime_data = get_current_regime()
        logger.info(
            f"Scan regime: {regime_data['Market_Regime']} (x{regime_data['Regime_Multiplier']})"
        )
    except Exception as e:
        logger.warning(f"Regime fetch failed, defaulting to Range: {e}")
        regime_data = {"Market_Regime": "Range", "Regime_Multiplier": 1.0, "VIX": 20.0}

    results = []

    # FORTRESS-E3: optional side-channel for callers that need scan-internal
    # bookkeeping (scan_id, signal ledger rows written, the E1 insert/
    # duplicate counts) that execute_scan's own return value has never
    # exposed — e.g. research.auto_scan's daily summary. `run_meta` stays
    # untouched for every existing caller that doesn't pass one.
    _scan_meta: Dict[str, Any] = {
        "scan_id": None, "signals_written": 0, "research_observations_result": None,
    }

    # Circuit breaker: individual ticker failures were logged and skipped
    # with no aggregate tracking, so a broad provider outage (yfinance
    # rate-limited, network down, etc.) meant grinding through every
    # remaining ticker in the universe one at a time — each one failing
    # slowly — instead of surfacing the problem and stopping early. Once at
    # least _BREAKER_MIN_SAMPLE tickers have been attempted, if the failure
    # rate is at or above _BREAKER_FAILURE_RATE, stop scanning the rest of
    # the universe and return whatever partial results exist along with a
    # clear signal that the scan was aborted early, rather than a
    # silently-shorter results list with no explanation.
    _BREAKER_MIN_SAMPLE = 10
    _BREAKER_FAILURE_RATE = 0.8
    scan_attempted = 0
    scan_failed = 0
    circuit_breaker_tripped = False

    # Pre-load fundamental/news/calendar/earnings metadata for the whole
    # universe (DB cache first, then a bounded-concurrency live fetch for
    # whatever's missing/stale — see prefetch_metadata()'s docstring for the
    # full FORTRESS-P2 design), so the per-ticker loop below normally
    # consumes already-loaded metadata instead of making its own blocking
    # calls.
    progress_cb("metadata", current=0, total=len(tickers), message="Prefetching ticker metadata")
    _metadata_started = time.monotonic()
    _metadata_rss_start = _get_process_rss_mb()
    _t0 = time.monotonic()
    # `or {}`: defensive against test doubles / callers built against the
    # pre-P2 contract (prefetch_metadata() used to return None implicitly).
    prefetch_stats = prefetch_metadata(tickers) or {}
    scan_timings["metadata_prefetch_s"] = round(time.monotonic() - _t0, 3)
    scan_timings["metadata_cache_hits"] = prefetch_stats.get("cache_hits", 0)
    scan_timings["metadata_cache_misses"] = prefetch_stats.get("cache_misses", 0)
    scan_timings["metadata_external_fetches"] = prefetch_stats.get("external_fetches", 0)
    scan_timings["metadata_fetch_successes"] = prefetch_stats.get("fetch_successes", 0)
    scan_timings["metadata_fetch_failures"] = prefetch_stats.get("fetch_failures", 0)
    scan_timings["metadata_persist_s"] = prefetch_stats.get("persist_duration_s", 0.0)
    _log_scan_stage(_scan_job_id, "metadata", _metadata_started, _metadata_rss_start)
    progress_cb(
        "metadata",
        current=len(tickers),
        total=len(tickers),
        message=f"Metadata ready ({prefetch_stats.get('cache_hits', 0)} cached, "
        f"{prefetch_stats.get('fetch_successes', 0)} fetched)",
    )

    # Keep the existing yfinance-based implementation, but make it resilient:
    # if the bulk download fails or returns partial data, fall back to per-symbol
    # fetches so one bad ticker does not fail the entire scan.
    progress_cb("market_data", current=0, total=len(tickers), message="Fetching market data")
    _market_data_started = time.monotonic()
    _market_data_rss_start = _get_process_rss_mb()
    _t0 = time.monotonic()
    _indicator_rss_start = _get_process_rss_mb()
    batch_data = get_stock_data(
        tuple(tickers), period="1y", interval="1d", group_by="ticker"
    )
    scan_timings["market_data_s"] = round(time.monotonic() - _t0, 3)
    _log_scan_stage(_scan_job_id, "market_data", _market_data_started, _market_data_rss_start)
    fallback_active = batch_data.empty
    if fallback_active:
        logger.warning("Bulk market data fetch returned no rows for %s", req.universe)
    progress_cb(
        "market_data",
        current=len(tickers),
        total=len(tickers),
        message="Market data ready" if not fallback_active else "Market data fetch degraded, using per-ticker fallback",
    )

    def _maybe_trip_breaker(reason: str):
        """FORTRESS-V4: shared trip check for both the batch and per-ticker
        fallback paths below, so the threshold is evaluated identically
        everywhere scan_attempted/scan_failed change."""
        nonlocal circuit_breaker_tripped
        if circuit_breaker_tripped:
            return
        if (
            scan_attempted >= _BREAKER_MIN_SAMPLE
            and (scan_failed / scan_attempted) >= _BREAKER_FAILURE_RATE
        ):
            logger.error(
                "run_scan: circuit breaker tripped for universe=%s (%s) — "
                "%d/%d tickers failed/unusable (>=%.0f%% failure rate); "
                "aborting the remaining %d tickers instead of grinding "
                "through a likely provider outage",
                req.universe,
                reason,
                scan_failed,
                scan_attempted,
                _BREAKER_FAILURE_RATE * 100,
                len(tickers) - scan_attempted,
            )
            circuit_breaker_tripped = True

    def _record_result(ticker, hist):
        nonlocal scan_attempted, scan_failed
        scan_attempted += 1
        try:
            # FORTRESS-V4: no usable market data is itself an evaluation
            # failure — this is the exact "outage" signal V3 found silently
            # invisible here, because check_institutional_fortress's own
            # internal `len(data) < 210` early-return looked identical to a
            # legitimate scoring rejection at this call site. Checking the
            # length here, before calling it, keeps that function (scoring
            # logic) completely untouched while still counting this
            # correctly. A ticker that *does* clear this bar and is still
            # rejected by check_institutional_fortress (e.g. the smallcap
            # liquidity guard) used real data and is a legitimate scoring
            # outcome — never counted as a provider failure.
            if hist is None or hist.empty or len(hist) < 210:
                scan_failed += 1
                logger.warning(
                    "No usable market data for %s (%d rows, need >=210)",
                    ticker, 0 if hist is None else len(hist),
                )
            else:
                # FORTRESS-E3: a combined multi-universe run passes one
                # synthetic label as req.universe (see tickers_override
                # above), which would otherwise silently disable
                # check_institutional_fortress's Nifty-Smallcap-250-only
                # liquidity guard for every smallcap symbol scored this way.
                # `universe_membership` restores the exact per-symbol
                # universe string a standalone scan of that universe would
                # have passed — no other selected_universe value changes any
                # scoring behavior (see stock_scanner/logic.py), so this is
                # the only case that needs preserving.
                symbol_universe = req.universe
                if universe_membership is not None and (
                    "Nifty Smallcap 250" in universe_membership.get(ticker, [])
                ):
                    symbol_universe = "Nifty Smallcap 250"
                res = check_institutional_fortress(
                    ticker,
                    hist,
                    None,
                    req.portfolio_val,
                    req.risk_pct,
                    selected_universe=symbol_universe,
                    regime_data=regime_data,  # ← live regime passed
                )
                if res:
                    results.append(res)
        except Exception as e:
            logger.warning(f"Error scanning {ticker}: {e}")
            scan_failed += 1

        _maybe_trip_breaker("indicators")
        progress_cb(
            "indicators",
            current=scan_attempted,
            total=len(tickers),
            message=f"Scored {scan_attempted}/{len(tickers)} tickers ({len(results)} matched so far)",
        )

    _t0 = time.monotonic()
    _indicator_rss_start = _get_process_rss_mb()
    progress_cb("indicators", current=0, total=len(tickers), message="Running indicator calculation and scoring")
    if fallback_active:
        # FORTRESS-P2: the batch fetch returned nothing, so every ticker
        # needs its own OHLCV fetch — previously fully serial. Fetch one
        # bounded-size chunk at a time with a thread pool, then run that
        # chunk through the exact same circuit-breaker accounting as the
        # non-fallback path below before moving to the next chunk. Chunking
        # (rather than fetching the whole universe concurrently up front)
        # preserves the breaker's early-exit behavior: once it trips, no
        # further chunks are fetched at all, not just not scored.
        def _fallback_fetch_one(ticker):
            # Routed through this module's own `get_stock_data` name (not
            # stock_scanner.logic's) so tests/monkeypatches targeting
            # main.get_stock_data keep working, and so this stays the exact
            # same call the pre-P2 serial fallback made.
            return get_stock_data(
                ticker, period="1y", interval="1d", group_by="column"
            ).dropna()

        chunk_size = _ohlcv_fallback_workers(len(tickers))
        for i in range(0, len(tickers), chunk_size):
            chunk = tickers[i : i + chunk_size]
            chunk_results = fetch_ohlcv_fallback_chunk(chunk, fetch_fn=_fallback_fetch_one)
            for ticker in chunk:
                hist, fetch_exc = chunk_results.get(ticker, (pd.DataFrame(), None))
                if fetch_exc is not None:
                    scan_attempted += 1
                    scan_failed += 1
                    logger.warning(f"Error scanning {ticker}: {fetch_exc}")
                    _maybe_trip_breaker("fallback fetch")
                    progress_cb(
                        "indicators",
                        current=scan_attempted,
                        total=len(tickers),
                        message=f"Scored {scan_attempted}/{len(tickers)} tickers ({len(results)} matched so far)",
                    )
                else:
                    _record_result(ticker, hist if hist is not None else pd.DataFrame())
                if circuit_breaker_tripped:
                    break
            if circuit_breaker_tripped:
                break
    else:
        for ticker in tickers:
            hist = (
                batch_data[ticker].dropna()
                if len(tickers) > 1 and ticker in batch_data.columns.get_level_values(0)
                else batch_data.dropna()
            )
            _record_result(ticker, hist)
            if circuit_breaker_tripped:
                break
    scan_timings["indicator_scoring_loop_s"] = round(time.monotonic() - _t0, 3)
    _log_scan_stage(_scan_job_id, "indicators", _t0, _indicator_rss_start)

    def _score_results(raw_results):
        """Shared scoring step for both the normal path and the
        circuit-breaker-tripped-with-partial-results path. Returns the
        scored DataFrame (not a dict) so callers can both serialize it for
        the API response and persist it to scan history unchanged."""
        score_df = pd.DataFrame(raw_results)
        scoring_config = DEFAULT_SCORING_CONFIG.copy()
        scoring_config.update(
            {
                "enable_regime": req.enable_regime,
                "liquidity_cr_min": req.liquidity_cr_min,
                "market_cap_cr_min": req.market_cap_cr_min,
                "price_min": req.price_min,
                "regime": regime_data,  # ← live regime for apply_advanced_scoring
            }
        )
        if req.weights:
            scoring_config["weights"] = req.weights
        progress_cb("scoring", current=0, total=1, message="Computing scores")
        _t0_scoring = time.monotonic()
        scored = apply_advanced_scoring(score_df, scoring_config)
        scan_timings["scoring_s"] = round(time.monotonic() - _t0_scoring, 3)
        _log_scan_stage(_scan_job_id, "scoring", _t0_scoring, None)
        progress_cb("scoring", current=1, total=1, message="Scoring complete")
        return scored

    def _log_scan_timings():
        scan_timings["total_scan_s"] = round(time.monotonic() - _t_scan_start, 3)
        _log_scan_stage(_scan_job_id, "total", _t_scan_start, None)
        logger.info(
            "scan_timing universe=%s tickers=%d scanned=%d failed=%d %s",
            req.universe,
            len(tickers),
            scan_attempted,
            scan_failed,
            scan_timings,
        )

    def _persist_scan_history(score_df):
        """Save this scan's scored results to scan_history_details so the
        frontend's Scan History page (/api/history/timestamps + /api/history/data)
        has something to show. This was previously only wired up in the
        legacy Streamlit UI (stock_scanner/ui.py's _save_scan) and the
        Telegram bot script — /api/scan, which is what the actual Next.js
        frontend calls, never called register_scan/save_scan_results at
        all, so the Scan History page was always empty no matter what ran.
        Best-effort: a history-write failure must never fail the scan
        response itself, since the results are already computed."""
        if score_df is None or score_df.empty:
            return
        progress_cb("persistence", current=0, total=1, message="Saving scan history")
        _t0_persist = time.monotonic()
        # FORTRESS-V4: each write is independent and best-effort — a legacy
        # scan_history_details failure (e.g. a fresh/partially-migrated DB
        # missing that table) must not silently prevent T1's signal ledger
        # or E1's research observations from being recorded for an
        # otherwise-successful scan. Previously all three shared one try
        # block, so the first failure silently skipped the rest.
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        history_df = score_df.copy()
        history_df["Universe"] = req.universe
        scan_id = None
        try:
            scan_id = register_scan(
                timestamp, universe=req.universe, scan_type="STOCK", status="Completed"
            )
            save_scan_results(scan_id, history_df, scan_timestamp=timestamp)
        except Exception as e:
            logger.warning("run_scan: failed to persist scan history: %s", e)
        try:
            _record_signal_ledger(history_df, scan_id, timestamp)
        except Exception as e:
            logger.warning("run_scan: failed to record signal ledger: %s", e)
        try:
            _record_research_observations(history_df, scan_id, timestamp)
        except Exception as e:
            logger.warning("run_scan: failed to record research observations: %s", e)
        finally:
            scan_timings["db_persist_s"] = round(time.monotonic() - _t0_persist, 3)
            _log_scan_stage(_scan_job_id, "persistence", _t0_persist, None)
            progress_cb("persistence", current=1, total=1, message="Scan history saved")

    def _record_signal_ledger(history_df, scan_id, timestamp):
        """FORTRESS-T1: append one immutable signal_ledger row per scored
        ticker, capturing enough point-in-time state (the full scored row,
        plus the specific fields most likely to be queried directly) to
        reconstruct exactly what Fortress knew when the signal was
        generated — independent of what a later re-scan says. Append-only:
        record_signal_ledger_entries() only ever INSERTs, never UPDATEs, so
        a re-scan of the same symbol adds a new row rather than overwriting
        this one. Best-effort — a ledger-write failure must not affect the
        scan response, same as scan-history persistence above (this is
        already inside that function's own try/except)."""
        try:
            from utils.market_data_provider import provider_status
            data_source = provider_status().get("ohlcv_source")
        except Exception:
            data_source = None

        entries = []
        for row in history_df.to_dict(orient="records"):
            verdict = row.get("Verdict")
            gate_failures = row.get("Quality_Gate_Failures") or ""
            explanation = f"{verdict or 'N/A'} — {row.get('Strategy', 'N/A')}"
            if gate_failures:
                explanation += f" (gate failures: {gate_failures})"
            entries.append({
                "generated_at": timestamp,
                "symbol": row.get("Symbol"),
                "sector": row.get("Sector"),
                "score": row.get("Score"),
                "component_scores": _sanitize_json_value(row.get("sub_scores") or {}),
                "market_regime": row.get("Market_Regime") or row.get("Regime"),
                "regime_multiplier": row.get("Regime_Multiplier"),
                "price_used": row.get("Price"),
                "data_source": data_source,
                "data_timestamp": row.get("Data_As_Of"),
                "scan_id": scan_id,
                "scan_version": FORTRESS_SCAN_LOGIC_VERSION,
                "universe": req.universe,
                "explanation": explanation,
                "suggested_entry": row.get("Price"),
                "stop_loss": row.get("Stop_Loss"),
                "target": row.get("Target_10D"),
                "risk_classification": verdict,
                # The full scored row — the actual point-in-time
                # reconstruction payload; every other field above is just a
                # queryable projection of this.
                "feature_snapshot": _sanitize_json_value(row),
            })

        if entries:
            written = record_signal_ledger_entries(entries)
            _scan_meta["scan_id"] = scan_id
            _scan_meta["signals_written"] = written
            if written < len(entries):
                logger.warning(
                    "run_scan: signal ledger wrote %d/%d entries for scan_id=%s",
                    written, len(entries), scan_id,
                )

    def _record_research_observations(history_df, scan_id, timestamp):
        """FORTRESS-E1: append one research_observations row per
        successfully-scored ticker (the full score_df, not just signals —
        see docs/research/PROSPECTIVE_EVIDENCE_COLLECTION.md). Never runs
        when the circuit breaker tripped: a provider-outage-truncated scan
        must not masquerade as valid evidence. Best-effort, same as
        _record_signal_ledger above."""
        if circuit_breaker_tripped:
            logger.info("run_scan: circuit breaker tripped — skipping research observation collection")
            return
        try:
            from research.prospective_store import collect_from_scan
            from utils.market_data_provider import provider_status
            data_source = provider_status().get("ohlcv_source")
            trading_date = timestamp.split(" ")[0]
            result = collect_from_scan(
                history_df.to_dict(orient="records"), scan_id, trading_date,
                FORTRESS_SCAN_LOGIC_VERSION, data_source=data_source,
            )
            _scan_meta["research_observations_result"] = result
            logger.info("run_scan: research observations for scan_id=%s: %s", scan_id, result)
        except Exception as e:
            logger.warning("run_scan: failed to record research observations: %s", e)

    if circuit_breaker_tripped:
        # Score whatever partial results came through before the breaker
        # tripped (may be zero) rather than discarding them, but always use
        # the "aborted early" summary so a real provider outage is never
        # confused with "nothing matched the screen" (asArray() on the
        # frontend already handles a {results: [...]} dict same as a bare
        # list, so this doesn't change how existing successful scans render).
        score_df = _score_results(results) if results else None
        _persist_scan_history(score_df)
        _log_scan_timings()
        if run_meta is not None:
            run_meta.update(_scan_meta)
            run_meta.update({"scanned": scan_attempted, "failed": scan_failed, "circuit_breaker_tripped": True})
        return {
            "results": _sanitize_json_value(score_df.to_dict(orient="records")) if score_df is not None else [],
            "summary": (
                f"Scan aborted early: {scan_failed}/{scan_attempted} tickers "
                f"failed before {len(results)} results could be scored. This "
                "usually means the market data provider is rate-limited or "
                "unreachable right now — try again shortly."
            ),
            "scanned": scan_attempted,
            "failed": scan_failed,
            "circuit_breaker_tripped": True,
        }

    if not results:
        _log_scan_timings()
        if run_meta is not None:
            run_meta.update(_scan_meta)
            run_meta.update({"scanned": scan_attempted, "failed": scan_failed, "circuit_breaker_tripped": False})
        return {
            "results": [],
            "summary": "No tickers met criteria or market data was unavailable.",
            "scanned": scan_attempted,
            "failed": scan_failed,
            "circuit_breaker_tripped": False,
        }

    # Generate action links
    score_df = _score_results(results)
    _persist_scan_history(score_df)
    _log_scan_timings()
    if run_meta is not None:
        run_meta.update(_scan_meta)
        run_meta.update({"scanned": scan_attempted, "failed": scan_failed, "circuit_breaker_tripped": False})
    return _sanitize_json_value(score_df.to_dict(orient="records"))


@app.post("/api/scan")
def run_scan(req: ScanRequest):
    # Plain `def`, not `async def`: everything execute_scan() does
    # (INDstocks/yfinance network calls, pandas/pandas_ta scoring) is
    # synchronous blocking work. Declaring it `async def` with no `await`
    # inside would run it directly on uvicorn's single event-loop thread,
    # freezing the ENTIRE server — including unrelated requests like
    # /api/health and the frontend's status polling — for the whole scan
    # duration. A plain `def` route is run by FastAPI in its threadpool
    # instead, so the event loop stays free to serve other requests
    # concurrently while a scan is in flight.
    #
    # Kept as the synchronous entry point for backward compatibility —
    # existing callers of POST /api/scan see identical behavior and
    # response shape. FORTRESS-P3 added POST /api/scan/jobs below for
    # callers that want the same scan run off the request path entirely,
    # with progress polling instead of one long blocking call.
    return execute_scan(req)


# ── Async scan jobs (FORTRESS-P3) ───────────────────────────────────────────
# Moves a long-running scan off the synchronous request path:
#   POST /api/scan/jobs                  -> {job_id, status: "queued"}
#   GET  /api/scan/jobs/{job_id}/status  -> status/stage/progress/error
#   GET  /api/scan/jobs/{job_id}/results -> the same shape POST /api/scan
#                                            already returns, once completed
#
# Job state lives in the scan_jobs DB table (utils.db), not in memory, so a
# browser refresh/reconnect just resumes polling the same job_id and sees
# the same state — no client-side session/state to lose. Uses FastAPI's
# BackgroundTasks + asyncio.to_thread (the same pattern engine/mf_lab/jobs.py
# already uses for MF background jobs) rather than a new task queue —
# nothing about the current deployment (a single persistent Render web
# service) requires more than that for one background scan at a time per
# request.

_JOB_PROGRESS_UPDATES_PER_SCAN = 20  # throttle: ~20 DB writes/scan regardless of universe size
_DEFAULT_SCAN_JOB_HEARTBEAT_SECONDS = 45


def _scan_job_heartbeat_seconds() -> float:
    try:
        value = float(os.getenv("FORTRESS_SCAN_JOB_HEARTBEAT_SECONDS", "45"))
        return value if value > 0 else _DEFAULT_SCAN_JOB_HEARTBEAT_SECONDS
    except (TypeError, ValueError):
        return _DEFAULT_SCAN_JOB_HEARTBEAT_SECONDS


async def _heartbeat_scan_job(job_id: str) -> None:
    """Keep a running scan fresh until its owning task exits."""
    interval = _scan_job_heartbeat_seconds()
    while True:
        await asyncio.sleep(interval)
        await asyncio.to_thread(heartbeat_scan_job, job_id)


def _make_job_progress_cb(job_id: str) -> Callable[..., None]:
    """Build a progress_cb for execute_scan() that persists progress to the
    scan_jobs table, throttled so a 500-ticker scan doesn't turn into 500
    extra DB writes on top of its own work. Every call still marks the job
    'running' (idempotent) so the first progress event is what flips a job
    out of 'queued'."""
    last_reported = {"current": -1}

    def _cb(stage: str, current: Optional[int] = None, total: Optional[int] = None, message: Optional[str] = None) -> None:
        if stage == "indicators" and current is not None and total:
            step = max(1, total // _JOB_PROGRESS_UPDATES_PER_SCAN)
            if current != total and (current - last_reported["current"]) < step:
                return
            last_reported["current"] = current
        update_scan_job_progress(
            job_id, status="running", stage=stage, current=current, total=total, message=message
        )

    return _cb


async def _run_scan_job(job_id: str, req: ScanRequest) -> None:
    """Background-task entry point for one scan job. Reuses execute_scan()
    unchanged — the same scoring, retries, and circuit-breaker behavior as
    the synchronous POST /api/scan — so job results are byte-compatible and
    scoring itself is never touched here."""
    progress_cb = _make_job_progress_cb(job_id)
    heartbeat_task = asyncio.create_task(_heartbeat_scan_job(job_id))
    try:
        result = await asyncio.to_thread(execute_scan, req, progress_cb, job_id=job_id)
        complete_scan_job(job_id, result)
        logger.info("scan job %s completed", job_id)
    except Exception as exc:
        logger.error("scan job %s failed: %s", job_id, exc, exc_info=True)
        fail_scan_job(job_id, str(exc))
    finally:
        heartbeat_task.cancel()
        await asyncio.gather(heartbeat_task, return_exceptions=True)


@app.post("/api/scan/jobs", status_code=202)
async def create_scan_job_endpoint(req: ScanRequest, background_tasks: BackgroundTasks):
    """Accept a scan request and run it off the request path. Returns
    immediately with a job_id; poll GET /api/scan/jobs/{job_id}/status for
    progress and GET /api/scan/jobs/{job_id}/results once completed."""
    tickers = TICKER_GROUPS.get(req.universe)
    if not tickers:
        raise HTTPException(status_code=404, detail="Universe not found")

    job_id = str(uuid.uuid4())
    create_scan_job(job_id, req.universe, req.model_dump())
    background_tasks.add_task(_run_scan_job, job_id, req)

    logger.info(
        "scan job %s queued for universe=%s (%d tickers)", job_id, req.universe, len(tickers)
    )
    return {"job_id": job_id, "status": "queued"}


@app.get("/api/scan/jobs/{job_id}/status")
def get_scan_job_status(job_id: str):
    job = get_scan_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return {
        "job_id": job["job_id"],
        "status": job["status"],
        "stage": job.get("stage"),
        "progress": {
            "current": job.get("progress_current") or 0,
            "total": job.get("progress_total") or 0,
        },
        "message": job.get("message"),
        "universe": job.get("universe"),
        "error": job.get("error"),
        "created_at": job.get("created_at"),
        "updated_at": job.get("updated_at"),
    }


@app.get("/api/scan/jobs/{job_id}/results")
def get_scan_job_results(job_id: str):
    job = get_scan_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")

    status = job["status"]
    if status == "completed":
        # Byte-compatible with POST /api/scan's own response shape — a bare
        # list on a normal successful scan, or the aborted-early/no-results
        # dict, exactly as complete_scan_job() stored it.
        return job.get("results_json")

    if status == "failed":
        return JSONResponse(
            status_code=200,
            content={"status": "failed", "error": job.get("error") or "Scan failed"},
        )

    # queued/running — not ready yet. 202 (not an error) so pollers can
    # distinguish "still working" from an actual failure without parsing
    # the body first.
    return JSONResponse(
        status_code=202,
        content={
            "status": status,
            "stage": job.get("stage"),
            "progress": {
                "current": job.get("progress_current") or 0,
                "total": job.get("progress_total") or 0,
            },
            "message": job.get("message"),
        },
    )


@app.get("/api/symbols/search")
def search_symbols(q: str = Query(..., min_length=1), n: int = 10):
    """Ticker/company-name suggestions for the UI's stock search box.

    Tries the INDstocks instruments cache first (has full company names);
    falls back to Bhav Copy's own distinct symbol list (tickers only, no
    company names) so search still works when INDstocks credentials are
    broken or expired — see utils.instruments_cache / utils.db.search_bhavcopy_symbols.
    """
    query = q.strip()
    if not query:
        return []

    try:
        from utils.instruments_cache import get_instruments_cache

        matches = get_instruments_cache().search_symbol(query, n=n)
        if matches:
            return [
                {
                    "symbol": f"{m['TRADING_SYMBOL'].upper()}.NS",
                    "name": m.get("SYMBOL_NAME", ""),
                }
                for m in matches
            ]
    except Exception as e:
        logger.debug(f"Instruments-cache symbol search failed, falling back to Bhav Copy: {e}")

    try:
        from utils.db import search_bhavcopy_symbols

        return [{"symbol": s, "name": ""} for s in search_bhavcopy_symbols(query, limit=n)]
    except Exception as e:
        logger.warning(f"Bhav Copy symbol search failed for {query!r}: {e}")
        return []


@app.get("/api/scan/search")
def search_stock(
    symbol: str = Query(..., min_length=1),
    universe: Optional[str] = None,
    portfolio_val: float = 1000000,
    risk_pct: float = 0.01,
):
    """Fetch live data and score a single arbitrary NSE ticker outside the
    curated universes. Same scoring pipeline /api/scan uses per-ticker
    (check_institutional_fortress -> apply_advanced_scoring), so the
    response has the exact same columns as a row from /api/scan — but the
    OHLCV fetch itself goes through get_ohlcv_indmoney_first() (IndMoney/
    INDstocks -> yfinance) instead of get_stock_data()'s Bhav Copy-first
    tiering, per explicit request: this search feature should surface
    IndMoney data specifically, without touching how /api/scan or anything
    else sources data.

    Note: a few columns in apply_advanced_scoring are cross-sectional
    (computed relative to the whole scanned universe, e.g. Sector_RSI_Z,
    RS_Rank) — on this single-row DataFrame they degenerate to a neutral
    value (0 / 100th percentile) rather than being meaningfully comparable
    to a multi-stock scan's values.
    """
    from stock_scanner.pulse import get_current_regime
    from utils.market_data_provider import get_ohlcv_indmoney_first

    ticker = symbol.strip().upper()
    if not ticker:
        raise HTTPException(status_code=400, detail="symbol is required")
    if not ticker.startswith("^") and "." not in ticker:
        ticker = f"{ticker}.NS"

    try:
        regime_data = get_current_regime()
    except Exception as e:
        logger.warning(f"Regime fetch failed for search, defaulting to Range: {e}")
        regime_data = {"Market_Regime": "Range", "Regime_Multiplier": 1.0, "VIX": 20.0}

    hist = get_ohlcv_indmoney_first(ticker, period="1y").dropna()
    if hist.empty or len(hist) < 210:
        raise HTTPException(
            status_code=404,
            detail=(
                f"Not enough market data for '{ticker}' (need at least 210 "
                "trading days). Check the symbol is correct and NSE-listed."
            ),
        )

    result = check_institutional_fortress(
        ticker,
        hist,
        None,
        portfolio_val,
        risk_pct,
        selected_universe=universe,
        regime_data=regime_data,
    )
    if not result:
        raise HTTPException(
            status_code=404,
            detail=(
                f"'{ticker}' did not produce a scoreable result — it may be "
                "illiquid, recently listed, or missing fundamentals data."
            ),
        )

    scoring_config = DEFAULT_SCORING_CONFIG.copy()
    scoring_config["regime"] = regime_data
    score_df = apply_advanced_scoring(pd.DataFrame([result]), scoring_config)
    return _sanitize_json_value(score_df.to_dict(orient="records"))


@app.get("/api/sector-pulse")
def get_sector_pulse(universe: str = "Nifty 50"):
    # Same reasoning as /api/scan above: purely synchronous blocking work,
    # so plain `def` lets FastAPI offload it to a worker thread instead of
    # blocking the event loop.
    # This logic replicates the "Sector Intelligence" from legacy ui.py
    tickers = TICKER_GROUPS.get(universe, [])
    if not tickers:
        raise HTTPException(status_code=404, detail="Universe not found")

    prefetch_metadata(tickers)

    batch_data = get_stock_data(
        tuple(tickers), period="1y", interval="1d", group_by="ticker"
    )
    results = []

    for ticker in tickers:
        try:
            if batch_data.empty:
                hist = get_stock_data(
                    ticker, period="1y", interval="1d", group_by="column"
                ).dropna()
            else:
                hist = (
                    batch_data[ticker].dropna()
                    if len(tickers) > 1 and ticker in batch_data.columns.get_level_values(0)
                    else batch_data.dropna()
                )
            if not hist.empty and len(hist) >= 210:
                res = check_institutional_fortress(
                    ticker, hist, None, 1000000, 0.01, selected_universe=universe
                )
                if res:
                    results.append(res)
        except Exception:
            continue

    if not results:
        return []

    df = pd.DataFrame(results)
    df = apply_advanced_scoring(df)

    if "Sector" not in df.columns or "Velocity" not in df.columns:
        return []

    sector_stats = (
        df.groupby("Sector")
        .agg({"Velocity": "mean", "Above_EMA200": "mean", "Score": "mean"})
        .reset_index()
    )

    sector_stats["Breadth"] = (sector_stats["Above_EMA200"] * 100).round(1)
    sector_stats["Avg_Score"] = sector_stats["Score"].round(1)
    sector_stats["Velocity"] = sector_stats["Velocity"].round(2)

    # Thesis Generation
    def get_thesis(row):
        if row["Score"] > 75 and row["Velocity"] > 0:
            return "🐂 Bullish Accumulation"
        elif row["Score"] < 35 and row["Breadth"] < 40:
            return "❄️ Structural Weakness"
        elif row["Velocity"] > 2:
            return "🚀 High Momentum"
        else:
            return "⚖️ Neutral / Rotation"

    sector_stats["Thesis"] = sector_stats.apply(get_thesis, axis=1)

    # Classification
    def check_rise(row):
        if row["Velocity"] > 0 and row["Breadth"] > 70:
            return "🔥 YES"
        return ""

    def check_fall(row):
        if row["Velocity"] < 0 or row["Breadth"] < 40:
            return "❄️ YES"
        return ""

    sector_stats["On_the_Rise"] = sector_stats.apply(check_rise, axis=1)
    sector_stats["On_the_Fall"] = sector_stats.apply(check_fall, axis=1)

    records = sector_stats.to_dict(orient="records")
    return _sanitize_json_value(records)


@app.get("/api/mf-analysis")
def get_mf_analysis(
    limit: Optional[int] = Query(None),
    force_refresh: bool = Query(
        False,
        description=(
            "Skip the monthly scan cache and run a fresh full discover-and-score "
            "pass. Use sparingly — this hits mfapi.in live for the whole fund "
            "universe. The 'Trigger Job' / Full Recalculation flow is the "
            "normal way to force a refresh."
        ),
    ),
):
    # Same reasoning as /api/scan above: purely synchronous blocking work,
    # so plain `def` lets FastAPI offload it to a worker thread instead of
    # blocking the event loop.
    #
    # The MF universe (hundreds to low thousands of direct-growth schemes)
    # doesn't meaningfully change day to day, so this is a "run once a
    # month" scan, not a "run on every page load" one: check the persisted
    # monthly scan first (mf_scan_results, via fetch_mf_cached_results) and
    # only fall through to a full discover-and-score pass when nothing
    # fresh enough is on file. run_full_mf_scan() already persists its
    # result at the end, so the next request within the freshness window
    # serves from cache instead of re-scanning.
    df = pd.DataFrame() if force_refresh else fetch_mf_cached_results(max_age_days=31)
    cache_hit = not df.empty
    if not cache_hit:
        df = run_full_mf_scan(limit=limit)
    elif limit:
        df = df.head(limit)

    logger.info(
        "mf-analysis: %s (%d funds)",
        "served from monthly cache" if cache_hit else "ran a fresh full scan",
        len(df),
    )

    records = df.replace([float("inf"), float("-inf")], pd.NA).to_dict(orient="records")
    records = _sanitize_json_value(records)

    # ── Phase 5: Enrich with transparent conviction scores (additive, backward-compat) ──
    # Re-run even on cached data: this is cheap (percentile ranking within
    # the current record set, no network), and keeps conviction_score_v2/
    # risk flags/confidence consistent with whatever `records` actually is.
    try:
        from mf_lab.logic import enrich_mf_records_with_conviction
        records = enrich_mf_records_with_conviction(records)
    except Exception as enrich_err:
        logger.warning("MF conviction enrichment skipped: %s", enrich_err)

    return records



@mf_router.post("/trigger-job", status_code=202)
async def trigger_mf_job(req: MFJobRequest, background_tasks: BackgroundTasks):
    """
    Accepts a Mutual Fund processing job and immediately schedules it as a
    background task (HTTP 202 Accepted). The caller (Streamlit) is never blocked.

    Supported job types:
      - 'refresh_nav'
      - 'update_metrics'
      - 'full_refresh'
      - 'recalculate_rankings'
    """
    VALID_JOBS = {
        "refresh_nav",
        "full_refresh",
        "update_metrics",
        "recalculate_rankings",
    }
    if req.job_type not in VALID_JOBS:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown job_type '{req.job_type}'. Valid options: {sorted(VALID_JOBS)}",
        )

    background_tasks.add_task(
        run_mf_background_job,
        job_type=req.job_type,
        force_refresh=req.force_refresh,
        scheme_codes=req.scheme_codes,
    )

    logger.info(f"MF background job queued: {req.job_type} (force={req.force_refresh})")
    return {
        "status": "accepted",
        "job_type": req.job_type,
        "force_refresh": req.force_refresh,
        "scheme_codes": req.scheme_codes or [],
        "message": f"Job '{req.job_type}' is running on the server. Streamlit stays responsive.",
    }


@app.get("/api/commodities")
def get_commodities(force_refresh: bool = Query(False)):
    """Return conviction-scored Gold/Silver/Crude/Copper rows.

    Declared as a plain `def`, not `async def`: build_commodities_frame()
    does synchronous, potentially slow work (up to 9 live yfinance calls —
    USDINR plus global+local OHLCV for each of the 4 commodities — on a
    cache miss). An `async def` route with no real `await` inside runs
    directly on uvicorn's single event loop and freezes request handling
    for the *entire app*, not just this endpoint — the same bug pattern
    already fixed for the stock scanner, sector pulse, MF analysis, REIT/
    InvIT, and US Investing routes (this one was missed at the time). A
    plain `def` route lets FastAPI dispatch it to a worker thread instead.
    """
    df = build_commodities_frame(force_refresh=force_refresh)

    # Persist to scan_history_details so the existing Scan History page
    # (GET /api/history/timestamps + /api/history/data — already used by
    # the stock scanner and MF Lab) also covers commodity scans. The
    # legacy Streamlit UI (commodities/ui.py) already did this
    # (register_scan + save_scan_results); the Next.js-facing endpoint
    # never picked it up, so every commodity scan this app has ever run
    # vanished the moment the response was returned — no way to see how
    # e.g. Gold's spread or conviction score has trended over time.
    if not df.empty:
        try:
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            scan_id = register_scan(
                timestamp, universe="Commodities", scan_type="COMMODITY", status="Completed"
            )
            save_scan_results(scan_id, df, scan_timestamp=timestamp)
        except Exception as e:
            logger.warning("get_commodities: failed to persist scan history: %s", e)

    records = df.to_dict(orient="records")
    return _sanitize_json_value(records)


@app.get("/api/options/expiries")
def get_options_expiries(symbol: str):
    symbol = INDEX_BENCHMARKS.get(symbol, symbol)
    return get_available_expiries(symbol)


@app.get("/api/options/chain")
def get_options_chain(
    symbol: str,
    expiry: str,
    oi_threshold: int = Query(10000, ge=0),
):
    symbol = INDEX_BENCHMARKS.get(symbol, symbol)
    chain_df, spot, _ = fetch_option_chain(symbol, expiry)
    chain_df = chain_df.fillna(0)
    strategies = scan_strategies(chain_df, oi_threshold=oi_threshold)
    return {
        "symbol": symbol,
        "expiry": expiry,
        "spot": spot,
        "chain": _sanitize_json_value(chain_df.to_dict(orient="records")),
        "strategies": _sanitize_json_value(strategies.to_dict(orient="records")),
    }


@app.get("/api/history/timestamps")
def get_history_timestamps():
    """Return scan entries with enough metadata (scan_id, universe,
    scan_type) for the frontend to label each one by section, not just
    by a bare, indistinguishable timestamp."""
    return fetch_scan_history_list()


@app.get("/api/history/data")
def get_history_data(scan_id: int):
    df = fetch_history_data("scan_mf", scan_id=scan_id)
    records = df.to_dict(orient="records") if not df.empty else []
    return _sanitize_json_value(records)


app.include_router(mf_router)
app.include_router(auth_router)
app.include_router(users_router)
app.include_router(orders_router)
app.include_router(brokers_router)
app.include_router(picks_router)
app.include_router(telegram_router)
app.include_router(reit_invits_router)
app.include_router(us_investing_router)
app.include_router(investments_router)
app.include_router(bhavcopy_router)
app.include_router(research_evidence_router)
app.include_router(paper_trading_router)
app.include_router(auto_scan_router)


@app.on_event("startup")
def startup_init_db():
    """Initialize the DB and recover stale queued/running scan jobs."""
    try:
        from utils.db import init_db
        init_db()
        stale_failed = mark_stale_scan_jobs_failed()
        if stale_failed:
            logger.warning("Recovered %d stale scan job(s) on startup.", stale_failed)
        logger.info("Database initialized successfully.")
    except Exception as exc:
        logger.warning(f"Database init skipped: {exc}")


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
