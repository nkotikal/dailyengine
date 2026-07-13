#!/usr/bin/env python3
"""Single entry point for the packaged Daily Digest app.

    DailyDigest                     start the local web UI + morning scheduler
    DailyDigest --send              send any DUE digests now (the daily task uses this)
    DailyDigest --send --force      send every enabled user's digest now (testing)

In development you can still run ``python3 server.py`` directly; this file is the
target PyInstaller freezes into ``DailyDigest.exe``.
"""

import sys

import app_paths
from resume_pipeline.core import load_dotenv


def _send(force: bool) -> int:
    from datetime import datetime
    from digest_pipeline import checkins, digest, email_send
    stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    if not email_send.is_configured():
        print(f"[{stamp}] ERROR: SMTP not configured (.env).", file=sys.stderr)
        return 2
    when = datetime.now()
    results = (digest.force_send_for_all_users(when) if force
               else digest.run_scheduled_for_all_users(when))
    sent = 0
    for r in results:
        who = r.get("name") or r.get("user")
        if r.get("sent"):
            sent += 1
            print(f"[{stamp}] sent to {r.get('to', '')} for {who}.")
        else:
            print(f"[{stamp}] {who}: {r.get('reason', 'not sent')}")
    print(f"[{stamp}] done: {sent} digest(s) sent.")

    # Also dispatch due check-ins + the recap (opt-in, due-time gated, de-duped).
    try:
        inter = checkins.run_interactivity_for_all_users(when)
        ci = sum(x["checkins"].get("sent", 0) for x in inter)
        rc = sum(x["recap"].get("sent", 0) for x in inter)
        if ci or rc:
            print(f"[{stamp}] check-ins sent: {ci}, recaps sent: {rc}.")
    except Exception as exc:  # noqa: BLE001
        print(f"[{stamp}] interactivity error: {exc}", file=sys.stderr)
    return 0


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv

    # A windowed .exe has no console, so tee output to a log file users can inspect.
    if app_paths.FROZEN:
        try:
            logf = open(app_paths.data_dir() / "app.log", "a", buffering=1, encoding="utf-8")
            sys.stdout = logf
            sys.stderr = logf
        except OSError:
            pass

    load_dotenv(app_paths.env_path())

    if "--send" in argv:
        return _send(force="--force" in argv)

    # Default: run the web UI. Open a browser automatically in the packaged app.
    if app_paths.FROZEN:
        import threading
        import webbrowser
        threading.Timer(1.8, lambda: webbrowser.open("http://127.0.0.1:8765")).start()

    from server import main as server_main
    return server_main([])


if __name__ == "__main__":
    raise SystemExit(main())
