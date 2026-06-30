"""Long-term, editable memory for the digest engine.

A growing list of small "memory" facts (about you, goals, projects, preferences,
resume highlights, ...). You can build on it, prune it, or reshape it over time:
  - directly (add / edit / delete a memory), or
  - in natural language ("I'm no longer working on X", "remember that I prefer Y"),
    which an LLM turns into precise add/update/remove operations, or
  - by uploading a resume, whose durable facts are extracted into memories.

All memories are fed to the digest composer as long-term context.
"""

from . import llm, store

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


def render_for_digest(max_items: int = 200) -> str:
    """Compact, grouped text of all memories for the digest composer."""
    items = store.list_memories()[:max_items]
    if not items:
        return ""
    by_cat = {}
    for m in items:
        by_cat.setdefault(m.get("category", "fact"), []).append(m.get("text", ""))
    lines = []
    for cat in sorted(by_cat):
        lines.append(f"{cat.capitalize()}:")
        for t in by_cat[cat]:
            lines.append(f"  - {t}")
    return "\n".join(lines)


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


def ingest_resume(raw_text: str, *, model: str | None = None) -> dict:
    """Extract durable facts from resume text into memories."""
    raw_text = (raw_text or "").strip()
    if not raw_text:
        raise ValueError("No resume text provided.")
    data = llm.post_json(RESUME_SYSTEM, "RESUME:\n" + raw_text[:20000],
                         model=model, temperature=0.2, max_tokens=3000)
    added = store.bulk_add_memories(data.get("memories") or [], source="resume")
    return {"added": len(added), "memories": store.list_memories()}
