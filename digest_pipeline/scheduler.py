"""Background scheduler that emails the morning digest when it's due.

A single daemon thread wakes every ``interval`` seconds and asks ``digest`` whether
today's digest should go out yet (respecting the configured send time, the enabled
flag, and whether one was already sent today). It catches up if the machine was
asleep at the exact send time, as long as the server is running later that morning.
"""

import threading
import time
from datetime import datetime

from . import digest

_thread = None
_stop = threading.Event()


def _loop(interval: int):
    while not _stop.wait(interval):
        try:
            # Multi-user: send each user's digest when their own send time is due.
            digest.run_scheduled_for_all_users(datetime.now())
        except Exception:  # noqa: BLE001 - never let the loop die
            pass


def start(interval: int = 30) -> None:
    """Start the scheduler thread once (idempotent)."""
    global _thread
    if _thread and _thread.is_alive():
        return
    _stop.clear()
    _thread = threading.Thread(target=_loop, args=(interval,), daemon=True,
                               name="digest-scheduler")
    _thread.start()


def stop() -> None:
    _stop.set()
