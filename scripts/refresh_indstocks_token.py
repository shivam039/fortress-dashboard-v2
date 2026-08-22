#!/usr/bin/env python3
"""
scripts/refresh_indstocks_token.py
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Standalone script to generate/refresh the INDstocks access token via TOTP.

Reads from env:
    INDSTOCKS_CLIENT_ID   -- your static client ID
    INDSTOCKS_MPIN        -- your account MPIN
    INDSTOCKS_TOTP_SECRET -- base32 setup key from the dashboard QR code

Writes:
    Prints the fresh token and exports INDSTOCKS_TOKEN to the current process.
    Optionally writes to .env.local for persistent use.

Usage (from repo root):
    source .venv/bin/activate
    export INDSTOCKS_CLIENT_ID=<your_client_id>
    export INDSTOCKS_MPIN=<your_mpin>
    export INDSTOCKS_TOTP_SECRET=<your_base32_secret>
    python3 scripts/refresh_indstocks_token.py [--write-env]
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

# Allow running from repo root without installing
sys.path.insert(0, str(Path(__file__).parent.parent / "engine"))


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate a fresh INDstocks access token using TOTP."
    )
    parser.add_argument(
        "--write-env",
        action="store_true",
        help="Write INDSTOCKS_TOKEN=<token> to .env.local in the repo root.",
    )
    parser.add_argument(
        "--env-file",
        default=".env.local",
        help="Path to the env file to write (default: .env.local).",
    )
    args = parser.parse_args()

    # Validate env vars
    missing = [
        k
        for k in ("INDSTOCKS_CLIENT_ID", "INDSTOCKS_MPIN", "INDSTOCKS_TOTP_SECRET")
        if not os.getenv(k, "").strip()
    ]
    if missing:
        print(f"❌ Missing env vars: {', '.join(missing)}", file=sys.stderr)
        print(
            "\nSet them before running:\n"
            "  export INDSTOCKS_CLIENT_ID=<your_client_id>\n"
            "  export INDSTOCKS_MPIN=<your_mpin>\n"
            "  export INDSTOCKS_TOTP_SECRET=<base32_setup_key>",
            file=sys.stderr,
        )
        sys.exit(1)

    try:
        from utils.indstocks_client import _fetch_new_token
    except ImportError as e:
        print(f"❌ Import error: {e}", file=sys.stderr)
        print("Run from repo root with PYTHONPATH set, or activate your venv.", file=sys.stderr)
        sys.exit(1)

    try:
        token = _fetch_new_token()
    except Exception as exc:
        print(f"❌ Token generation failed: {exc}", file=sys.stderr)
        sys.exit(1)

    print(f"✅ Token generated successfully.")
    print(f"\nexport INDSTOCKS_TOKEN={token}\n")

    if args.write_env:
        env_path = Path(args.env_file)
        # Read existing, remove old INDSTOCKS_TOKEN line, add fresh one
        lines = []
        if env_path.exists():
            lines = [
                ln for ln in env_path.read_text().splitlines()
                if not ln.startswith("INDSTOCKS_TOKEN=")
            ]
        lines.append(f"INDSTOCKS_TOKEN={token}")
        env_path.write_text("\n".join(lines) + "\n")
        print(f"✅ Written to {env_path.resolve()}")
        print(f"   Source it with: source {env_path}")


if __name__ == "__main__":
    main()
