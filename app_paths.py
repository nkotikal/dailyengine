"""Path resolution that works both in development and as a frozen executable.

When packaged with PyInstaller, read-only assets (web/, RESUME_MANIFESTO.md,
samples/) are extracted to ``sys._MEIPASS``, while writable state must live in a
per-user location that survives reinstalls. In development everything stays in
the repo so nothing changes for the existing workflow.

    bundle_dir()  -> read-only assets   (repo root in dev; _MEIPASS when frozen)
    data_dir()    -> writable state     (repo/data in dev; %APPDATA%/DailyDigest when frozen)
    env_path()    -> the .env file to load
"""

import os
import sys
from pathlib import Path

FROZEN = bool(getattr(sys, "frozen", False))
_REPO = Path(__file__).resolve().parent

APP_NAME = "DailyDigest"


def bundle_dir() -> Path:
    """Directory holding read-only, shipped assets."""
    if FROZEN:
        return Path(getattr(sys, "_MEIPASS", _REPO))
    return _REPO


def data_dir() -> Path:
    """Writable per-user data directory (created if missing)."""
    if FROZEN:
        base = (os.environ.get("APPDATA")
                or os.environ.get("XDG_DATA_HOME")
                or str(Path.home() / ".local" / "share"))
        d = Path(base) / APP_NAME
    else:
        d = _REPO / "data"
    d.mkdir(parents=True, exist_ok=True)
    return d


def env_path() -> Path:
    """The .env file to load. In a frozen app, prefer one in the data dir, then one
    next to the executable, so a recipient can drop their .env beside the app."""
    if FROZEN:
        in_data = data_dir() / ".env"
        if in_data.exists():
            return in_data
        beside_exe = Path(sys.executable).resolve().parent / ".env"
        return beside_exe if beside_exe.exists() else in_data
    return _REPO / ".env"
