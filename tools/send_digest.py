#!/usr/bin/env python3
"""Headless daily-digest sender, intended to be triggered by Windows Task Scheduler.

The Windows task IS the schedule now (no always-on server required). This builds
today's digest and emails it, with a once-per-day guard so an accidental double
trigger won't send twice. Use --force to send regardless (for testing).

Run from the project root:  python3 tools/send_digest.py [--force]
"""

import argparse
import sys
from datetime import datetime
from pathlib import Path

# Ensure the project root is importable regardless of the caller's cwd.
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from resume_pipeline.core import load_dotenv  # noqa: E402
load_dotenv(ROOT / ".env")

from digest_pipeline import digest, email_send, store  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description="Send today's daily digest by email.")
    ap.add_argument("--force", action="store_true",
                    help="Send even if a digest was already sent today.")
    args = ap.parse_args()

    stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    today = datetime.now().strftime("%Y-%m-%d")
    cfg = store.load_config()

    to = (cfg.get("email_to") or "").strip()
    if not to:
        print(f"[{stamp}] ERROR: no recipient configured (set one in the UI).", file=sys.stderr)
        return 2
    if not email_send.is_configured():
        print(f"[{stamp}] ERROR: SMTP not configured (set SMTP_* in .env).", file=sys.stderr)
        return 2

    # Atomically claim today's send so we never double up with the in-server
    # scheduler (or a second trigger). --force bypasses the claim (for testing).
    if not args.force and not store.claim_send_slot(today):
        print(f"[{stamp}] already handled today ({today}); skipping.")
        return 0

    try:
        built = digest.send_now(cfg)
    except Exception as exc:  # noqa: BLE001 - log and signal failure to Task Scheduler
        if not args.force:
            store.release_send_slot(today)  # allow a retry
        print(f"[{stamp}] ERROR sending digest: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1

    warn = f" | warning: {built['warning']}" if built.get("warning") else ""
    print(f"[{stamp}] sent to {built.get('sent_to')} "
          f"(used_llm={built['used_llm']}, updates={built['update_count']}){warn}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
