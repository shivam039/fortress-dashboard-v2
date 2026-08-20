"""
Fortress Background Scheduler
==============================
Runs inside the Streamlit process as a daemon thread.
Handles:
  1. Daily Telegram broadcast at 09:45 IST (stocks + commodities)
  2. Self-ping keep-alive to prevent Streamlit Cloud from sleeping
  3. Daily pick outcome evaluation at 16:00 IST (post-market)

This module is designed to be started ONCE per Streamlit process
(guarded by a module-level flag) so it survives Streamlit re-runs.
"""

import logging
import os
import threading
import time
from datetime import datetime, timedelta

import pytz
import requests

logger = logging.getLogger("fortress.scheduler")
logger.setLevel(logging.INFO)
if not logger.handlers:
    _h = logging.StreamHandler()
    _h.setFormatter(
        logging.Formatter("[%(asctime)s] %(name)s %(levelname)s: %(message)s")
    )
    logger.addHandler(_h)

IST = pytz.timezone("Asia/Kolkata")

# ── Configuration ────────────────────────────────────────────────────────────
BROADCAST_HOUR = int(os.environ.get("FORTRESS_BROADCAST_HOUR", "9"))
BROADCAST_MINUTE = int(os.environ.get("FORTRESS_BROADCAST_MINUTE", "45"))
EVALUATION_HOUR = int(os.environ.get("FORTRESS_EVALUATION_HOUR", "16"))
EVALUATION_MINUTE = int(os.environ.get("FORTRESS_EVALUATION_MINUTE", "0"))
KEEPALIVE_INTERVAL_SEC = int(
    os.environ.get("FORTRESS_KEEPALIVE_INTERVAL", "60")
)  # 1 min

# Module-level guard: ensures we only start one scheduler per Python process.
_scheduler_started = False
_lock = threading.Lock()


def _seconds_until_next_broadcast() -> float:
    """Calculate seconds until the next 09:45 IST broadcast window."""
    now = datetime.now(IST)
    target = now.replace(
        hour=BROADCAST_HOUR, minute=BROADCAST_MINUTE, second=0, microsecond=0
    )
    if now >= target:
        # Already past today's window — schedule for tomorrow
        target += timedelta(days=1)
    delta = (target - now).total_seconds()
    return max(delta, 0)


def _run_telegram_broadcast():
    """Execute the Telegram broadcast (stocks + commodities)."""
    import sys

    engine_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    scripts_dir = os.path.abspath(os.path.dirname(__file__))
    for p in (engine_dir, scripts_dir):
        if p not in sys.path:
            sys.path.insert(0, p)

    try:
        from telegram_bot import main as telegram_main

        logger.info("🚀 Starting scheduled Telegram broadcast...")
        telegram_main()
        logger.info("✅ Telegram broadcast completed.")
    except Exception:
        logger.exception("❌ Telegram broadcast failed")


def _broadcast_loop():
    """Infinite loop: sleep until 09:45 IST, run broadcast, repeat."""
    while True:
        wait = _seconds_until_next_broadcast()
        next_run = datetime.now(IST) + timedelta(seconds=wait)
        logger.info(
            f"📅 Next Telegram broadcast at {next_run.strftime('%Y-%m-%d %H:%M IST')} "
            f"(in {wait/3600:.1f}h)"
        )
        time.sleep(wait)
        # Double-check we're in the right window (guards against clock drift)
        now = datetime.now(IST)
        if now.hour == BROADCAST_HOUR and abs(now.minute - BROADCAST_MINUTE) <= 2:
            _run_telegram_broadcast()
        else:
            logger.warning(
                f"⏰ Woke up at {now.strftime('%H:%M')} IST — outside broadcast window, skipping."
            )
        # Small sleep to avoid re-triggering within the same minute
        time.sleep(120)


def _seconds_until_next_evaluation() -> float:
    """Calculate seconds until the next 16:00 IST evaluation window."""
    now = datetime.now(IST)
    target = now.replace(
        hour=EVALUATION_HOUR, minute=EVALUATION_MINUTE, second=0, microsecond=0
    )
    if now >= target:
        target += timedelta(days=1)
    delta = (target - now).total_seconds()
    return max(delta, 0)


def _run_pick_evaluation():
    """Evaluate all open picks against current market prices."""
    import sys

    engine_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    scripts_dir = os.path.abspath(os.path.dirname(__file__))
    for p in (engine_dir, scripts_dir):
        if p not in sys.path:
            sys.path.insert(0, p)

    try:
        from pick_tracker import evaluate_open_picks

        logger.info("📊 Starting scheduled pick evaluation...")
        stats = evaluate_open_picks()
        logger.info(f"✅ Pick evaluation done: {stats}")
    except Exception:
        logger.exception("❌ Pick evaluation failed")


def _evaluation_loop():
    """Infinite loop: sleep until 16:00 IST, evaluate picks, repeat."""
    while True:
        wait = _seconds_until_next_evaluation()
        next_run = datetime.now(IST) + timedelta(seconds=wait)
        logger.info(
            f"📊 Next pick evaluation at {next_run.strftime('%Y-%m-%d %H:%M IST')} "
            f"(in {wait/3600:.1f}h)"
        )
        time.sleep(wait)
        now = datetime.now(IST)
        if now.hour == EVALUATION_HOUR and abs(now.minute - EVALUATION_MINUTE) <= 2:
            _run_pick_evaluation()
        else:
            logger.warning(
                f"⏰ Woke up at {now.strftime('%H:%M')} IST — outside evaluation window, skipping."
            )
        time.sleep(120)


def _keepalive_loop():
    """Ping the Streamlit app URL periodically to prevent Streamlit Cloud sleep."""
    # Streamlit Cloud sets STREAMLIT_SERVER_ADDRESS or the app URL is predictable.
    # We also try the common Streamlit Cloud URL pattern.
    app_url = os.environ.get("FORTRESS_APP_URL", "").strip()
    if not app_url:
        # Try constructing from Streamlit Cloud environment
        # Streamlit Cloud exposes STREAMLIT_SHARING_APP_URL in some configurations
        app_url = os.environ.get("STREAMLIT_SHARING_APP_URL", "").strip()
    if not app_url:
        # Fallback: try localhost (works in dev, harmless on cloud)
        app_url = "http://localhost:8501"

    # Also try an external pinger service as backup
    health_url = f"{app_url.rstrip('/')}/_stcore/health"

    while True:
        time.sleep(KEEPALIVE_INTERVAL_SEC)
        try:
            resp = requests.get(health_url, timeout=10)
            logger.debug(f"💓 Keep-alive ping: {resp.status_code}")
        except Exception:
            # Fallback: try the root URL
            try:
                resp = requests.get(app_url, timeout=10)
                logger.debug(f"💓 Keep-alive ping (root): {resp.status_code}")
            except Exception:
                logger.debug(
                    "💓 Keep-alive ping failed (expected in some environments)"
                )


def start_scheduler():
    """Start the background scheduler threads (idempotent — safe to call multiple times)."""
    global _scheduler_started
    with _lock:
        if _scheduler_started:
            return False  # Already running
        _scheduler_started = True

    logger.info("🔧 Starting Fortress background scheduler...")

    # Thread 1: Telegram broadcast at 09:45 IST
    broadcast_thread = threading.Thread(
        target=_broadcast_loop,
        name="fortress-broadcast",
        daemon=True,
    )
    broadcast_thread.start()

    # Thread 2: Keep-alive pinger
    keepalive_thread = threading.Thread(
        target=_keepalive_loop,
        name="fortress-keepalive",
        daemon=True,
    )
    keepalive_thread.start()

    # Thread 3: Pick outcome evaluation at 16:00 IST
    evaluation_thread = threading.Thread(
        target=_evaluation_loop,
        name="fortress-pick-eval",
        daemon=True,
    )
    evaluation_thread.start()

    logger.info(
        f"✅ Scheduler active — broadcast at {BROADCAST_HOUR:02d}:{BROADCAST_MINUTE:02d} IST, "
        f"pick eval at {EVALUATION_HOUR:02d}:{EVALUATION_MINUTE:02d} IST, "
        f"keep-alive every {KEEPALIVE_INTERVAL_SEC}s"
    )
    return True
