import json
import os
import sys
from datetime import datetime

import pandas as pd
import requests

# Adjust path to import from engine root
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from fortress_config import TICKER_GROUPS
from utils.db import (
    _read_df,
    init_db,
    register_scan,
    save_scan_results,
    update_scan_status,
)

TELEGRAM_BOT_TOKEN = os.environ.get(
    "TELEGRAM_BOT_TOKEN", "8586585011:AAHFal_zfoGEtjol86GMI49OKCSlCgvclMA"
)

# Read subscriber list: env var > subscribers file > default
_DEFAULT_CHAT_ID = "677141544,-1003933571318"
_SUBS_FILE = os.path.join(os.path.dirname(__file__), "telegram_subscribers.txt")
if os.environ.get("TELEGRAM_CHAT_ID"):
    TELEGRAM_CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]
elif os.path.exists(_SUBS_FILE):
    with open(_SUBS_FILE, "r") as _f:
        _file_ids = _f.read().strip()
    TELEGRAM_CHAT_ID = _file_ids if _file_ids else _DEFAULT_CHAT_ID
else:
    TELEGRAM_CHAT_ID = _DEFAULT_CHAT_ID


def _clear_stock_market_cache():
    """Clear Streamlit's cached stock downloads before an alert scan."""
    try:
        from stock_scanner.logic import get_stock_data

        clear_cache = getattr(get_stock_data, "clear", None)
        if callable(clear_cache):
            clear_cache()
    except Exception as e:
        print(f"  Could not clear stock data cache: {e}")


def run_fresh_stock_scan(universe: str):
    """Run the stock screener now and return the fresh dataframe + timestamp."""
    from stock_scanner.logic import (
        DEFAULT_SCORING_CONFIG,
        apply_advanced_scoring,
        check_institutional_fortress,
        get_stock_data,
    )
    from stock_scanner.pulse import get_current_regime

    tickers = TICKER_GROUPS.get(universe)
    if not tickers:
        print(f"  Unknown universe: {universe}")
        return None

    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    scan_id = register_scan(
        timestamp, universe=universe, scan_type="STOCK", status="In Progress"
    )

    try:
        try:
            regime_data = get_current_regime()
            print(
                f"  Fresh regime: {regime_data['Market_Regime']} (x{regime_data['Regime_Multiplier']})"
            )
        except Exception as e:
            print(f"  Regime fetch failed, defaulting to Range: {e}")
            regime_data = {
                "Market_Regime": "Range",
                "Regime_Multiplier": 1.0,
                "VIX": 20.0,
            }

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
                        None,
                        1000000,
                        0.01,
                        selected_universe=universe,
                        regime_data=regime_data,
                    )
                    if res:
                        results.append(res)
            except Exception as e:
                print(f"  Error scanning {ticker}: {e}")

        if not results:
            update_scan_status(scan_id, "No Data")
            return {"df": pd.DataFrame(), "timestamp": timestamp, "scan_id": scan_id}

        df = pd.DataFrame(results)
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
        df["Universe"] = universe
        save_scan_results(scan_id, df, scan_timestamp=timestamp)
        update_scan_status(scan_id, "Completed")
        return {"df": df, "timestamp": timestamp, "scan_id": scan_id}
    except Exception as e:
        update_scan_status(scan_id, "Failed")
        print(f"  Fresh stock scan failed for {universe}: {e}")
        return None


def run_fresh_commodity_scan():
    """Run the commodities scanner now and return the fresh dataframe + timestamp."""
    try:
        from commodities.logic import build_commodities_frame

        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        df = build_commodities_frame(force_refresh=True)
        if df.empty:
            return {"df": df, "timestamp": timestamp, "scan_id": None}

        scan_id = register_scan(
            timestamp, universe="Commodities", scan_type="COMMODITY", status="Completed"
        )
        save_scan_results(scan_id, df, scan_timestamp=timestamp)
        return {"df": df, "timestamp": timestamp, "scan_id": scan_id}
    except Exception as e:
        print(f"  Fresh commodity scan failed: {e}")
        return None


def get_latest_scan_for_universe(universe: str):
    """Fetch the latest completed scan for a given universe."""
    query = """
        SELECT scan_id, timestamp 
        FROM scans 
        WHERE universe = :universe AND status = 'Completed' 
        ORDER BY timestamp DESC 
        LIMIT 1
    """
    scan_info = _read_df(query, {"universe": universe})
    if scan_info.empty:
        return None

    scan_id = scan_info.iloc[0]["scan_id"]
    timestamp = scan_info.iloc[0]["timestamp"]

    # Fetch details
    details_query = """
        SELECT raw_data 
        FROM scan_history_details 
        WHERE scan_id = :scan_id
    """
    details = _read_df(details_query, {"scan_id": int(scan_id)})

    if details.empty or "raw_data" not in details.columns:
        return None

    df = pd.json_normalize(
        details["raw_data"].apply(lambda x: x if isinstance(x, dict) else json.loads(x))
    )
    return {"df": df, "timestamp": timestamp}


def format_telegram_message(row):
    """Format a single stock pick using the optimized template."""
    ticker = row.get("Symbol", "UNKNOWN")
    buy_zone = row.get("Buy_Zone", "N/A")
    score_raw = row.get("Score", 0)
    score_out_of_10 = min(10.0, score_raw / 10.0)

    sector = row.get("Sector", "General")
    strategy = row.get("Strategy", "Momentum Pick")

    target_10d = row.get("Target_10D", "N/A")
    tgt_mean = row.get("Tgt_Mean", "N/A")

    # Fallback for Target 2
    if pd.isna(tgt_mean) or tgt_mean == 0 or tgt_mean == "N/A":
        # Estimate Target 2 as slightly higher than Target 1
        if isinstance(target_10d, (int, float)):
            target_2 = round(target_10d * 1.05, 2)
        else:
            target_2 = "N/A"
    else:
        target_2 = tgt_mean

    stop_loss = row.get("Stop_Loss", "N/A")

    msg = f"🚀 STOCK PICK: ${ticker}\n\n"
    msg += "Action: BUY\n"
    msg += f"Entry Range: {buy_zone}\n\n"
    msg += f"Conviction Score: 🔥 {score_out_of_10:.1f}/10\n"
    msg += f"({sector} | {strategy})\n\n"
    msg += "Targets & Risk:\n"
    msg += f"🎯 Target 1: {target_10d}\n"
    msg += f"🎯 Target 2: {target_2}\n"
    msg += f"🛑 Stop Loss: {stop_loss} (Closing basis)\n\n"
    msg += "Timeframe: Swing (5-10 Days)\n"
    msg += "Disclaimer: Not financial advice. Educational purposes only."

    return msg


def send_telegram_message(message: str):
    """Send message via Telegram API to multiple chat IDs."""
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("Skipping Telegram send: TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID not set.")
        return False

    chat_ids = [cid.strip() for cid in TELEGRAM_CHAT_ID.split(",") if cid.strip()]
    success = True

    for chat_id in chat_ids:
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        payload = {"chat_id": chat_id, "text": message, "parse_mode": "HTML"}

        try:
            response = requests.post(url, json=payload, timeout=10)
            response.raise_for_status()
        except Exception as e:
            print(f"Failed to send Telegram message to {chat_id}: {e}")
            if "response" in locals() and response is not None:
                print(f"Response: {response.text}")
            success = False

    return success


def format_commodity_message(row):
    """Format a commodity alert using a rich template."""
    name = row.get("Commodity", "UNKNOWN")
    price = row.get("Price (₹)", 0)
    score = row.get("Conviction Score", 0)
    label = row.get("Conviction Label", "HOLD")
    emoji = row.get("Conviction Emoji", "🟡")
    trend = row.get("Trend", "—")
    atr_regime = row.get("ATR Regime", "—")
    spread = row.get("Spread %", 0)
    ret_1m = row.get("1M Return %", 0)
    ret_3m = row.get("3M Return %", 0)
    ret_6m = row.get("6M Return %", 0)
    decision = row.get("Decision", "")
    usdinr = row.get("USDINR", 84.0)

    msg = f"{emoji} COMMODITY ALERT: {name}\n\n"
    msg += f"Conviction: {score}/100 ({label})\n"
    msg += f"Price: ₹{price:,.2f}\n"
    msg += f"Trend: {trend}\n"
    msg += f"ATR Regime: {atr_regime}\n\n"
    msg += "Returns:\n"
    msg += f"  📊 1M: {ret_1m:+.2f}%\n"
    msg += f"  📊 3M: {ret_3m:+.2f}%\n"
    msg += f"  📊 6M: {ret_6m:+.2f}%\n\n"
    msg += f"Spread vs Global: {spread:+.2f}%\n"
    msg += f"USDINR: {usdinr:.2f}\n\n"
    msg += f"Decision: {decision}\n"
    msg += "Disclaimer: Not financial advice. Educational purposes only."
    return msg


def broadcast_commodities():
    """Run a fresh commodity scan and broadcast alerts."""
    print("Checking Commodities with a fresh scan...")

    scan_data = run_fresh_commodity_scan()
    if not scan_data:
        print("  Could not load fresh commodities.")
        return

    df = scan_data["df"]

    if df.empty:
        print("  No commodity data available.")
        return

    # Ensure Conviction Score column exists
    score_col = "Conviction Score" if "Conviction Score" in df.columns else None
    if not score_col:
        for col in df.columns:
            if "conviction" in col.lower() and "score" in col.lower():
                score_col = col
                break

    if not score_col:
        print("  No conviction score column found.")
        return

    df[score_col] = pd.to_numeric(df[score_col], errors="coerce").fillna(0)
    top_commodities = df.sort_values(score_col, ascending=False)

    if top_commodities.empty:
        print("  No commodities to broadcast.")
        return

    print(f"  Broadcasting {len(top_commodities)} commodities.")

    header_msg = f"🌍 <b>Commodities Intelligence Report</b>\n<i>Fresh scan: {scan_data['timestamp']}</i>"
    send_telegram_message(header_msg)

    for _, row in top_commodities.iterrows():
        msg = format_commodity_message(row)
        success = send_telegram_message(msg)
        if success:
            print(f"  -> Sent {row.get('Commodity')}")
        else:
            print(f"  -> Failed to send {row.get('Commodity')}")


def main():
    print(f"Starting Telegram Bot broadcaster at {datetime.now()}")
    init_db()
    _clear_stock_market_cache()

    # ── Stock Picks ──────────────────────────────────────────────────────
    indices_to_check = [
        "Nifty 50",
        "Nifty Next 50",
        "Nifty Midcap 150",
        "Nifty Smallcap 250",
        "Nifty Microcap 250",
    ]

    for index_name in indices_to_check:
        if index_name not in TICKER_GROUPS:
            continue

        print(f"Checking {index_name} with a fresh scan...")
        scan_data = run_fresh_stock_scan(index_name)

        if not scan_data:
            print(f"  Fresh scan failed for {index_name}.")
            continue

        df = scan_data["df"]
        if df.empty or "Score" not in df.columns:
            print(f"  No valid score data found for {index_name}.")
            continue

        # Filter top picks (Score >= 60)
        df["Score"] = pd.to_numeric(df["Score"], errors="coerce").fillna(0)
        top_picks = df[df["Score"] >= 60].sort_values("Score", ascending=False).head(5)

        if top_picks.empty:
            print(f"  No picks with Score >= 60 for {index_name}.")
            continue

        print(f"  Found {len(top_picks)} top picks for {index_name}.")

        # Add a header for the index
        header_msg = f"📊 <b>Top Picks for {index_name}</b>\n<i>Fresh scan: {scan_data['timestamp']}</i>"
        send_telegram_message(header_msg)

        # Send each pick
        for _, row in top_picks.iterrows():
            msg = format_telegram_message(row)
            success = send_telegram_message(msg)
            if success:
                print(f"  -> Sent {row.get('Symbol')}")
            else:
                print(f"  -> Failed to send {row.get('Symbol')}")

    # ── Commodities ──────────────────────────────────────────────────────
    broadcast_commodities()

    print("Done.")


if __name__ == "__main__":
    main()
