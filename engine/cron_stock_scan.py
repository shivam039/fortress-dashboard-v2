import os
import sys
from datetime import datetime

import pandas as pd

# Add current directory to path
sys.path.append(os.getcwd())

# Services
from fortress_config import TICKER_GROUPS
from stock_scanner.logic import (
    DEFAULT_SCORING_CONFIG,
    apply_advanced_scoring,
    check_institutional_fortress,
    get_stock_data,
)
from stock_scanner.pulse import get_current_regime
from utils.db import (
    get_db_backend,
    init_db,
    log_audit,
    register_scan,
    save_scan_results,
    update_scan_status,
)

LOCK_FILE = "/tmp/fortress_stock_scan.lock"


def run_weekday_stock_scan():
    """Run automated stock scans for all universes at 7:00 AM weekdays."""

    # 1. Concurrency Lock
    if os.path.exists(LOCK_FILE):
        print("Stock scan already running (Lock file exists). Exiting.")
        return

    try:
        open(LOCK_FILE, "w").close()

        start_time = datetime.now()
        timestamp = start_time.strftime("%Y-%m-%d %H:%M:%S")
        print(f"Starting Fortress Stock Scan at {timestamp}...")

        # Init DB (ensure tables exist)
        init_db()
        print(f"DB backend: {get_db_backend()}")

        # Fetch live regime once for all scans
        try:
            regime_data = get_current_regime()
            print(
                f"Regime: {regime_data['Market_Regime']} (x{regime_data['Regime_Multiplier']})"
            )
        except Exception as e:
            print(f"Regime fetch failed, defaulting: {e}")
            regime_data = {
                "Market_Regime": "Range",
                "Regime_Multiplier": 1.0,
                "VIX": 20.0,
            }

        # 2. Scan each universe
        for universe, tickers in TICKER_GROUPS.items():
            print(f"Scanning universe: {universe} ({len(tickers)} tickers)")

            # Register Scan per universe
            scan_id = register_scan(
                timestamp, universe=universe, scan_type="STOCK", status="In Progress"
            )

            try:
                # Batch fetch data
                batch_data = get_stock_data(
                    tickers, period="1y", interval="1d", group_by="ticker"
                )

                results = []
                for ticker in tickers:
                    try:
                        hist = (
                            batch_data[ticker].dropna()
                            if len(tickers) > 1
                            else batch_data.dropna()
                        )
                        if not hist.empty and len(hist) >= 210:
                            res = check_institutional_fortress(
                                ticker,
                                hist,
                                None,  # No ticker_obj for automation
                                1000000,  # Default portfolio
                                0.01,  # Default risk
                                selected_universe=universe,
                                regime_data=regime_data,
                            )
                            if res:
                                results.append(res)
                    except Exception as e:
                        print(f"Error scanning {ticker}: {e}")

                if results:
                    df = pd.DataFrame(results)

                    # Apply advanced scoring
                    scoring_config = DEFAULT_SCORING_CONFIG.copy()
                    scoring_config.update(
                        {
                            "enable_regime": True,
                            "liquidity_cr_min": 8.0,
                            "market_cap_cr_min": 1500.0,
                            "price_min": 80.0,
                            "regime": regime_data,
                        }
                    )
                    df = apply_advanced_scoring(df, scoring_config)

                    # Save results
                    save_scan_results(scan_id, df, scan_timestamp=timestamp)
                    update_scan_status(scan_id, "Completed")

                    print(f"Completed {universe}: {len(df)} results saved.")
                else:
                    update_scan_status(scan_id, "No Data")
                    print(f"No results for {universe}.")

            except Exception as e:
                update_scan_status(scan_id, "Failed")
                print(f"Failed scanning {universe}: {e}")

        # Cleanup
        log_audit(
            "Stock Scan Completed", "All Universes", f"Automated scan at {timestamp}"
        )
        print(f"Stock scan completed at {datetime.now()}")

    finally:
        # Remove lock file
        if os.path.exists(LOCK_FILE):
            os.remove(LOCK_FILE)


if __name__ == "__main__":
    run_weekday_stock_scan()
