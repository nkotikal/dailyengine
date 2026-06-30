#!/usr/bin/env bash
# Launch the Daily Digest / ResumeForge server and keep it alive.
# - Single instance: exits immediately if a server.py is already running.
# - Auto-restart: relaunches a few seconds after any crash.
# Logs to data/digest/server.log. Invoked at Windows logon via a hidden VBS +
# Task Scheduler (see tools/install_startup_task.ps1).

PROJECT="/mnt/c/Users/nkotikal/Desktop/bldr"

# Already running? Do nothing (avoids double-binding port 8000).
if pgrep -f "[s]erver.py" >/dev/null 2>&1; then
  exit 0
fi

cd "$PROJECT" || exit 1
mkdir -p data/digest

while true; do
  echo "[$(date '+%Y-%m-%d %H:%M:%S')] starting server" >> data/digest/server.log 2>&1
  python3 server.py >> data/digest/server.log 2>&1
  echo "[$(date '+%Y-%m-%d %H:%M:%S')] server exited; restarting in 5s" >> data/digest/server.log 2>&1
  sleep 5
done
