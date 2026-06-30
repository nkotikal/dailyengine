"""Profile persistence.

The profile is saved on any run that supplies one, so that future runs can pass
only the job-description keywords and reuse the stored profile. Every time the
current profile changes it is also archived as a timestamped version under
``data/profiles/`` so older saved profiles remain viewable and restorable.
"""

import json
import time
import uuid
from datetime import datetime
from pathlib import Path

DEFAULT_STORE = Path(__file__).resolve().parent.parent / "data" / "profile.json"
DEFAULT_OPTIMIZED = Path(__file__).resolve().parent.parent / "data" / "optimized.json"
DEFAULT_CONTEXT = Path(__file__).resolve().parent.parent / "data" / "context.txt"
PROFILES_DIR = Path(__file__).resolve().parent.parent / "data" / "profiles"


def save_profile(profile: dict, path: Path = DEFAULT_STORE) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(profile, f, indent=2, ensure_ascii=False)
    return path


def load_profile(path: Path = DEFAULT_STORE):
    path = Path(path)
    if not path.exists():
        return None
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def has_profile(path: Path = DEFAULT_STORE) -> bool:
    return Path(path).exists()


def profile_name(path: Path = DEFAULT_STORE) -> str:
    """Return the stored profile's contact name, or '' if none/unreadable."""
    try:
        profile = load_profile(path)
    except (OSError, ValueError):
        return ""
    if not isinstance(profile, dict):
        return ""
    contact = profile.get("contact") or {}
    return str(contact.get("name") or "").strip() if isinstance(contact, dict) else ""


def _profile_display_name(profile) -> str:
    if not isinstance(profile, dict):
        return ""
    contact = profile.get("contact") or {}
    return str(contact.get("name") or "").strip() if isinstance(contact, dict) else ""


def archive_profile(profile: dict, source: str = "", profiles_dir: Path = PROFILES_DIR) -> dict | None:
    """Save a timestamped snapshot of ``profile`` to the version archive.

    Skips writing if it is identical to the most recent snapshot (avoids dupes on
    repeated saves). Returns the snapshot metadata, or None if skipped/invalid.
    """
    if not isinstance(profile, dict):
        return None
    profiles_dir = Path(profiles_dir)
    profiles_dir.mkdir(parents=True, exist_ok=True)

    versions = list_profile_versions(profiles_dir)
    if versions:
        latest = load_profile_version(versions[0]["id"], profiles_dir)
        if latest == profile:
            return None  # unchanged since last snapshot

    # Microsecond precision keeps ids strictly chronological (sortable) even when
    # several saves happen within the same second.
    vid = datetime.now().strftime("%Y%m%d-%H%M%S-%f") + "-" + uuid.uuid4().hex[:4]
    snapshot = {
        "id": vid,
        "saved_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "source": source or "",
        "name": _profile_display_name(profile),
        "profile": profile,
    }
    with open(profiles_dir / f"{vid}.json", "w", encoding="utf-8") as f:
        json.dump(snapshot, f, indent=2, ensure_ascii=False)
    return {k: snapshot[k] for k in ("id", "saved_at", "source", "name")}


def list_profile_versions(profiles_dir: Path = PROFILES_DIR) -> list:
    """Return version metadata (newest first): [{id, saved_at, source, name}]."""
    profiles_dir = Path(profiles_dir)
    if not profiles_dir.exists():
        return []
    out = []
    for p in profiles_dir.glob("*.json"):
        try:
            with open(p, encoding="utf-8") as f:
                snap = json.load(f)
            out.append({
                "id": snap.get("id", p.stem),
                "saved_at": snap.get("saved_at", ""),
                "source": snap.get("source", ""),
                "name": snap.get("name", ""),
            })
        except (OSError, ValueError):
            continue
    out.sort(key=lambda s: s["id"], reverse=True)
    return out


def load_profile_version(version_id: str, profiles_dir: Path = PROFILES_DIR):
    """Return the full profile dict for a snapshot id, or None."""
    p = Path(profiles_dir) / f"{version_id}.json"
    if not p.exists():
        return None
    try:
        with open(p, encoding="utf-8") as f:
            return json.load(f).get("profile")
    except (OSError, ValueError):
        return None


def delete_profile_version(version_id: str, profiles_dir: Path = PROFILES_DIR) -> bool:
    p = Path(profiles_dir) / f"{version_id}.json"
    if p.exists():
        p.unlink()
        return True
    return False


def save_optimized(profile: dict, path: Path = DEFAULT_OPTIMIZED) -> Path:
    """Persist the last LLM-optimized profile (regeneration starts from this)."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(profile, f, indent=2, ensure_ascii=False)
    return path


def load_optimized(path: Path = DEFAULT_OPTIMIZED):
    path = Path(path)
    if not path.exists():
        return None
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def has_optimized(path: Path = DEFAULT_OPTIMIZED) -> bool:
    return Path(path).exists()


def clear_optimized(path: Path = DEFAULT_OPTIMIZED) -> bool:
    path = Path(path)
    if path.exists():
        path.unlink()
        return True
    return False


def clear(
    store_path: Path = DEFAULT_STORE,
    context_path: Path = DEFAULT_CONTEXT,
    optimized_path: Path = DEFAULT_OPTIMIZED,
) -> list:
    """Delete stored profile, optimized draft, and context. Returns names removed."""
    removed = []
    for p in (Path(store_path), Path(context_path), Path(optimized_path)):
        if p.exists():
            p.unlink()
            removed.append(p.name)
    return removed


def save_context(text: str, path: Path = DEFAULT_CONTEXT) -> Path:
    """Persist the full raw resume text / notes used as LLM context."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text or "", encoding="utf-8")
    return path


def append_context(text: str, path: Path = DEFAULT_CONTEXT) -> Path:
    """Append incremental notes to the stored context (repeatable gap-filling).

    Each note is timestamped so the accumulated context stays readable, and so the
    optimizer can treat later additions as the most current truth.
    """
    text = (text or "").strip()
    if not text:
        return Path(path)
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    from datetime import datetime
    stamp = datetime.now().strftime("%Y-%m-%d %H:%M")
    block = f"\n\n--- Added by candidate ({stamp}) ---\n{text}\n"
    existing = path.read_text(encoding="utf-8") if path.exists() else ""
    path.write_text((existing + block).strip() + "\n", encoding="utf-8")
    return path


def load_context(path: Path = DEFAULT_CONTEXT) -> str:
    path = Path(path)
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8")


def has_context(path: Path = DEFAULT_CONTEXT) -> bool:
    p = Path(path)
    return p.exists() and bool(p.read_text(encoding="utf-8").strip())
