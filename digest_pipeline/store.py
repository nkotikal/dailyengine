"""Persistence for the Daily Digest engine (stdlib only).

Everything lives under ``data/digest/`` so it is fully separate from the resume
pipeline's ``data/`` files:
  config.json   - what you tell it about yourself + delivery preferences.
  updates.json  - the running log of updates you add between digests.
  state.json    - bookkeeping (last sent date, last render, last error).
"""

import json
import os
import threading
import time
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DIR = ROOT / "data" / "digest"
CONFIG_PATH = DIR / "config.json"
UPDATES_PATH = DIR / "updates.json"
STATE_PATH = DIR / "state.json"
SCHEDULE_PATH = DIR / "schedule.json"
KOREAN_PATH = DIR / "korean.json"
TRACKERS_PATH = DIR / "trackers.json"
TRACKER_STATE_PATH = DIR / "tracker_state.json"
REMINDERS_PATH = DIR / "reminders.json"
MEMORY_PATH = DIR / "memory.json"
WEEKLY_TASKS_PATH = DIR / "weekly_tasks.json"

# Suggested memory buckets (free-form categories are allowed too).
MEMORY_CATEGORIES = [
    "about", "goal", "project", "preference", "skill",
    "experience", "fact", "contact", "reminder",
]

# Serialize read/modify/write cycles (the scheduler thread and HTTP threads both touch these).
_LOCK = threading.RLock()

DEFAULT_CONFIG = {
    "about": "",          # who you are, context, working style
    "goals": "",          # legacy single goals field (migrated to long-term)
    "weekly_goals": "",   # goals for this week
    "longterm_goals": "",  # long-term goals, ideally with target dates
    "tasks": "",          # recurring / standing daily tasks
    "email_to": "",       # recipient address
    "send_time": "07:00",  # local 24h HH:MM
    "model": "",          # optional model override; "" = default
    "offline": False,     # skip the LLM and build a plain digest
    "enabled": False,     # is the morning scheduler armed?
    "tone": "friendly and concise",
    "include_schedule": True,    # fold today's parsed planner into the digest
    "include_calendar": True,    # pull today's Google Calendar events (if configured)
    "include_trackers": True,    # poll trackers for new developments
    "korean_enabled": False,     # add a daily Korean lesson
    "korean_level": "intermediate",
    "daily_capacity_hours": 6,   # realistic focus hours/day (headspace / anti-overload)
    "news_enabled": True,        # include a Headlines section
    "interests": [],             # topics you care about (shape headline selection)
    "news_sources": [
        {"id": "hn", "type": "hackernews", "name": "Hacker News",
         "url": "https://news.ycombinator.com/", "enabled": True},
    ],
}


def _read_json(path: Path, default):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def _write_json(path: Path, obj) -> None:
    DIR.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, indent=2, ensure_ascii=False)
    tmp.replace(path)


# --- config ----------------------------------------------------------------

def load_config() -> dict:
    with _LOCK:
        cfg = dict(DEFAULT_CONFIG)
        stored = _read_json(CONFIG_PATH, {})
        if isinstance(stored, dict):
            cfg.update({k: stored[k] for k in stored if k in DEFAULT_CONFIG})
        return cfg


def save_config(updates: dict) -> dict:
    with _LOCK:
        cfg = load_config()
        for k, v in (updates or {}).items():
            if k in DEFAULT_CONFIG:
                cfg[k] = v
        _write_json(CONFIG_PATH, cfg)
        return cfg


# --- updates ---------------------------------------------------------------

def list_updates() -> list:
    with _LOCK:
        data = _read_json(UPDATES_PATH, [])
        return data if isinstance(data, list) else []


def pending_updates() -> list:
    """Updates not yet folded into a sent digest."""
    return [u for u in list_updates() if not u.get("included")]


def add_update(text: str) -> dict:
    text = (text or "").strip()
    if not text:
        raise ValueError("Update text is empty.")
    with _LOCK:
        items = list_updates()
        item = {
            "id": uuid.uuid4().hex[:12],
            "text": text,
            "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "included": False,
        }
        items.append(item)
        _write_json(UPDATES_PATH, items)
        return item


def delete_update(update_id: str) -> bool:
    with _LOCK:
        items = list_updates()
        kept = [u for u in items if u.get("id") != update_id]
        if len(kept) == len(items):
            return False
        _write_json(UPDATES_PATH, kept)
        return True


def mark_included(ids) -> None:
    """Mark the given update ids as folded into a sent digest."""
    ids = set(ids or [])
    if not ids:
        return
    with _LOCK:
        items = list_updates()
        for u in items:
            if u.get("id") in ids:
                u["included"] = True
        _write_json(UPDATES_PATH, items)


def clear_included() -> int:
    """Permanently drop updates already included in a digest. Returns count removed."""
    with _LOCK:
        items = list_updates()
        kept = [u for u in items if not u.get("included")]
        removed = len(items) - len(kept)
        if removed:
            _write_json(UPDATES_PATH, kept)
        return removed


# --- state -----------------------------------------------------------------

def load_state() -> dict:
    with _LOCK:
        data = _read_json(STATE_PATH, {})
        return data if isinstance(data, dict) else {}


def save_state(updates: dict) -> dict:
    with _LOCK:
        state = load_state()
        state.update(updates or {})
        _write_json(STATE_PATH, state)
        return state


def add_interests(topics) -> list:
    with _LOCK:
        cfg = load_config()
        cur = list(cfg.get("interests") or [])
        low = {t.lower() for t in cur}
        for t in topics or []:
            t = str(t).strip()
            if t and t.lower() not in low:
                cur.append(t)
                low.add(t.lower())
        save_config({"interests": cur})
        return cur


def remove_interests(topics) -> list:
    with _LOCK:
        cfg = load_config()
        drop = {str(t).strip().lower() for t in (topics or [])}
        cur = [t for t in (cfg.get("interests") or []) if t.lower() not in drop]
        save_config({"interests": cur})
        return cur


def reply_processed(uid: str) -> bool:
    return uid in set(load_state().get("processed_reply_uids", []))


def mark_reply_processed(uid: str) -> None:
    with _LOCK:
        st = load_state()
        seen = st.get("processed_reply_uids", [])
        if uid not in seen:
            seen.append(uid)
            st["processed_reply_uids"] = seen[-500:]
            _write_json(STATE_PATH, st)


def claim_send_slot(date_str: str) -> bool:
    """Atomically claim 'today's digest' ACROSS PROCESSES.

    Returns True only for the first caller on ``date_str``; everyone else gets False.
    Uses O_CREAT|O_EXCL (atomic file create) so the Windows-task sender and the
    in-server scheduler can never both send the same day, even racing at 07:00.
    """
    DIR.mkdir(parents=True, exist_ok=True)
    lock = DIR / f".sent-{date_str}.lock"
    try:
        fd = os.open(str(lock), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        os.write(fd, time.strftime("%Y-%m-%d %H:%M:%S").encode())
        os.close(fd)
    except FileExistsError:
        return False
    except OSError:
        return False
    # Best-effort cleanup of stale day-locks from previous days.
    for p in DIR.glob(".sent-*.lock"):
        if p.name != lock.name:
            try:
                p.unlink()
            except OSError:
                pass
    return True


def release_send_slot(date_str: str) -> None:
    """Release a claimed slot (e.g. if the send failed) so a retry can run."""
    try:
        (DIR / f".sent-{date_str}.lock").unlink()
    except OSError:
        pass


# --- schedule (parsed planner) --------------------------------------------

def load_schedule() -> dict:
    with _LOCK:
        data = _read_json(SCHEDULE_PATH, {})
        return data if isinstance(data, dict) else {}


def save_schedule(raw: str, parsed: dict) -> dict:
    with _LOCK:
        data = {"raw": raw or "", "parsed": parsed or {},
                "updated_at": time.strftime("%Y-%m-%d %H:%M:%S")}
        _write_json(SCHEDULE_PATH, data)
        return data


# --- korean learning history ----------------------------------------------

def load_korean() -> dict:
    with _LOCK:
        data = _read_json(KOREAN_PATH, {})
        if not isinstance(data, dict):
            data = {}
        data.setdefault("history", [])
        data.setdefault("seen_vocab", [])
        data.setdefault("seen_grammar", [])
        # Structured-curriculum state:
        data.setdefault("progress", {"grammar_index": 0, "vocab_index": 0})
        data.setdefault("srs", {})  # key -> {type,item,reps,interval,next_due,introduced}
        data.setdefault("placement", {"done": False, "level": "intermediate"})
        return data


def save_korean(state: dict) -> dict:
    """Persist the entire Korean state (progress, srs, placement, history, seen)."""
    with _LOCK:
        state["history"] = state.get("history", [])[-120:]
        _write_json(KOREAN_PATH, state)
        return state


def korean_lesson_for(date_str: str):
    """Return a lesson already generated for date_str (so re-runs are stable)."""
    for entry in load_korean().get("history", []):
        if entry.get("date") == date_str:
            return entry.get("lesson")
    return None


# --- trackers --------------------------------------------------------------

def list_trackers() -> list:
    with _LOCK:
        data = _read_json(TRACKERS_PATH, [])
        return data if isinstance(data, list) else []


def get_tracker(tracker_id: str):
    for t in list_trackers():
        if t.get("id") == tracker_id:
            return t
    return None


def add_tracker(ttype: str, name: str, config: dict) -> dict:
    with _LOCK:
        items = list_trackers()
        item = {
            "id": uuid.uuid4().hex[:12],
            "type": ttype,
            "name": (name or "").strip() or ttype,
            "enabled": True,
            "config": config or {},
        }
        items.append(item)
        _write_json(TRACKERS_PATH, items)
        return item


def update_tracker(tracker_id: str, fields: dict) -> bool:
    with _LOCK:
        items = list_trackers()
        changed = False
        for t in items:
            if t.get("id") == tracker_id:
                for k in ("name", "enabled", "config", "type"):
                    if k in fields:
                        t[k] = fields[k]
                changed = True
        if changed:
            _write_json(TRACKERS_PATH, items)
        return changed


def delete_tracker(tracker_id: str) -> bool:
    with _LOCK:
        items = list_trackers()
        kept = [t for t in items if t.get("id") != tracker_id]
        if len(kept) == len(items):
            return False
        _write_json(TRACKERS_PATH, kept)
        state = _read_json(TRACKER_STATE_PATH, {})
        if isinstance(state, dict) and tracker_id in state:
            del state[tracker_id]
            _write_json(TRACKER_STATE_PATH, state)
        return True


def get_tracker_state(tracker_id: str) -> dict:
    with _LOCK:
        state = _read_json(TRACKER_STATE_PATH, {})
        if not isinstance(state, dict):
            return {}
        return state.get(tracker_id, {})


def set_tracker_state(tracker_id: str, new_state: dict) -> None:
    with _LOCK:
        state = _read_json(TRACKER_STATE_PATH, {})
        if not isinstance(state, dict):
            state = {}
        state[tracker_id] = new_state or {}
        _write_json(TRACKER_STATE_PATH, state)


# --- reminders / deadlines (persistent, resurface until done) --------------

def list_reminders() -> list:
    with _LOCK:
        data = _read_json(REMINDERS_PATH, [])
        return data if isinstance(data, list) else []


def add_reminder(text: str, due: str = "", priority: str = "medium") -> dict:
    text = (text or "").strip()
    if not text:
        raise ValueError("Reminder text is empty.")
    with _LOCK:
        items = list_reminders()
        item = {
            "id": uuid.uuid4().hex[:12],
            "text": text,
            "due": (due or "").strip(),     # YYYY-MM-DD or "" for undated
            "priority": priority if priority in ("low", "medium", "high") else "medium",
            "created_at": time.strftime("%Y-%m-%d"),
            "done": False,
        }
        items.append(item)
        _write_json(REMINDERS_PATH, items)
        return item


def update_reminder(rid: str, fields: dict) -> bool:
    with _LOCK:
        items = list_reminders()
        changed = False
        for r in items:
            if r.get("id") == rid:
                for k in ("text", "due", "priority", "done"):
                    if k in fields:
                        r[k] = fields[k]
                changed = True
        if changed:
            _write_json(REMINDERS_PATH, items)
        return changed


def delete_reminder(rid: str) -> bool:
    with _LOCK:
        items = list_reminders()
        kept = [r for r in items if r.get("id") != rid]
        if len(kept) == len(items):
            return False
        _write_json(REMINDERS_PATH, kept)
        return True


def active_reminders() -> list:
    return [r for r in list_reminders() if not r.get("done")]


# --- long-term memory (editable context that grows over time) --------------

def list_memories() -> list:
    with _LOCK:
        data = _read_json(MEMORY_PATH, [])
        return data if isinstance(data, list) else []


def get_memory(mem_id: str):
    for m in list_memories():
        if m.get("id") == mem_id:
            return m
    return None


def add_memory(text: str, category: str = "fact", source: str = "manual") -> dict:
    text = (text or "").strip()
    if not text:
        raise ValueError("Memory text is empty.")
    with _LOCK:
        items = list_memories()
        now = time.strftime("%Y-%m-%d %H:%M:%S")
        item = {
            "id": uuid.uuid4().hex[:12],
            "text": text,
            "category": (category or "fact").strip() or "fact",
            "source": source or "manual",
            "created_at": now,
            "updated_at": now,
        }
        items.append(item)
        _write_json(MEMORY_PATH, items)
        return item


def update_memory(mem_id: str, fields: dict) -> bool:
    with _LOCK:
        items = list_memories()
        changed = False
        for m in items:
            if m.get("id") == mem_id:
                if "text" in fields and str(fields["text"]).strip():
                    m["text"] = str(fields["text"]).strip()
                if "category" in fields and str(fields["category"]).strip():
                    m["category"] = str(fields["category"]).strip()
                m["updated_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
                changed = True
        if changed:
            _write_json(MEMORY_PATH, items)
        return changed


def delete_memory(mem_id: str) -> bool:
    with _LOCK:
        items = list_memories()
        kept = [m for m in items if m.get("id") != mem_id]
        if len(kept) == len(items):
            return False
        _write_json(MEMORY_PATH, kept)
        return True


def bulk_add_memories(items: list, source: str = "import") -> list:
    added = []
    for it in items or []:
        text = (it.get("text") if isinstance(it, dict) else str(it)) or ""
        if not text.strip():
            continue
        cat = it.get("category", "fact") if isinstance(it, dict) else "fact"
        added.append(add_memory(text, cat, source))
    return added


# --- weekly task list (derived from the weekly-goals box, then editable) ---

def list_weekly_tasks() -> list:
    with _LOCK:
        data = _read_json(WEEKLY_TASKS_PATH, [])
        return data if isinstance(data, list) else []


def _save_weekly_tasks(items: list) -> list:
    _write_json(WEEKLY_TASKS_PATH, items)
    return items


def _mk_subtasks(subs) -> list:
    """Build a (recursive) subtask tree; each node may have its own subtasks."""
    out = []
    for s in subs or []:
        if isinstance(s, dict):
            text = (s.get("text") or "").strip()
            done = bool(s.get("done"))
            kids = s.get("subtasks") or []
        else:
            text, done, kids = str(s).strip(), False, []
        if not text:
            continue
        due = (s.get("due") or "").strip() if isinstance(s, dict) else ""
        out.append({"id": uuid.uuid4().hex[:8], "text": text, "done": done,
                    "due": due, "subtasks": _mk_subtasks(kids)})
    return out


def _find_node(roots, node_id):
    """Find a node by id anywhere in the forest. Returns (node, siblings_list)."""
    for n in roots:
        if n.get("id") == node_id:
            return n, roots
        found, lst = _find_node(n.get("subtasks") or [], node_id)
        if found is not None:
            return found, lst
    return None, None


def add_weekly_task(text: str, priority: str = "medium", source: str = "manual",
                    subtasks=None, due: str = "", est_minutes: int = 0) -> dict:
    text = (text or "").strip()
    if not text:
        raise ValueError("Task text is empty.")
    with _LOCK:
        items = list_weekly_tasks()
        now = time.strftime("%Y-%m-%d %H:%M:%S")
        item = {
            "id": uuid.uuid4().hex[:12],
            "text": text,
            "done": False,
            "priority": priority if priority in ("high", "medium", "low") else "medium",
            "due": (due or "").strip(),
            "est_minutes": int(est_minutes or 0),
            "subtasks": _mk_subtasks(subtasks),
            "source": source,
            "created_at": now,
            "updated_at": now,
        }
        items.append(item)
        return _save_weekly_tasks(items)[-1]


def add_subtask(parent_id: str, text: str, due: str = "") -> bool:
    """Add a child under ANY node (task or subtask) - enables arbitrary depth."""
    text = (text or "").strip()
    if not text:
        raise ValueError("Subtask text is empty.")
    with _LOCK:
        items = list_weekly_tasks()
        parent, _ = _find_node(items, parent_id)
        if parent is None:
            return False
        parent.setdefault("subtasks", []).append(
            {"id": uuid.uuid4().hex[:8], "text": text, "done": False,
             "due": (due or "").strip(), "subtasks": []})
        _save_weekly_tasks(items)
        return True


def update_node(node_id: str, fields: dict) -> bool:
    """Update any node (task or subtask) by id. Importance/due/est apply to top tasks."""
    with _LOCK:
        items = list_weekly_tasks()
        node, siblings = _find_node(items, node_id)
        if node is None:
            return False
        if "text" in fields and str(fields["text"]).strip():
            node["text"] = str(fields["text"]).strip()
        if "done" in fields:
            node["done"] = bool(fields["done"])
        if "due" in fields:  # due dates apply to tasks AND subtasks (feed triage)
            node["due"] = str(fields["due"] or "").strip()
        if siblings is items:  # importance/estimate stay top-level
            if "priority" in fields and fields["priority"] in ("high", "medium", "low"):
                node["priority"] = fields["priority"]
            if "est_minutes" in fields:
                try:
                    node["est_minutes"] = max(0, int(fields["est_minutes"] or 0))
                except (TypeError, ValueError):
                    pass
            node["updated_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
        _save_weekly_tasks(items)
        return True


def delete_node(node_id: str) -> bool:
    """Delete any node (task or subtask) by id."""
    with _LOCK:
        items = list_weekly_tasks()
        node, siblings = _find_node(items, node_id)
        if node is None:
            return False
        siblings.remove(node)
        _save_weekly_tasks(items)
        return True


# Backwards-compatible aliases (top-level task ops route through the generic ones).
def update_weekly_task(task_id: str, fields: dict) -> bool:
    return update_node(task_id, fields)


def update_subtask(node_id: str, fields: dict) -> bool:
    return update_node(node_id, fields)


def delete_subtask(node_id: str) -> bool:
    return delete_node(node_id)


def delete_weekly_task(task_id: str) -> bool:
    return delete_node(task_id)


def merge_weekly_tasks(new_items: list, source: str = "derived") -> dict:
    """Merge derived tasks (with subtasks) into the stored list.

    - A new parent (text not already present) is added with its subtasks.
    - An existing parent keeps its state/edits; any genuinely new subtasks are added.
    Dedup is case-insensitive on text.
    """
    with _LOCK:
        items = list_weekly_tasks()
        by_text = {t.get("text", "").strip().lower(): t for t in items}
        added = added_subs = 0
        now = time.strftime("%Y-%m-%d %H:%M:%S")
        for it in new_items or []:
            if isinstance(it, dict):
                text = (it.get("text") or "").strip()
                pr = it.get("priority", "medium")
                subs_in = it.get("subtasks") or []
                due = (it.get("due") or "").strip()
                est = int(it.get("est_minutes") or 0)
            else:
                text, pr, subs_in, due, est = str(it).strip(), "medium", [], "", 0
            if not text:
                continue
            key = text.lower()
            existing = by_text.get(key)
            if existing is None:
                task = {
                    "id": uuid.uuid4().hex[:12], "text": text, "done": False,
                    "priority": pr if pr in ("high", "medium", "low") else "medium",
                    "due": due, "est_minutes": est,
                    "subtasks": _mk_subtasks(subs_in),
                    "source": source, "created_at": now, "updated_at": now,
                }
                items.append(task)
                by_text[key] = task
                added += 1
            else:
                have_subs = {s.get("text", "").strip().lower()
                             for s in existing.get("subtasks", [])}
                for s in _mk_subtasks(subs_in):
                    if s["text"].lower() not in have_subs:
                        existing.setdefault("subtasks", []).append(s)
                        have_subs.add(s["text"].lower())
                        added_subs += 1
        _save_weekly_tasks(items)
        return {"added": added, "added_subtasks": added_subs, "tasks": items}


def clear_weekly_tasks(only_done: bool = False) -> int:
    with _LOCK:
        items = list_weekly_tasks()
        kept = [t for t in items if t.get("done")] if False else (
            [t for t in items if not t.get("done")] if only_done else [])
        removed = len(items) - len(kept)
        _save_weekly_tasks(kept)
        return removed


# --- per-category clear / reset -------------------------------------------

# Text fields cleared by emptying them in the config.
_TEXT_CATEGORIES = {"about", "weekly_goals", "longterm_goals", "tasks"}


def clear_category(category: str) -> bool:
    """Clear one content category (or 'all'). Delivery settings are preserved."""
    cat = (category or "").strip()
    with _LOCK:
        if cat == "weekly_tasks":
            clear_weekly_tasks(False)
        elif cat == "weekly_tasks_done":
            clear_weekly_tasks(True)
        elif cat in _TEXT_CATEGORIES:
            upd = {cat: ""}
            if cat == "longterm_goals":
                upd["goals"] = ""  # also wipe the legacy field
            save_config(upd)
        elif cat == "schedule":
            _write_json(SCHEDULE_PATH, {})
        elif cat == "updates":
            _write_json(UPDATES_PATH, [])
        elif cat == "reminders":
            _write_json(REMINDERS_PATH, [])
        elif cat == "trackers":
            _write_json(TRACKERS_PATH, [])
            _write_json(TRACKER_STATE_PATH, {})
        elif cat == "memory":
            _write_json(MEMORY_PATH, [])
        elif cat == "korean":
            try:
                KOREAN_PATH.unlink()
            except FileNotFoundError:
                pass
        elif cat == "all":
            for c in ("weekly_tasks", "schedule", "updates", "reminders",
                      "trackers", "memory", "korean"):
                clear_category(c)
            save_config({"about": "", "goals": "", "weekly_goals": "",
                         "longterm_goals": "", "tasks": ""})
        else:
            return False
        return True
