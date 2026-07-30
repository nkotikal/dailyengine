"""Home Base - side-car state and the per-task LLM space for the 3D task tab.

The weekly task forest in ``weekly_tasks.json`` stays the single source of truth, so
anything edited from Home Base immediately shows up in the digest email, the recap and
the accountability score. This module only stores what the 3D view adds on top -
icons, descriptions, saved progress notes, per-task chat threads and view preferences -
in ``homebase.json``, keyed by task id. Entries for deleted tasks are pruned on read.
"""

import json
import re
import threading
import time

import user_context

from . import llm, store, tasks as task_lib

_LOCK = threading.RLock()

FILE = "homebase.json"

DEFAULT_PREFS = {
    "scene_theme": "space",   # which 3D scene the tab renders
    "filter": "week",         # which progress filter is selected
    "quality": "high",        # renderer quality tier
}

# Fields Home Base owns. Everything else about a task lives in weekly_tasks.json.
META_FIELDS = ("icon", "color", "description")

MAX_CHAT_MESSAGES = 60
MAX_NOTES = 40

_VALID_PRIORITY = ("critical", "high", "medium", "low")
_ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _path():
    return user_context.digest_dir() / FILE


def _blank() -> dict:
    return {"nodes": {}, "prefs": dict(DEFAULT_PREFS)}


def _read() -> dict:
    try:
        with open(_path(), encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return _blank()
    if not isinstance(data, dict):
        return _blank()
    nodes = data.get("nodes")
    prefs = dict(DEFAULT_PREFS)
    if isinstance(data.get("prefs"), dict):
        prefs.update({k: v for k, v in data["prefs"].items() if k in DEFAULT_PREFS})
    return {"nodes": nodes if isinstance(nodes, dict) else {}, "prefs": prefs}


def _write(data: dict) -> None:
    path = _path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    tmp.replace(path)


# --- node walking -----------------------------------------------------------

def _all_ids(nodes) -> set:
    out = set()
    for n in nodes or []:
        if n.get("id"):
            out.add(n["id"])
        out |= _all_ids(n.get("subtasks"))
    return out


def _find_path(roots, node_id, trail=None):
    """Return the chain of nodes from a root down to ``node_id`` (inclusive)."""
    trail = trail or []
    for n in roots or []:
        chain = trail + [n]
        if n.get("id") == node_id:
            return chain
        found = _find_path(n.get("subtasks"), node_id, chain)
        if found:
            return found
    return []


def _entry(data: dict, node_id: str) -> dict:
    return data["nodes"].setdefault(node_id, {})


# --- public state -----------------------------------------------------------

def load() -> dict:
    """Side-car state with entries for deleted tasks dropped."""
    with _LOCK:
        data = _read()
        live = _all_ids(store.list_weekly_tasks())
        orphans = [k for k in data["nodes"] if k not in live]
        if orphans:
            for k in orphans:
                data["nodes"].pop(k, None)
            _write(data)
        return data


def state() -> dict:
    """Everything the Home Base tab needs in one round trip."""
    data = load()
    cfg = store.load_config()
    return {
        "ok": True,
        "tasks": store.list_weekly_tasks(),
        "summary": task_lib.summary(),
        "meta": data["nodes"],
        "prefs": data["prefs"],
        "weekly_goals": cfg.get("weekly_goals", ""),
        "offline": bool(cfg.get("offline")),
        "llm_ready": llm_available(),
    }


def set_meta(node_id: str, fields: dict) -> dict:
    """Set Home Base-only fields (icon, color, description) on one task."""
    node_id = (node_id or "").strip()
    if not node_id:
        raise ValueError("Missing task id.")
    with _LOCK:
        data = _read()
        entry = _entry(data, node_id)
        for key in META_FIELDS:
            if key in (fields or {}):
                entry[key] = str(fields[key] or "").strip()[:2000]
        _write(data)
        return entry


def set_prefs(updates: dict) -> dict:
    with _LOCK:
        data = _read()
        for k, v in (updates or {}).items():
            if k in DEFAULT_PREFS:
                data["prefs"][k] = str(v)
        _write(data)
        return data["prefs"]


def add_note(node_id: str, text: str) -> dict:
    """Append a saved progress note to a task."""
    text = (text or "").strip()
    if not text:
        raise ValueError("Note is empty.")
    with _LOCK:
        data = _read()
        entry = _entry(data, node_id)
        notes = entry.setdefault("notes", [])
        note = {"at": time.strftime("%Y-%m-%d %H:%M"), "text": text[:1000]}
        notes.append(note)
        del notes[:-MAX_NOTES]
        _write(data)
        return note


def reset_chat(node_id: str) -> bool:
    with _LOCK:
        data = _read()
        entry = data["nodes"].get(node_id)
        if not entry or not entry.get("chat"):
            return False
        entry["chat"] = []
        _write(data)
        return True


def _append_chat(node_id: str, role: str, text: str) -> None:
    with _LOCK:
        data = _read()
        entry = _entry(data, node_id)
        thread = entry.setdefault("chat", [])
        thread.append({"role": role, "text": text, "at": time.strftime("%Y-%m-%d %H:%M")})
        del thread[:-MAX_CHAT_MESSAGES]
        _write(data)


def reset_progress() -> int:
    """Uncheck every task and subtask, keeping the structure. Returns how many changed."""
    return store.reset_weekly_progress()


# --- LLM space --------------------------------------------------------------

CHAT_SYSTEM = """\
You are the assistant living inside ONE task in a personal task cosmos. The user is
looking at that task and asking about it. Be concrete, brief and practical - you are a
thinking partner, not a cheerleader. Never invent progress the user did not report.

Respond with ONLY a single valid JSON object. No markdown, no code fences:

{ "reply": "your answer to the user, 1-4 short sentences",
  "note": "a durable progress fact worth saving, or empty",
  "updates": {"done": true, "due": "YYYY-MM-DD", "priority": "critical|high|medium|low",
              "text": "a better task name", "description": "what this task involves"},
  "add_subtasks": ["a concrete next step", "another step"] }

RULES:
- "reply" is required. Every other key is optional - omit or leave empty when nothing
  should change. An empty "updates" object is the normal case.
- Only include a key in "updates" when the user's message clearly implies it. "I
  finished it" -> done. "push it to Friday" -> the matching ISO date. "this is
  urgent" -> priority. Do NOT restate values that are already correct.
- "note" is for progress worth remembering later ("blocked on the driver team's
  review", "first draft done"), not for pleasantries. Leave it empty otherwise.
- "add_subtasks" only when the user asks you to break the task down or clearly names
  new steps. Each one is a short, concrete line starting with a verb. Max 8.
- If the user is only asking a question, answer it and change nothing."""

ASK_ONLY_RULE = """

MODE: READ-ONLY. The user has not authorized changes. Return "updates": {} and
"add_subtasks": [], and leave "note" empty. Answer in "reply" only."""

BREAKDOWN_SYSTEM = """\
You break ONE task into the concrete steps needed to finish it. Respond with ONLY a
JSON object: { "subtasks": ["step starting with a verb", "..."] }

RULES:
- 3 to 6 steps, ordered the way they would actually be done.
- Each step is one short line, concrete enough to start without thinking.
- Do not repeat steps that already exist under the task.
- No preamble, no numbering, no markdown."""


def llm_available() -> bool:
    """True when a task can actually reach a model right now."""
    cfg = store.load_config()
    if cfg.get("offline"):
        return False
    return bool(llm.have_key() or llm.openai_configured())


def _provider(cfg: dict):
    """Pick the provider for a one-off call without disturbing a digest run."""
    if llm.have_key():
        return None  # default (Anthropic gateway)
    if llm.openai_configured():
        llm.set_active("openai", cfg.get("openai_model") or None)
        return "openai"
    raise llm.DigestLLMError(
        "No model is configured. Set ANTHROPIC_API_KEY (or the OpenAI fallback) in .env."
    )


def _outline(node: dict, depth: int = 0, lines=None) -> list:
    lines = lines if lines is not None else []
    mark = "x" if node.get("done") else " "
    bits = [f"{'  ' * depth}- [{mark}] {node.get('text', '')}"]
    extras = []
    if node.get("due"):
        extras.append("due " + node["due"])
    if node.get("priority") and node["priority"] != "medium":
        extras.append(node["priority"])
    if node.get("est_minutes"):
        extras.append(task_lib.fmt_est(node["est_minutes"]))
    if extras:
        bits.append(f"  ({', '.join(extras)})")
    lines.append("".join(bits))
    for kid in node.get("subtasks") or []:
        _outline(kid, depth + 1, lines)
    return lines


def _context_for(node_id: str) -> tuple:
    """Build (node, prompt_context, side-car entry) for one task."""
    items = store.list_weekly_tasks()
    chain = _find_path(items, node_id)
    if not chain:
        raise ValueError("That task no longer exists.")
    node = chain[-1]
    entry = load()["nodes"].get(node_id, {})

    parts = ["TODAY: " + time.strftime("%Y-%m-%d (%A)")]
    if len(chain) > 1:
        parts.append("WHERE IT LIVES: " + " > ".join(n.get("text", "") for n in chain[:-1]))
    parts.append("THE TASK (with its subtasks):\n" + "\n".join(_outline(node)))
    if entry.get("description"):
        parts.append("DESCRIPTION: " + entry["description"])
    notes = entry.get("notes") or []
    if notes:
        parts.append("SAVED PROGRESS:\n" + "\n".join(
            f"- {n.get('at', '')}: {n.get('text', '')}" for n in notes[-8:]))
    thread = entry.get("chat") or []
    if thread:
        parts.append("EARLIER IN THIS CONVERSATION:\n" + "\n".join(
            f"{m.get('role', 'user').upper()}: {m.get('text', '')}" for m in thread[-10:]))
    return node, "\n\n".join(parts), entry


def _clean_updates(raw, node: dict) -> dict:
    """Keep only well-formed changes that actually differ from the current values."""
    out = {}
    if not isinstance(raw, dict):
        return out
    if "done" in raw and isinstance(raw["done"], bool) and raw["done"] != bool(node.get("done")):
        out["done"] = raw["done"]
    due = str(raw.get("due", "") or "").strip()
    if due and _ISO_DATE.match(due) and due != (node.get("due") or ""):
        out["due"] = due
    pr = str(raw.get("priority", "") or "").strip().lower()
    if pr in _VALID_PRIORITY and pr != (node.get("priority") or "medium"):
        out["priority"] = pr
    text = str(raw.get("text", "") or "").strip()
    if text and text != (node.get("text") or ""):
        out["text"] = text[:300]
    desc = str(raw.get("description", "") or "").strip()
    if desc:
        out["description"] = desc[:2000]
    return out


def chat(node_id: str, message: str, *, mode: str = "ask", model: str | None = None) -> dict:
    """One turn in a task's LLM space. In 'edit' mode the model may change the task."""
    message = (message or "").strip()
    if not message:
        raise ValueError("Ask something first.")
    cfg = store.load_config()
    if cfg.get("offline"):
        raise llm.DigestLLMError(
            "Offline mode is on, so the task space cannot reach a model. "
            "Turn it off in Daily Digest settings."
        )
    node, context, _entry_now = _context_for(node_id)
    editable = mode == "edit"
    provider = _provider(cfg)

    system = CHAT_SYSTEM if editable else CHAT_SYSTEM + ASK_ONLY_RULE
    data = llm.post_json(system, context + "\n\nUSER: " + message,
                         model=(model or cfg.get("model") or None),
                         temperature=0.3, max_tokens=1200, provider=provider)

    reply = str(data.get("reply") or "").strip() or "(no reply)"
    applied = []

    if editable:
        updates = _clean_updates(data.get("updates"), node)
        desc = updates.pop("description", "")
        if updates:
            store.update_node(node_id, updates)
            for key, val in updates.items():
                applied.append(f"{key} -> {val}" if not isinstance(val, bool)
                               else (f"marked {'done' if val else 'not done'}"))
        if desc:
            set_meta(node_id, {"description": desc})
            applied.append("description updated")
        added = 0
        for sub in (data.get("add_subtasks") or [])[:8]:
            text = str(sub or "").strip()
            if text and store.add_subtask(node_id, text[:300]):
                added += 1
        if added:
            applied.append(f"added {added} subtask{'s' if added != 1 else ''}")
        note = str(data.get("note") or "").strip()
        if note:
            add_note(node_id, note)
            applied.append("saved a progress note")

    _append_chat(node_id, "user", message)
    _append_chat(node_id, "assistant", reply)

    fresh = load()
    return {
        "ok": True,
        "reply": reply,
        "applied": applied,
        "changed": bool(applied),
        "tasks": store.list_weekly_tasks(),
        "summary": task_lib.summary(),
        "meta": fresh["nodes"],
    }


def breakdown(node_id: str, *, model: str | None = None) -> dict:
    """Ask the model to split one task into concrete steps, and add them as subtasks."""
    cfg = store.load_config()
    if cfg.get("offline"):
        raise llm.DigestLLMError(
            "Offline mode is on. Turn it off to break tasks down automatically, "
            "or add subtasks by hand."
        )
    node, context, _ = _context_for(node_id)
    provider = _provider(cfg)
    data = llm.post_json(BREAKDOWN_SYSTEM, context,
                         model=(model or cfg.get("model") or None),
                         temperature=0.2, max_tokens=700, provider=provider)
    added = 0
    for sub in (data.get("subtasks") or [])[:8]:
        text = str(sub or "").strip()
        if text and store.add_subtask(node_id, text[:300]):
            added += 1
    return {
        "ok": True,
        "added": added,
        "tasks": store.list_weekly_tasks(),
        "summary": task_lib.summary(),
        "meta": load()["nodes"],
    }
