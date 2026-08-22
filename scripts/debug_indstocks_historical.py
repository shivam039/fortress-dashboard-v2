#!/usr/bin/env python3
"""Diagnostic: probe INDstocks' /market/historical/{interval} endpoint directly.

Round 1 of this script (batches of 1/2/5/10/49 scrip codes) showed batching
itself works fine — 1, 2, and 5 scrip codes all returned 200 OK — but a batch
of 10 came back `{"debug_info":"Invalid scrip codes","message":"Bad Request"}`.
That means INDstocks is rejecting one or more *specific* scrip codes in that
batch, not the batch size. This round tests every symbol individually (each
already confirmed to work fine solo, at n=1) and reports which ones actually
fail, so we can see exactly which tickers `get_scrip_code()` is resolving to
a bad security ID for.

Usage (from the repo root, with your venv active and INDSTOCKS_TOKEN set —
same env as running the server):

    python3 scripts/debug_indstocks_historical.py

Nothing here is written anywhere or sent anywhere except to INDstocks' API
using your own token; this only prints to your terminal.
"""

from __future__ import annotations

import os
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

# Make `engine` importable when run as `python3 scripts/debug_indstocks_historical.py`
# from the repo root (same layout engine/main.py itself relies on).
_REPO_ROOT = Path(__file__).resolve().parent.parent
_ENGINE_DIR = _REPO_ROOT / "engine"
sys.path.insert(0, str(_ENGINE_DIR))
sys.path.insert(0, str(_REPO_ROOT))

BASE_URL = "https://api.indstocks.com"


def _get_token() -> str:
    token = os.environ.get("INDSTOCKS_TOKEN", "").strip()
    if token:
        return token
    # Fall back to generating one via TOTP if that's what's configured instead.
    try:
        from utils.indstocks_client import get_client

        return get_client()._token  # noqa: SLF001 -- diagnostic script, deliberate
    except Exception as exc:
        print(f"Could not resolve a token: {exc}")
        sys.exit(1)


def _sample_symbol_scrip_pairs(n: int) -> list[tuple[str, str]]:
    """Pull (ticker, scrip_code) pairs for the first n Nifty 50 tickers that
    resolve via the instruments cache."""
    from fortress_config import TICKER_GROUPS
    from utils.instruments_cache import get_instruments_cache

    cache = get_instruments_cache()
    pairs = []
    for sym in TICKER_GROUPS["Nifty 50"]:
        scrip = cache.get_scrip_code(sym)
        if scrip:
            pairs.append((sym, scrip))
        if len(pairs) >= n:
            break
    return pairs


def probe(token: str, scrip_codes: list[str]) -> tuple[int, str]:
    now = datetime.now(tz=timezone.utc)
    start = now - timedelta(days=30)  # short range is enough to test shape/limits
    params = {
        "scrip-codes": ",".join(scrip_codes),
        "start_time": int(start.timestamp() * 1000),
        "end_time": int(now.timestamp() * 1000),
    }
    resp = requests.get(
        f"{BASE_URL}/market/historical/1day",
        headers={"Authorization": token, "Content-Type": "application/json"},
        params=params,
        timeout=15,
    )
    return resp.status_code, resp.text[:300]


def find_max_batch_size(token: str, codes: list[str], hi_cap: int) -> int:
    """Binary-search the largest N (1..hi_cap) for which an N-code batch
    request succeeds. Assumes success is monotonic in N (true if this is a
    hard count cap rather than a specific-code issue — already confirmed
    above, since every code passes individually)."""
    lo, hi = 1, min(hi_cap, len(codes))
    best = 0
    while lo <= hi:
        mid = (lo + hi) // 2
        status, body = probe(token, codes[:mid])
        ok = status == 200
        print(f"  batch of {mid:<3} -> HTTP {status} {'' if ok else body}")
        time.sleep(0.25)
        if ok:
            best = mid
            lo = mid + 1
        else:
            hi = mid - 1
    return best


def main() -> None:
    token = _get_token()
    pairs = _sample_symbol_scrip_pairs(49)
    codes = [scrip for _sym, scrip in pairs]
    print(f"Resolved {len(pairs)} (ticker, scrip_code) pairs from Nifty 50.\n")

    print("Step 1: testing each symbol individually (isolates a bad ID, if any):\n")
    bad = []
    for sym, scrip in pairs:
        status, body = probe(token, [scrip])
        ok = status == 200
        marker = "OK  " if ok else "FAIL"
        print(f"[{marker}] {sym:<16} -> {scrip:<12} HTTP {status}  {'' if ok else body}")
        if not ok:
            bad.append((sym, scrip, status, body))
        time.sleep(0.25)  # stay well under the 5 req/s data API limit

    print(f"\n{'=' * 70}")
    if bad:
        print(f"{len(bad)} of {len(pairs)} symbols FAILED individually:")
        for sym, scrip, status, body in bad:
            print(f"  {sym} -> {scrip}: HTTP {status} {body}")
        return

    print("All symbols passed individually — not a bad ID. Since 5-symbol")
    print("batches worked and 10-symbol batches didn't, this looks like a hard")
    print("cap on batch size. Binary-searching the exact max (1..49):\n")
    max_ok = find_max_batch_size(token, codes, hi_cap=49)
    print(f"\n{'=' * 70}")
    print(f"Largest working batch size: {max_ok} scrip codes per /market/historical call.")


if __name__ == "__main__":
    main()
