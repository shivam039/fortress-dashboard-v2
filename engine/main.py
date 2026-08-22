# engine/main.py
# AI agents modifying this file: see /AI_AGENT_PROTOCOL.md — log every change
# via engine/utils/ai_audit.py:log_ai_change().
import os
import sys
from typing import Dict, List, Optional

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

from commodities.logic import build_commodities_frame
from fortress_config import TICKER_GROUPS
from mf_lab.jobs import run_mf_background_job
from mf_lab.logic import run_full_mf_scan
from stock_scanner.logic import (
    DEFAULT_SCORING_CONFIG,
    apply_advanced_scoring,
    check_institutional_fortress,
    get_stock_data,
    prefetch_metadata,
)
from options_algo.logic import fetch_option_chain, get_available_expiries, scan_strategies
from fortress_config import INDEX_BENCHMARKS
from utils.broker_mappings import generate_dhan_url, generate_zerodha_url
from utils.db import (
    fetch_history_data,
    fetch_mf_cached_results,
    fetch_timestamps,
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

# API key auth — set FORTRESS_API_KEY env var to enable. Unset = local dev (no auth).
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


app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        origin.strip()
        for origin in os.environ.get(
            "FORTRESS_CORS_ORIGINS",
            "http://localhost:3000,http://127.0.0.1:3000",
        ).split(",")
        if origin.strip()
    ],
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


@app.post("/api/scan")
def run_scan(req: ScanRequest):
    # Plain `def`, not `async def`: everything in this handler (INDstocks/
    # yfinance network calls, pandas/pandas_ta scoring) is synchronous
    # blocking work. Declaring it `async def` with no `await` inside would
    # run it directly on uvicorn's single event-loop thread, freezing the
    # ENTIRE server — including unrelated requests like /api/health and the
    # frontend's status polling — for the whole scan duration, which is
    # exactly why a slow scan can look like the whole app hung rather than
    # just "still scanning". A plain `def` route is run by FastAPI in its
    # threadpool instead, so the event loop stays free to serve other
    # requests concurrently while a scan is in flight.
    from stock_scanner.pulse import get_current_regime

    tickers = TICKER_GROUPS.get(req.universe)
    if not tickers:
        raise HTTPException(status_code=404, detail="Universe not found")

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
    # universe from the DB cache in one call, so tickers with a fresh-enough
    # cached entry skip a live yfinance .info/.news/.calendar/.earnings_dates
    # call in the loop below entirely. This doesn't change *where* that data
    # ultimately comes from (INDstocks has no fundamentals/news endpoint —
    # it always was and still is yfinance) but it cuts how often the loop
    # actually has to hit yfinance live, and previously wasn't wired up here
    # at all (only the legacy Streamlit UI did this).
    prefetch_metadata(tickers)

    # Keep the existing yfinance-based implementation, but make it resilient:
    # if the bulk download fails or returns partial data, fall back to per-symbol
    # fetches so one bad ticker does not fail the entire scan.
    batch_data = get_stock_data(
        tuple(tickers), period="1y", interval="1d", group_by="ticker"
    )
    if batch_data.empty:
        logger.warning("Bulk market data fetch returned no rows for %s", req.universe)

    for ticker in tickers:
        scan_attempted += 1
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
                    ticker,
                    hist,
                    None,
                    req.portfolio_val,
                    req.risk_pct,
                    selected_universe=req.universe,
                    regime_data=regime_data,  # ← live regime passed
                )
                if res:
                    results.append(res)
        except Exception as e:
            logger.warning(f"Error scanning {ticker}: {e}")
            scan_failed += 1

            if (
                scan_attempted >= _BREAKER_MIN_SAMPLE
                and (scan_failed / scan_attempted) >= _BREAKER_FAILURE_RATE
            ):
                logger.error(
                    "run_scan: circuit breaker tripped for universe=%s — "
                    "%d/%d tickers failed (>=%.0f%% failure rate); aborting "
                    "the remaining %d tickers instead of grinding through a "
                    "likely provider outage",
                    req.universe,
                    scan_failed,
                    scan_attempted,
                    _BREAKER_FAILURE_RATE * 100,
                    len(tickers) - scan_attempted,
                )
                circuit_breaker_tripped = True
                break

    def _score_results(raw_results):
        """Shared scoring step for both the normal path and the
        circuit-breaker-tripped-with-partial-results path."""
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
        score_df = apply_advanced_scoring(score_df, scoring_config)
        return score_df.to_dict(orient="records")

    if circuit_breaker_tripped:
        # Score whatever partial results came through before the breaker
        # tripped (may be zero) rather than discarding them, but always use
        # the "aborted early" summary so a real provider outage is never
        # confused with "nothing matched the screen" (asArray() on the
        # frontend already handles a {results: [...]} dict same as a bare
        # list, so this doesn't change how existing successful scans render).
        return {
            "results": _sanitize_json_value(_score_results(results)) if results else [],
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
        return {
            "results": [],
            "summary": "No tickers met criteria or market data was unavailable.",
            "scanned": scan_attempted,
            "failed": scan_failed,
            "circuit_breaker_tripped": False,
        }

    # Generate action links
    return _sanitize_json_value(_score_results(results))


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
async def get_commodities():
    df = build_commodities_frame()
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
    return fetch_timestamps()


@app.get("/api/history/data")
def get_history_data(timestamp: str, scan_type: Optional[str] = None):
    df = fetch_history_data("scan_mf", timestamp, scan_type=scan_type)
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


@app.on_event("startup")
def startup_init_db():
    """Initialize database tables on startup."""
    try:
        from utils.db import init_db
        init_db()
        logger.info("Database initialized successfully.")
    except Exception as exc:
        logger.warning(f"Database init skipped: {exc}")


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
