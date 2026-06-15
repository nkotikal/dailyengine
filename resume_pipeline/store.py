"""Profile persistence.

The profile is saved on any run that supplies one, so that future runs can pass
only the job-description keywords and reuse the stored profile.
"""

import json
from pathlib import Path

DEFAULT_STORE = Path(__file__).resolve().parent.parent / "data" / "profile.json"
DEFAULT_OPTIMIZED = Path(__file__).resolve().parent.parent / "data" / "optimized.json"
DEFAULT_CONTEXT = Path(__file__).resolve().parent.parent / "data" / "context.txt"


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
