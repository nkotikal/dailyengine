"""Auto-assemble a daily schedule when you didn't hand one in.

Given what you want to accomplish (weekly tasks / focus), your active deadlines, and
your RECENT past schedules (to learn recurring items and their usual timings), the
LLM lays out a realistic hour-by-hour plan in the same planner format the app parses
(bare hour numbers; one-tab tasks; a leading ' marks something important). The result
is saved as today's schedule so the check-ins track real, concrete daily tasks.
"""

import re
from datetime import datetime

from . import llm, schedule, store, tasks

SYSTEM = """\
You are a personal planner. Build a realistic, focused HOUR-BY-HOUR schedule for the
day in EXACTLY this planner text format (no JSON, no commentary):

- A line that is just a number is an hour marker: 8 = 8 AM, 12 = noon, 1 = 1 PM ...
  List hours in chronological order across the working day.
- Lines indented ONE tab under an hour are the concrete tasks for that hour.
- A leading apostrophe (') marks an important task.
- Keep tasks concrete and doable; group related work into focused blocks.

RULES:
- Anchor the day on the RECURRING ITEMS learned from past schedules, placed at the
  times they usually happen (e.g. lunch ~12, gym in the evening, stand-ups, meals,
  sleep). Only include recurring items that make sense for THIS weekday.
- Fill focus blocks with the user's stated GOALS/TASKS for the day and anything with a
  near DEADLINE, giving the most important/urgent work prime, uninterrupted morning or
  early blocks. Mark those important with a leading '.
- Be realistic: don't overfill. Leave the day coherent, not minute-by-minute.
- Prefer the user's typical day shape (start/end hours, meal times) inferred from the
  past schedules. If none, assume a reasonable ~9 AM to ~10 PM day.
- Output ONLY the planner text."""


def _looks_like_schedule(text: str) -> bool:
    parsed = schedule.parse_schedule(text or "")
    return bool(parsed.get("blocks")) and bool(parsed.get("tasks_flat"))


def generate(when: datetime | None = None, *, goals_text: str = "",
             deadlines_text: str = "", model: str | None = None) -> dict | None:
    """Return {raw, parsed} for a generated schedule, or None if it can't be built."""
    when = when or datetime.now()
    weekday = when.strftime("%A")

    past = store.list_schedule_history(21)
    # Only learn from OTHER days (not a stale entry for today).
    today_key = when.strftime("%Y-%m-%d")
    past_txt = "\n\n".join(
        f"# {h.get('for_date','')} ({_weekday_of(h.get('for_date',''))})\n{h.get('raw','').strip()}"
        for h in past if h.get("for_date") != today_key and (h.get("raw") or "").strip()
    ) or "(no past schedules on record yet)"

    if not goals_text.strip() and not deadlines_text.strip() and past == []:
        return None  # nothing to build from

    user = (
        f"WEEKDAY: {weekday}\n\n"
        f"WHAT I WANT TO ACCOMPLISH (goals / open tasks, most important first):\n"
        f"{goals_text.strip() or '(none provided)'}\n\n"
        f"ACTIVE DEADLINES:\n{deadlines_text.strip() or '(none)'}\n\n"
        f"MY RECENT SCHEDULES (learn recurring items and their usual times/day-of-week):\n"
        f"{past_txt}"
    )
    try:
        raw = llm.post_text(SYSTEM, user, model=model, temperature=0.4, max_tokens=1200)
    except (llm.DigestLLMError, AttributeError):
        # Fallback: no text helper or provider down -> a minimal deterministic plan.
        raw = _fallback(goals_text, deadlines_text)
    raw = _clean(raw)
    if not _looks_like_schedule(raw):
        raw = _fallback(goals_text, deadlines_text)
        if not _looks_like_schedule(raw):
            return None
    return {"raw": raw, "parsed": schedule.parse_schedule(raw)}


def generate_and_save(when: datetime | None = None, *, model: str | None = None) -> dict | None:
    """Build today's schedule from the current goals/deadlines and save it FOR today."""
    when = when or datetime.now()
    goals_text = tasks.render_for_llm(when.date())
    rems = store.active_reminders()

    def _dd(due):
        return f" (due {due})" if due else ""
    deadlines_text = "\n".join(f"- {r.get('text','')}{_dd(r.get('due',''))}"
                               for r in rems) or ""
    gen = generate(when, goals_text=goals_text, deadlines_text=deadlines_text, model=model)
    if not gen:
        return None
    store.save_schedule(gen["raw"], gen["parsed"], for_date=when.strftime("%Y-%m-%d"))
    return gen


# --- helpers ---------------------------------------------------------------

def _weekday_of(date_str: str) -> str:
    try:
        return datetime.strptime(date_str, "%Y-%m-%d").strftime("%A")
    except (ValueError, TypeError):
        return "?"


def _clean(raw: str) -> str:
    """Strip stray code fences/prose the model may add around the planner text."""
    s = (raw or "").strip()
    if s.startswith("```"):
        s = s.split("\n", 1)[-1]
        if s.rstrip().endswith("```"):
            s = s.rstrip()[:-3]
    # Drop leading commentary lines until the first hour marker.
    lines = s.splitlines()
    start = 0
    for i, ln in enumerate(lines):
        if re.match(r"^\s*\d{1,2}\s*$", ln):
            start = i
            break
    return "\n".join(lines[start:]).strip()


def _fallback(goals_text: str, deadlines_text: str) -> str:
    """A plain morning-focus / afternoon plan when the LLM can't be used."""
    goal_lines = [ln.strip("[] ").lstrip("x ").strip()
                  for ln in (goals_text or "").splitlines() if ln.strip()][:4]
    if not goal_lines:
        return ""
    out = ["9"]
    out.append("\t'" + goal_lines[0])
    if len(goal_lines) > 1:
        out.append("10")
        out.append("\t" + goal_lines[1])
    out += ["12", "\tLunch"]
    if len(goal_lines) > 2:
        out.append("1")
        out.append("\t" + goal_lines[2])
    if len(goal_lines) > 3:
        out.append("3")
        out.append("\t" + goal_lines[3])
    return "\n".join(out)
