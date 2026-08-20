"""
ui/utils/scan.py  —  Scan runner & related helpers
====================================================
Pure-ish helpers for running stock/MF scans and building broker order links.
These call engine modules directly (in-process fallback) when FastAPI is
unreachable, exactly replicating the logic that was previously embedded in
streamlit_app.py.
"""

from __future__ import annotations

import logging
import threading
from typing import Any, Dict, List

import pandas as pd

logger = logging.getLogger("fortress.ui.scan")


# ---------------------------------------------------------------------------
# Universe list — re-exported from ui.utils.api (single cache)
# ---------------------------------------------------------------------------


def fetch_universes(api_url: str) -> List[str]:
    """
    Return scan universe list.

    Delegates to ``ui.utils.api.fetch_universes`` which manages its own
    ``@st.cache_data`` and falls back to local config on failure.
    """
    from ui.utils.api import (  # noqa: PLC0415 — avoid circular at module load
        fetch_universes as _fetch,
    )

    return _fetch()


# ---------------------------------------------------------------------------
# In-process scan fallback
# ---------------------------------------------------------------------------


def run_scan_directly(payload: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    Run the stock scan in-process using engine modules.

    Mirrors the logic in ``engine/main.py POST /api/scan`` so the screener
    works on Streamlit Cloud where no separate FastAPI process is running.
    """
    from fortress_config import TICKER_GROUPS  # type: ignore[import]
    from stock_scanner.logic import (  # type: ignore[import]
        DEFAULT_SCORING_CONFIG,
        apply_advanced_scoring,
        check_institutional_fortress,
        get_stock_data,
    )
    from stock_scanner.pulse import get_current_regime  # type: ignore[import]
    from stock_scanner.ui import generate_action_link  # type: ignore[import]

    universe = payload["universe"]
    tickers = TICKER_GROUPS.get(universe)
    if not tickers:
        raise ValueError(f"Universe '{universe}' not found.")

    try:
        regime_data = get_current_regime()
    except Exception as exc:
        logger.warning("Regime fetch failed, defaulting to Range: %s", exc)
        regime_data = {"Market_Regime": "Range", "Regime_Multiplier": 1.0, "VIX": 20.0}

    batch_data = get_stock_data(tickers, period="1y", interval="1d", group_by="ticker")
    results: List[Dict[str, Any]] = []
    for ticker in tickers:
        try:
            hist = (
                batch_data[ticker].dropna() if len(tickers) > 1 else batch_data.dropna()
            )
            if not hist.empty and len(hist) >= 210:
                res = check_institutional_fortress(
                    ticker,
                    hist,
                    None,
                    payload["portfolio_val"],
                    payload["risk_pct"],
                    selected_universe=universe,
                    regime_data=regime_data,
                )
                if res:
                    results.append(res)
        except Exception as exc:
            logger.warning("Error scanning %s: %s", ticker, exc)

    if not results:
        return []

    df = pd.DataFrame(results)
    scoring_config = DEFAULT_SCORING_CONFIG.copy()
    scoring_config.update(
        {
            "enable_regime": payload.get("enable_regime", True),
            "liquidity_cr_min": payload.get("liquidity_cr_min", 8.0),
            "market_cap_cr_min": payload.get("market_cap_cr_min", 1500.0),
            "price_min": payload.get("price_min", 80.0),
            "regime": regime_data,
        }
    )
    if payload.get("weights"):
        scoring_config["weights"] = payload["weights"]

    df = apply_advanced_scoring(df, scoring_config)
    broker = payload.get("broker", "Zerodha")
    df["Actions"] = df.apply(lambda row: generate_action_link(row, broker), axis=1)
    return df.to_dict(orient="records")


# ---------------------------------------------------------------------------
# In-process MF job runner
# ---------------------------------------------------------------------------


def run_mf_job_directly(payload: Dict[str, Any]) -> None:
    """
    Dispatch an MF job to a background daemon thread.

    Uses threading to keep Streamlit responsive since MF jobs can be heavy.
    """
    from mf_lab.jobs import _run_job_sync  # type: ignore[import]

    def _target() -> None:
        try:
            _run_job_sync(
                job_type=payload["job_type"],
                force_refresh=payload.get("force_refresh", False),
                scheme_codes=payload.get("scheme_codes"),
            )
        except Exception as exc:
            logger.error("In-process MF job failed: %s", exc)

    thread = threading.Thread(target=_target, daemon=True)
    thread.start()


# ---------------------------------------------------------------------------
# Broker order link builder
# ---------------------------------------------------------------------------


def build_order_link(
    symbol: str,
    quantity: float,
    price: float,
    broker_name: str,
) -> str:
    """Return a deep-link URL to the broker's order entry screen, or ''."""
    from utils.broker_mappings import (  # type: ignore[import]
        generate_dhan_url,
        generate_zerodha_url,
    )

    if broker_name == "Dhan":
        return generate_dhan_url(symbol, quantity, price) or ""
    return generate_zerodha_url(symbol, quantity) or ""
