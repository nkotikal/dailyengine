"""Long-term, editable memory for the digest engine.

A growing list of small "memory" facts (about you, goals, projects, preferences,
resume highlights, ...). You can build on it, prune it, or reshape it over time:
  - directly (add / edit / delete a memory), or
  - in natural language ("I'm no longer working on X", "remember that I prefer Y"),
    which an LLM turns into precise add/update/remove operations, or
  - by uploading a resume, whose durable facts are extracted into memories.

All memories are fed to the digest composer as long-term context.
"""

from datetime import datetime

from . import llm, store

# Importance decays as a memory goes un-reinforced; recent things stay prominent and
# old, low-importance ones get compressed (the "tail compression" rule).
_DECAY_PER_DAY = 4          # importance points shed per idle day
_COMPRESS_THRESHOLD = 22    # below this importance, an old memory is a compression target
_COMPRESS_MIN_AGE_DAYS = 9  # don't compress anything fresher than this
_COMPRESS_WHEN_OVER = 14    # only bother compressing once the tail gets long


def _age_days(m: dict, now: datetime) -> int:
    stamp = m.get("last_reinforced") or m.get("updated_at") or m.get("created_at") or ""
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            return max(0, (now - datetime.strptime(stamp, fmt)).days)
        except (ValueError, TypeError):
            continue
    return 0

CMD_SYSTEM = """\
You maintain a user's long-term memory: a list of short factual notes, each with an
id and a category. The user gives an instruction in natural language. Translate it
into precise operations on the memory list. Respond with ONLY a JSON object:

{
  "operations": [
    {"op": "add", "text": "...", "category": "about|goal|project|preference|skill|experience|fact|contact|reminder"},
    {"op": "update", "id": "<existing id>", "text": "...", "category": "..."},
    {"op": "remove", "id": "<existing id>"}
  ],
  "summary": "one short sentence describing what you changed"
}

RULES:
- Only act on what the instruction implies. Do not invent unrelated memories.
- Prefer "update" when the user is changing an existing memory; use its exact id.
- Use "remove" when the user says to forget/drop something; use the exact id.
- Keep each memory atomic (one fact per item) and concise.
- Pick the best-fitting category. If unsure, use "fact".
- If nothing should change, return an empty operations list and say so in summary."""

RESUME_SYSTEM = """\
You extract durable, reusable facts from a resume to seed a person's long-term
memory. Respond with ONLY a JSON object:

{
  "memories": [
    {"text": "...", "category": "about|goal|project|skill|experience|fact|contact"}
  ]
}

RULES:
- Capture stable, high-signal facts: current role/title and employer, education,
  key skills/technologies, notable projects, and durable achievements (keep real
  metrics). One atomic fact per item.
- Do NOT copy the resume verbatim line-by-line; distill the reusable essence.
- Skip ephemeral formatting, objectives, and filler.
- Aim for 10-25 concise memories."""


def render_for_digest(max_items: int = 60) -> str:
    """Memories for the digest composer, most important first (recent work dominates)."""
    items = sorted(store.list_memories(),
                   key=lambda m: -int(m.get("importance", 60)))[:max_items]
    if not items:
        return ""
    return "\n".join(f"- {m.get('text','')}" for m in items)


def _memories_for_prompt() -> str:
    items = store.list_memories()
    if not items:
        return "(empty)"
    return "\n".join(f'- id={m["id"]} [{m.get("category","fact")}] {m.get("text","")}'
                     for m in items)


def apply_command(command: str, *, model: str | None = None) -> dict:
    """Interpret a natural-language instruction and apply it to memory."""
    command = (command or "").strip()
    if not command:
        raise ValueError("Command is empty.")
    user = (
        "CURRENT MEMORIES:\n" + _memories_for_prompt()
        + "\n\nINSTRUCTION:\n" + command
    )
    data = llm.post_json(CMD_SYSTEM, user, model=model, temperature=0, max_tokens=2048)
    ops = data.get("operations") or []
    applied = {"added": 0, "updated": 0, "removed": 0, "ignored": 0}
    for op in ops:
        if not isinstance(op, dict):
            continue
        kind = (op.get("op") or "").lower()
        if kind == "add" and op.get("text"):
            store.add_memory(op["text"], op.get("category", "fact"), source="nl")
            applied["added"] += 1
        elif kind == "update" and op.get("id"):
            fields = {k: op[k] for k in ("text", "category") if k in op}
            applied["updated"] += 1 if store.update_memory(op["id"], fields) else 0
        elif kind == "remove" and op.get("id"):
            applied["removed"] += 1 if store.delete_memory(op["id"]) else 0
        else:
            applied["ignored"] += 1
    return {
        "summary": str(data.get("summary") or "").strip() or "Updated memory.",
        "applied": applied,
        "memories": store.list_memories(),
    }


REFLECT_SYSTEM = """\
You maintain a person's long-term memory. You are given their existing memories and
their END-OF-DAY REFLECTION (what they accomplished, what blocked them, what's next).
Extract only the DURABLE, long-term-relevant changes and return ONLY a JSON object:

{
  "operations": [
    {"op": "add", "text": "...", "category": "about|goal|project|preference|skill|experience|fact|reminder", "importance": 0-100},
    {"op": "update", "id": "<existing id>", "text": "...", "category": "..."}
  ],
  "summary": "one short sentence"
}

RULES:
- Capture meaningful PROGRESS on projects/goals ("shipped the AMD PR"), new durable
  facts, changed circumstances, and PERSISTENT blockers worth remembering long-term.
- Prefer "update" to evolve an existing project/goal memory (use its exact id) over
  adding a near-duplicate.
- IGNORE transient mood, one-off scheduling, and things already captured.
- Give real progress importance ~55-70; background facts lower. Be conservative:
  if nothing is durable, return an empty operations list."""


def incorporate_reflection(reflection: dict, *, model: str | None = None) -> dict:
    """Fold a day's reflection into long-term memory (add/update ops only)."""
    if not reflection:
        return {"applied": {"added": 0, "updated": 0}}
    lines = []
    if reflection.get("accomplished"):
        lines.append("ACCOMPLISHED:\n" + "\n".join(f"- {a}" for a in reflection["accomplished"]))
    if reflection.get("blockers"):
        lines.append("BLOCKERS:\n" + "\n".join(
            f"- [{b.get('type','other')}] {b.get('text','')}" for b in reflection["blockers"]))
    if reflection.get("whats_next"):
        lines.append("WHAT'S NEXT:\n" + "\n".join(f"- {n}" for n in reflection["whats_next"]))
    if not lines:
        return {"applied": {"added": 0, "updated": 0}}
    user = ("CURRENT MEMORIES:\n" + _memories_for_prompt()
            + "\n\nEND-OF-DAY REFLECTION:\n" + "\n\n".join(lines))
    data = llm.post_json(REFLECT_SYSTEM, user, model=model, temperature=0.2, max_tokens=1500)
    applied = {"added": 0, "updated": 0}
    for op in (data.get("operations") or []):
        if not isinstance(op, dict):
            continue
        kind = (op.get("op") or "").lower()
        if kind == "add" and op.get("text"):
            imp = op.get("importance", 60)
            try:
                imp = int(imp)
            except (TypeError, ValueError):
                imp = 60
            store.add_memory(op["text"], op.get("category", "experience"),
                             source="reflection", importance=imp)
            applied["added"] += 1
        elif kind == "update" and op.get("id"):
            fields = {k: op[k] for k in ("text", "category") if k in op}
            if store.update_memory(op["id"], fields):
                applied["updated"] += 1
    return {"summary": str(data.get("summary") or "").strip(), "applied": applied}


def ingest_resume(raw_text: str, *, model: str | None = None) -> dict:
    """Extract durable facts from resume text into memories."""
    raw_text = (raw_text or "").strip()
    if not raw_text:
        raise ValueError("No resume text provided.")
    data = llm.post_json(RESUME_SYSTEM, "RESUME:\n" + raw_text[:20000],
                         model=model, temperature=0.2, max_tokens=3000)
    added = store.bulk_add_memories(data.get("memories") or [], source="resume")
    return {"added": len(added), "memories": store.list_memories()}


# --- evolving, tail-compressing memory -------------------------------------

COMPRESS_SYSTEM = """\
You are the long-term memory of a personal assistant, keeping it lean and useful.
You are given OLDER, low-importance memories that should be COMPRESSED, plus context
on what the person is currently working on. Respond with ONLY a JSON object:

{ "compressed": [ {"text": "a concise merged memory capturing the durable gist",
                   "category": "fact", "importance": 0-100} ] }

RULES:
- Merge related old memories into a FEW compact lines (fewer than you were given).
- Preserve only what still matters long-term; drop transient/dated detail.
- Recent, active work is handled elsewhere - here, fade old context into the background.
- importance should be low (these are background)."""


def evolve(*, model: str | None = None, when: datetime | None = None,
           use_llm: bool = True) -> dict:
    """Daily memory evolution: decay importance by age, reinforce items tied to current
    work, then compress the long low-importance tail into a few background lines.

    The profile base context is stored separately and is NEVER touched here.
    """
    now = when or datetime.now()
    items = store.list_memories()
    if not items:
        return {"decayed": 0, "compressed": 0, "kept": 0}

    # Signals for what's currently active (so we reinforce the relevant memories).
    active_text = " ".join(
        (t.get("text", "") + " " + " ".join(s.get("text", "")
         for s in t.get("subtasks", [])))
        for t in store.list_weekly_tasks() if not t.get("done")
    ).lower()
    active_words = set(w for w in active_text.split() if len(w) > 3)

    decayed = 0
    for m in items:
        imp = int(m.get("importance", 60))
        age = _age_days(m, now)
        new_imp = imp - _DECAY_PER_DAY * min(age, 1)  # one decay step per run, scaled by idleness
        # Reinforce if this memory overlaps current active work.
        mw = set(w for w in m.get("text", "").lower().split() if len(w) > 3)
        if mw & active_words:
            new_imp = min(100, max(new_imp, imp) + 5)
            m["last_reinforced"] = now.strftime("%Y-%m-%d %H:%M:%S")
        m["importance"] = max(0, min(100, new_imp))
        if m["importance"] != imp:
            decayed += 1

    # Identify the compressible tail: old + low importance.
    tail = [m for m in items
            if m.get("importance", 60) < _COMPRESS_THRESHOLD
            and _age_days(m, now) >= _COMPRESS_MIN_AGE_DAYS]
    keep = [m for m in items if m not in tail]
    compressed_n = 0

    if len(tail) >= _COMPRESS_WHEN_OVER and use_llm and llm.have_key():
        try:
            payload = "\n".join(f"- {m.get('text','')}" for m in tail)
            data = llm.post_json(
                COMPRESS_SYSTEM,
                "OLDER MEMORIES TO COMPRESS:\n" + payload
                + "\n\nCURRENTLY ACTIVE:\n" + (active_text[:1500] or "(n/a)"),
                model=model, temperature=0.2, max_tokens=1200)
            merged = []
            now_s = now.strftime("%Y-%m-%d %H:%M:%S")
            for c in (data.get("compressed") or []):
                if isinstance(c, dict) and c.get("text"):
                    merged.append({
                        "id": __import__("uuid").uuid4().hex[:12],
                        "text": str(c["text"]).strip(),
                        "category": str(c.get("category", "fact")).strip() or "fact",
                        "importance": max(0, min(100, int(c.get("importance", 12) or 12))),
                        "source": "compressed", "created_at": now_s,
                        "updated_at": now_s, "last_reinforced": now_s,
                    })
            if merged:
                compressed_n = len(tail) - len(merged)
                keep.extend(merged)
                store.replace_memories(keep)
                return {"decayed": decayed, "compressed": compressed_n,
                        "kept": len(keep), "tail": len(tail)}
        except llm.DigestLLMError:
            pass

    store.replace_memories(items)  # persist decay/reinforcement
    return {"decayed": decayed, "compressed": compressed_n, "kept": len(items)}
