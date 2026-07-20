"""Persistence for the Daily Digest engine (stdlib only).

Everything lives under ``data/digest/`` so it is fully separate from the resume
pipeline's ``data/`` files:
  config.json   - what you tell it about yourself + delivery preferences.
  updates.json  - the running log of updates you add between digests.
  state.json    - bookkeeping (last sent date, last render, last error).
"""

import json
import os
import re
import threading
import time
import uuid
from pathlib import Path

import user_context

# Per-user data isolation: every path resolves to the *current* user's digest
# folder (data/users/<id>/digest). HTTP requests use the active user; the
# scheduler and headless sender switch the current user per-user via
# ``user_context.using_user``. Nothing here is shared between users.

def _dir() -> Path:
    return user_context.digest_dir()


def _p(name: str) -> Path:
    return _dir() / name

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
    "korean_enabled": False,     # add a daily language lesson (name kept for back-compat)
    "korean_level": "intermediate",
    "language": "korean",        # which language practice: "korean" | "english"
    "english_level": "advanced", # english vocab level
    "theme": "",                 # UI color theme for this user ("" = default/aurora)
    "pattern": "moroccan",       # backdrop geometric pattern
    "ui_lang": "en",             # dashboard + report language: "en" | "ko" (Korean mode)
    "daily_capacity_hours": 6,   # realistic focus hours/day (headspace / anti-overload)
    "openai_model": "gpt-5.4-mini",  # OpenAI fallback model (used if AMD gateway is down)
    "news_enabled": True,        # include a Headlines section
    # --- daily accountability (email check-ins + score) ---
    "checkins_enabled": False,       # send progress check-in emails through the day
    "checkin_times": ["11:30", "15:00", "18:30"],  # local HH:MM slots to check in
    # Content controls for the check-in emails (what each one includes):
    "checkin_show_score": True,      # the points / tasks-done / % strip
    "checkin_show_later": True,      # the "Later today" section (else only what's due by now)
    "checkin_show_hint": True,       # the "reply done 1 3" instructions box
    "checkin_scope": "up_to_now",    # "up_to_now" = focus on due-by-now; "full_day" = whole plan
    "eod_recap_enabled": False,      # send an end-of-day recap + score email
    "eod_recap_time": "21:00",       # when the recap goes out
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
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, indent=2, ensure_ascii=False)
    tmp.replace(path)


# --- config ----------------------------------------------------------------

def load_config() -> dict:
    with _LOCK:
        cfg = dict(DEFAULT_CONFIG)
        stored = _read_json(_p("config.json"), {})
        if isinstance(stored, dict):
            cfg.update({k: stored[k] for k in stored if k in DEFAULT_CONFIG})
        return cfg


def save_config(updates: dict) -> dict:
    with _LOCK:
        cfg = load_config()
        for k, v in (updates or {}).items():
            if k in DEFAULT_CONFIG:
                cfg[k] = v
        _write_json(_p("config.json"), cfg)
        return cfg


# --- updates ---------------------------------------------------------------

def list_updates() -> list:
    with _LOCK:
        data = _read_json(_p("updates.json"), [])
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
        _write_json(_p("updates.json"), items)
        return item


def delete_update(update_id: str) -> bool:
    with _LOCK:
        items = list_updates()
        kept = [u for u in items if u.get("id") != update_id]
        if len(kept) == len(items):
            return False
        _write_json(_p("updates.json"), kept)
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
        _write_json(_p("updates.json"), items)


def clear_included() -> int:
    """Permanently drop updates already included in a digest. Returns count removed."""
    with _LOCK:
        items = list_updates()
        kept = [u for u in items if not u.get("included")]
        removed = len(items) - len(kept)
        if removed:
            _write_json(_p("updates.json"), kept)
        return removed


# --- state -----------------------------------------------------------------

def load_state() -> dict:
    with _LOCK:
        data = _read_json(_p("state.json"), {})
        return data if isinstance(data, dict) else {}


def save_state(updates: dict) -> dict:
    with _LOCK:
        state = load_state()
        state.update(updates or {})
        _write_json(_p("state.json"), state)
        return state


# --- daily accountability: day plan + score history ------------------------

def load_dayplan() -> dict:
    """Today's numbered plan + check-in/score state (or {})."""
    with _LOCK:
        data = _read_json(_p("dayplan.json"), {})
        return data if isinstance(data, dict) else {}


def save_dayplan(obj: dict) -> dict:
    with _LOCK:
        _write_json(_p("dayplan.json"), obj or {})
        return obj or {}


def load_scores() -> dict:
    """Finalized per-day scores keyed by YYYY-MM-DD (for weekly/monthly rollups)."""
    with _LOCK:
        data = _read_json(_p("scores.json"), {})
        return data if isinstance(data, dict) else {}


def save_scores(obj: dict) -> dict:
    with _LOCK:
        _write_json(_p("scores.json"), obj or {})
        return obj or {}


def merge_weekly_goals(lines) -> str:
    """Append new planning lines to the weekly-goals text (deduped, case-insensitive),
    so time-blocking / targets from an email reply land in the existing Weekly goals
    box instead of a new cluttered section. Returns the merged text."""
    lines = [str(x).strip() for x in (lines or []) if str(x).strip()]
    if not lines:
        return load_config().get("weekly_goals", "")
    with _LOCK:
        cur = (load_config().get("weekly_goals") or "").rstrip()
        have = {ln.strip().lower() for ln in cur.splitlines() if ln.strip()}
        added = [ln for ln in lines if ln.lower() not in have]
        if not added:
            return cur
        merged = (cur + ("\n" if cur else "") + "\n".join(added)).strip()
        save_config({"weekly_goals": merged})
        return merged


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
            _write_json(_p("state.json"), st)


def claim_send_slot(date_str: str) -> bool:
    """Atomically claim 'today's digest' ACROSS PROCESSES.

    Returns True only for the first caller on ``date_str``; everyone else gets False.
    Uses O_CREAT|O_EXCL (atomic file create) so the Windows-task sender and the
    in-server scheduler can never both send the same day, even racing at 07:00.
    """
    d = _dir()
    d.mkdir(parents=True, exist_ok=True)
    lock = d / f".sent-{date_str}.lock"
    try:
        fd = os.open(str(lock), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        os.write(fd, time.strftime("%Y-%m-%d %H:%M:%S").encode())
        os.close(fd)
    except FileExistsError:
        return False
    except OSError:
        return False
    # Best-effort cleanup of stale day-locks from previous days.
    for p in d.glob(".sent-*.lock"):
        if p.name != lock.name:
            try:
                p.unlink()
            except OSError:
                pass
    return True


def release_send_slot(date_str: str) -> None:
    """Release a claimed slot (e.g. if the send failed) so a retry can run."""
    try:
        (_dir() / f".sent-{date_str}.lock").unlink()
    except OSError:
        pass


def _safe_key(key: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]", "_", str(key or ""))[:80]


def claim_once(key: str) -> bool:
    """Atomically claim a one-shot job (e.g. a check-in slot or the recap) ACROSS
    PROCESSES, so the Windows scheduled task and the in-server scheduler never both
    fire the same job. Returns True only for the first caller for ``key``."""
    d = _dir()
    d.mkdir(parents=True, exist_ok=True)
    lock = d / f".claim-{_safe_key(key)}.lock"
    try:
        fd = os.open(str(lock), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        os.write(fd, time.strftime("%Y-%m-%d %H:%M:%S").encode())
        os.close(fd)
    except (FileExistsError, OSError):
        return False
    # Best-effort cleanup of claim files older than a week.
    cutoff = time.time() - 7 * 86400
    for p in d.glob(".claim-*.lock"):
        try:
            if p.stat().st_mtime < cutoff:
                p.unlink()
        except OSError:
            pass
    return True


def release_claim(key: str) -> None:
    """Release a claimed job (e.g. if its send failed) so a later tick can retry."""
    try:
        (_dir() / f".claim-{_safe_key(key)}.lock").unlink()
    except OSError:
        pass


# --- schedule (parsed planner) --------------------------------------------

def load_schedule() -> dict:
    with _LOCK:
        data = _read_json(_p("schedule.json"), {})
        return data if isinstance(data, dict) else {}


def save_schedule(raw: str, parsed: dict, for_date: str | None = None) -> dict:
    """Persist the planner. ``for_date`` (YYYY-MM-DD) is the day this plan is FOR
    (defaults to today), so the morning digest can tell whether the stored schedule
    is actually for today or a stale carry-over from a previous day.

    Also appends to a rolling schedule HISTORY so the generator can learn recurring
    items and their usual timings from past days.
    """
    with _LOCK:
        fd = for_date or time.strftime("%Y-%m-%d")
        data = {"raw": raw or "", "parsed": parsed or {},
                "for_date": fd,
                "updated_at": time.strftime("%Y-%m-%d %H:%M:%S")}
        _write_json(_p("schedule.json"), data)
        hist = _read_json(_p("schedule_history.json"), [])
        if not isinstance(hist, list):
            hist = []
        hist = [h for h in hist if h.get("for_date") != fd]  # one entry per date
        hist.append({"for_date": fd, "raw": raw or "", "saved_at": data["updated_at"]})
        hist.sort(key=lambda h: h.get("for_date", ""))
        _write_json(_p("schedule_history.json"), hist[-60:])
        return data


def list_schedule_history(limit: int = 21) -> list:
    """Recent past schedules (oldest first), for learning recurring patterns."""
    with _LOCK:
        hist = _read_json(_p("schedule_history.json"), [])
        return (hist if isinstance(hist, list) else [])[-limit:]


# --- end-of-day reflection (blockers / mood / progress; feeds next morning) --

def load_reflection() -> dict:
    """The most recent end-of-day reflection (or {})."""
    with _LOCK:
        data = _read_json(_p("reflection.json"), {})
        if not isinstance(data, dict):
            return {}
        return data.get("latest") or {}


def save_reflection(obj: dict) -> dict:
    """Store the latest reflection (accomplishments, blockers, mood, progress),
    stamped with today's date, and keep a short history."""
    with _LOCK:
        store_obj = _read_json(_p("reflection.json"), {})
        if not isinstance(store_obj, dict):
            store_obj = {}
        latest = dict(obj or {})
        latest.setdefault("date", time.strftime("%Y-%m-%d"))
        latest["created_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
        hist = store_obj.get("history")
        if not isinstance(hist, list):
            hist = []
        hist.append(latest)
        store_obj["latest"] = latest
        store_obj["history"] = hist[-60:]
        _write_json(_p("reflection.json"), store_obj)
        return latest


# --- korean learning history ----------------------------------------------

def load_korean() -> dict:
    with _LOCK:
        data = _read_json(_p("korean.json"), {})
        if not isinstance(data, dict):
            data = {}
        data.setdefault("history", [])
        data.setdefault("seen_vocab", [])
        data.setdefault("seen_grammar", [])
        # Structured-curriculum state:
        data.setdefault("progress", {"grammar_index": 0, "vocab_index": 0})
        data.setdefault("srs", {})  # key -> {type,item,reps,interval,next_due,introduced}
        data.setdefault("placement", {"done": False, "level": "intermediate"})
        data.setdefault("weekly", {})          # current week's theme/words/status/day_slots
        data.setdefault("weekly_history", [])  # past weeks (cross-week reinforcement)
        return data


def save_korean(state: dict) -> dict:
    """Persist the entire Korean state (progress, srs, placement, history, seen)."""
    with _LOCK:
        state["history"] = state.get("history", [])[-120:]
        _write_json(_p("korean.json"), state)
        return state


def save_korean_practice(date_str: str, results: list) -> None:
    with _LOCK:
        state = load_korean()
        prac = state.setdefault("practice", {})
        prac.setdefault(date_str, [])
        prac[date_str].extend(results or [])
        save_korean(state)


def get_korean_practice(date_str: str) -> list:
    return (load_korean().get("practice", {}) or {}).get(date_str, [])


def korean_lesson_for(date_str: str):
    """Return a lesson already generated for date_str (so re-runs are stable)."""
    for entry in load_korean().get("history", []):
        if entry.get("date") == date_str:
            return entry.get("lesson")
    return None


# --- english vocab practice (separate language track) ----------------------

def load_english() -> dict:
    with _LOCK:
        data = _read_json(_p("english.json"), {})
        if not isinstance(data, dict):
            data = {}
        data.setdefault("history", [])
        data.setdefault("seen_words", [])
        return data


def save_english(state: dict) -> dict:
    with _LOCK:
        state["history"] = state.get("history", [])[-120:]
        _write_json(_p("english.json"), state)
        return state


def english_lesson_for(date_str: str):
    for entry in load_english().get("history", []):
        if entry.get("date") == date_str:
            return entry.get("lesson")
    return None


# --- trackers --------------------------------------------------------------

def list_trackers() -> list:
    with _LOCK:
        data = _read_json(_p("trackers.json"), [])
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
        _write_json(_p("trackers.json"), items)
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
            _write_json(_p("trackers.json"), items)
        return changed


def delete_tracker(tracker_id: str) -> bool:
    with _LOCK:
        items = list_trackers()
        kept = [t for t in items if t.get("id") != tracker_id]
        if len(kept) == len(items):
            return False
        _write_json(_p("trackers.json"), kept)
        state = _read_json(_p("tracker_state.json"), {})
        if isinstance(state, dict) and tracker_id in state:
            del state[tracker_id]
            _write_json(_p("tracker_state.json"), state)
        return True


def get_tracker_state(tracker_id: str) -> dict:
    with _LOCK:
        state = _read_json(_p("tracker_state.json"), {})
        if not isinstance(state, dict):
            return {}
        return state.get(tracker_id, {})


def set_tracker_state(tracker_id: str, new_state: dict) -> None:
    with _LOCK:
        state = _read_json(_p("tracker_state.json"), {})
        if not isinstance(state, dict):
            state = {}
        state[tracker_id] = new_state or {}
        _write_json(_p("tracker_state.json"), state)


# --- reminders / deadlines (persistent, resurface until done) --------------

def list_reminders() -> list:
    with _LOCK:
        data = _read_json(_p("reminders.json"), [])
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
        _write_json(_p("reminders.json"), items)
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
            _write_json(_p("reminders.json"), items)
        return changed


def delete_reminder(rid: str) -> bool:
    with _LOCK:
        items = list_reminders()
        kept = [r for r in items if r.get("id") != rid]
        if len(kept) == len(items):
            return False
        _write_json(_p("reminders.json"), kept)
        return True


def active_reminders() -> list:
    return [r for r in list_reminders() if not r.get("done")]


# --- long-term memory (editable context that grows over time) --------------

def list_memories() -> list:
    with _LOCK:
        data = _read_json(_p("memory.json"), [])
        return data if isinstance(data, list) else []


def get_memory(mem_id: str):
    for m in list_memories():
        if m.get("id") == mem_id:
            return m
    return None


def add_memory(text: str, category: str = "fact", source: str = "manual",
               importance: int = 60) -> dict:
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
            "importance": max(0, min(100, int(importance))),
            "created_at": now,
            "updated_at": now,
            "last_reinforced": now,
        }
        items.append(item)
        _write_json(_p("memory.json"), items)
        return item


def replace_memories(items: list) -> list:
    """Replace the whole memory list (used by the evolution/compression engine)."""
    with _LOCK:
        clean = [m for m in (items or []) if isinstance(m, dict) and m.get("text")]
        _write_json(_p("memory.json"), clean)
        return clean


def load_profile_base() -> str:
    p = _p("profile_base.txt")
    return p.read_text(encoding="utf-8") if p.exists() else ""


def save_profile_base(text: str) -> None:
    with _LOCK:
        p = _p("profile_base.txt")
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text or "", encoding="utf-8")


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
                if "importance" in fields:
                    try:
                        m["importance"] = max(0, min(100, int(fields["importance"])))
                    except (TypeError, ValueError):
                        pass
                m["updated_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
                m["last_reinforced"] = m["updated_at"]
                changed = True
        if changed:
            _write_json(_p("memory.json"), items)
        return changed


def delete_memory(mem_id: str) -> bool:
    with _LOCK:
        items = list_memories()
        kept = [m for m in items if m.get("id") != mem_id]
        if len(kept) == len(items):
            return False
        _write_json(_p("memory.json"), kept)
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
        data = _read_json(_p("weekly_tasks.json"), [])
        return data if isinstance(data, list) else []


def _save_weekly_tasks(items: list) -> list:
    _write_json(_p("weekly_tasks.json"), items)
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
        pr = (s.get("priority") if isinstance(s, dict) else "") or "medium"
        if pr not in ("critical", "high", "medium", "low"):
            pr = "medium"
        out.append({"id": uuid.uuid4().hex[:8], "text": text, "done": done,
                    "due": due, "priority": pr, "subtasks": _mk_subtasks(kids)})
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
            "priority": priority if priority in ("critical", "high", "medium", "low") else "medium",
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
        if "priority" in fields and fields["priority"] in ("critical", "high", "medium", "low"):
            node["priority"] = fields["priority"]  # priority applies to any node now
        if siblings is items:  # importance/estimate stay top-level
            pass
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
                    "priority": pr if pr in ("critical", "high", "medium", "low") else "medium",
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
            _write_json(_p("schedule.json"), {})
        elif cat == "updates":
            _write_json(_p("updates.json"), [])
        elif cat == "reminders":
            _write_json(_p("reminders.json"), [])
        elif cat == "trackers":
            _write_json(_p("trackers.json"), [])
            _write_json(_p("tracker_state.json"), {})
        elif cat == "memory":
            _write_json(_p("memory.json"), [])
        elif cat == "reflection":
            _write_json(_p("reflection.json"), {})
        elif cat == "korean":
            for fn in ("korean.json", "english.json"):
                try:
                    _p(fn).unlink()
                except FileNotFoundError:
                    pass
        elif cat == "all":
            for c in ("weekly_tasks", "schedule", "updates", "reminders",
                      "trackers", "memory", "reflection", "korean"):
                clear_category(c)
            save_config({"about": "", "goals": "", "weekly_goals": "",
                         "longterm_goals": "", "tasks": ""})
        else:
            return False
        return True
