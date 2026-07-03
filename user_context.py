"""Per-user data isolation + active-user switching (stdlib only).

Every user gets a fully isolated data tree so no profiles, memories, tasks, or
settings can ever overlap:

    data/users/<id>/digest/...      daily-digest engine (config, memory, tasks, ...)
    data/users/<id>/profile.json    resume profile
    data/users/<id>/optimized.json  last optimized resume draft
    data/users/<id>/context.txt     resume context/notes
    data/users/<id>/profiles/       resume version archive

A registry at ``data/users.json`` holds the user list and the globally *active*
user. Most code is user-agnostic: it calls ``digest_dir()`` / ``resume_dir()``,
which resolve to the **current** user. HTTP requests operate on the active user;
the scheduler and headless sender temporarily switch the thread-local current
user (via ``using_user``) to process each user in turn.

The first time this runs on a pre-multi-user install, any existing files under
``data/`` are migrated into a ``default`` user so nothing is lost.
"""

import json
import re
import shutil
import threading
import time
from pathlib import Path

import app_paths

ROOT = Path(__file__).resolve().parent
DATA_ROOT = app_paths.data_dir()   # repo/data in dev; %APPDATA%/DailyDigest when frozen
USERS_ROOT = DATA_ROOT / "users"
REGISTRY_PATH = DATA_ROOT / "users.json"

_LOCK = threading.RLock()
_local = threading.local()


def _read_json(path: Path, default):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def _write_json(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, indent=2, ensure_ascii=False)
    tmp.replace(path)


def _slugify(name: str) -> str:
    base = re.sub(r"[^a-z0-9]+", "-", (name or "").strip().lower()).strip("-")
    return base or "user"


# --- registry --------------------------------------------------------------

def _load_registry() -> dict:
    reg = _read_json(REGISTRY_PATH, {})
    if not isinstance(reg, dict):
        reg = {}
    users = reg.get("users")
    if not isinstance(users, list):
        users = []
    reg["users"] = [u for u in users if isinstance(u, dict) and u.get("id")]
    reg.setdefault("active", "")
    return reg


def _save_registry(reg: dict) -> None:
    _write_json(REGISTRY_PATH, reg)


def _unique_id(reg: dict, base: str) -> str:
    existing = {u["id"] for u in reg["users"]}
    if base not in existing:
        return base
    i = 2
    while f"{base}-{i}" in existing:
        i += 1
    return f"{base}-{i}"


# --- one-time migration of a pre-multi-user install ------------------------

def _legacy_data_exists() -> bool:
    return (DATA_ROOT / "digest").is_dir() or (DATA_ROOT / "profile.json").exists()


def _move(src: Path, dst: Path) -> None:
    """Move src->dst, never clobbering existing data. Falls back to copy+remove
    so a directory with an open handle (e.g. a running server's log) can't block
    the migration of the actual data files."""
    try:
        if not src.exists() or dst.exists():
            return
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(src), str(dst))
    except OSError:
        try:
            if src.is_dir():
                shutil.copytree(str(src), str(dst), dirs_exist_ok=True)
                shutil.rmtree(str(src), ignore_errors=True)
            else:
                shutil.copy2(str(src), str(dst))
                src.unlink()
        except OSError:
            pass  # leave the original in place; nothing is lost


def _migrate_legacy_into(uid: str) -> None:
    """Move pre-multi-user files into a user's folder (best-effort, no data loss).

    Digest data files are moved individually (skipping transient logs and lock
    files) so a running server holding a log open can't block the migration.
    """
    dest = USERS_ROOT / uid
    (dest / "digest").mkdir(parents=True, exist_ok=True)

    legacy_digest = DATA_ROOT / "digest"
    if legacy_digest.is_dir():
        for src in legacy_digest.iterdir():
            if src.suffix in (".json", ".txt"):   # data only; not .log / .lock
                _move(src, dest / "digest" / src.name)

    for name in ("profile.json", "optimized.json", "context.txt"):
        _move(DATA_ROOT / name, dest / name)
    _move(DATA_ROOT / "profiles", dest / "profiles")


def _ensure_initialized() -> dict:
    with _LOCK:
        reg = _load_registry()
        if reg["users"]:
            ids = {u["id"] for u in reg["users"]}
            if not reg.get("active") or reg["active"] not in ids:
                reg["active"] = reg["users"][0]["id"]
                _save_registry(reg)
            return reg

        # No users yet -> create the default user, migrating any legacy data in.
        uid, name = "default", "Me"
        legacy_profile = _read_json(DATA_ROOT / "profile.json", None)
        if isinstance(legacy_profile, dict):
            contact = legacy_profile.get("contact") or {}
            if isinstance(contact, dict) and str(contact.get("name") or "").strip():
                name = str(contact["name"]).strip()
        if _legacy_data_exists():
            _migrate_legacy_into(uid)
        else:
            (USERS_ROOT / uid).mkdir(parents=True, exist_ok=True)
        reg["users"] = [{"id": uid, "name": name,
                         "created_at": time.strftime("%Y-%m-%d %H:%M:%S")}]
        reg["active"] = uid
        _save_registry(reg)
        return reg


# --- public registry API ---------------------------------------------------

def list_users() -> list:
    return _ensure_initialized()["users"]


def get_active() -> str:
    return _ensure_initialized()["active"]


def active_user() -> dict:
    reg = _ensure_initialized()
    for u in reg["users"]:
        if u["id"] == reg["active"]:
            return u
    return reg["users"][0]


def set_active(uid: str) -> str:
    with _LOCK:
        reg = _ensure_initialized()
        if uid not in {u["id"] for u in reg["users"]}:
            raise ValueError(f"Unknown user: {uid}")
        reg["active"] = uid
        _save_registry(reg)
        return uid


def create_user(name: str) -> dict:
    with _LOCK:
        reg = _ensure_initialized()
        uid = _unique_id(reg, _slugify(name))
        user = {"id": uid, "name": (name or "").strip() or uid,
                "created_at": time.strftime("%Y-%m-%d %H:%M:%S")}
        reg["users"].append(user)
        reg["active"] = uid
        _save_registry(reg)
        (USERS_ROOT / uid).mkdir(parents=True, exist_ok=True)
        return user


def rename_user(uid: str, name: str) -> bool:
    with _LOCK:
        reg = _ensure_initialized()
        for u in reg["users"]:
            if u["id"] == uid:
                u["name"] = (name or "").strip() or u["name"]
                _save_registry(reg)
                return True
        return False


def delete_user(uid: str) -> bool:
    with _LOCK:
        reg = _ensure_initialized()
        if len(reg["users"]) <= 1:
            raise ValueError("Cannot delete the only user.")
        if uid not in {u["id"] for u in reg["users"]}:
            return False
        reg["users"] = [u for u in reg["users"] if u["id"] != uid]
        if reg["active"] == uid:
            reg["active"] = reg["users"][0]["id"]
        _save_registry(reg)
        try:
            shutil.rmtree(USERS_ROOT / uid)
        except OSError:
            pass
        return True


# --- current-user resolution (thread-local override -> active) -------------

def current_user_id() -> str:
    return getattr(_local, "user", None) or get_active()


def set_thread_user(uid) -> None:
    _local.user = uid


def clear_thread_user() -> None:
    _local.user = None


class using_user:
    """Context manager: temporarily set the current user for this thread."""

    def __init__(self, uid: str):
        self.uid = uid
        self._prev = None

    def __enter__(self):
        self._prev = getattr(_local, "user", None)
        _local.user = self.uid
        return self

    def __exit__(self, *exc):
        _local.user = self._prev
        return False


# --- path resolution -------------------------------------------------------

def user_dir(uid: str | None = None) -> Path:
    uid = uid or current_user_id()
    d = USERS_ROOT / uid
    d.mkdir(parents=True, exist_ok=True)
    return d


def digest_dir(uid: str | None = None) -> Path:
    d = user_dir(uid) / "digest"
    d.mkdir(parents=True, exist_ok=True)
    return d


def resume_dir(uid: str | None = None) -> Path:
    return user_dir(uid)
