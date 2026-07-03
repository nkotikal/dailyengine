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

import app_paths  # noqa: E402
from resume_pipeline.core import load_dotenv  # noqa: E402
load_dotenv(app_paths.env_path())

from digest_pipeline import digest, email_send  # noqa: E402
import user_context  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description="Send the daily digest by email (all users).")
    ap.add_argument("--force", action="store_true",
                    help="Send every enabled user now, ignoring send-time / already-sent guards.")
    args = ap.parse_args()

    stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    if not email_send.is_configured():
        print(f"[{stamp}] ERROR: SMTP not configured (set SMTP_* in .env).", file=sys.stderr)
        return 2

    # Multi-user: each user has isolated data + their own recipient/send time.
    # --force sends every enabled user immediately; otherwise only those due now
    # are sent (the in-server scheduler also covers exact per-user send times).
    when = datetime.now()
    if args.force:
        results = digest.force_send_for_all_users(when)
    else:
        results = digest.run_scheduled_for_all_users(when)

    sent = 0
    for r in results:
        who = r.get("name") or r.get("user")
        if r.get("sent"):
            sent += 1
            print(f"[{stamp}] sent to {r.get('to', '')} for {who}.")
        else:
            print(f"[{stamp}] {who}: {r.get('reason', 'not sent')}")
    print(f"[{stamp}] done: {sent} digest(s) sent.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
