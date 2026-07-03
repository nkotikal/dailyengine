"""Parse the planner text format into a structured day plan + calendar events.

Format (as used by the author):
  - A bare number on its own line is an HOUR marker: 11 = 11AM, 12 = 12PM, 1 = 1PM...
    The sequence is walked so each hour is the next clock hour after the previous,
    rolling 11 -> 12 -> 1 ... -> 12 (midnight) across the day.
  - Lines indented one level under an hour are TASKS for that hour.
  - Lines indented a further level are SUBTASKS of the task above them.
  - A task/subtask whose text starts with an apostrophe (') is IMPORTANT.

Nothing is dropped: every task and subtask is preserved verbatim (minus the
leading "'" marker, which becomes the ``important`` flag).
"""

import re
from dataclasses import dataclass, field

_HOUR_RE = re.compile(r"^(1[0-2]|[1-9])$")


@dataclass
class Task:
    text: str
    important: bool = False
    critical: bool = False
    subtasks: list = field(default_factory=list)  # list[dict{text, important, critical}]

    def to_dict(self):
        return {"text": self.text, "important": self.important,
                "critical": self.critical, "subtasks": self.subtasks}


@dataclass
class Block:
    hour_label: int
    hour24: int            # 0-23 clock hour
    day_offset: int        # 0 = today, 1 = tomorrow (after midnight)
    time_str: str          # e.g. "11 AM"
    tasks: list = field(default_factory=list)  # list[Task]

    def to_dict(self):
        return {
            "hour_label": self.hour_label,
            "hour24": self.hour24,
            "day_offset": self.day_offset,
            "time_str": self.time_str,
            "tasks": [t.to_dict() for t in self.tasks],
        }


def _indent_level(line: str) -> int:
    """Leading-whitespace level: each tab or 4 spaces counts as one level."""
    n = 0
    for ch in line:
        if ch == "\t":
            n += 1
        elif ch == " ":
            n += 0.25
        else:
            break
    return int(n)


def _strip_important(text: str):
    """Return (text, important, critical). ''' (3+) = critical, ' = important."""
    text = text.strip()
    n = 0
    while n < len(text) and text[n] == "'":
        n += 1
    return text[n:].strip(), n >= 1, n >= 3


def _fmt_time(hour24: int) -> str:
    h = hour24 % 24
    suffix = "AM" if h < 12 else "PM"
    disp = h % 12
    if disp == 0:
        disp = 12
    return f"{disp} {suffix}"


def _next_hour24(prev: int | None, label: int) -> int:
    """Map an hour label (1-12) to a strictly-increasing 24h+ clock value."""
    target_mod = label % 12  # 12 -> 0
    if prev is None:
        # First hour of the day: assume the planner starts in the morning/at noon.
        return 12 if label == 12 else label
    h = prev + 1
    while h % 12 != target_mod:
        h += 1
    return h


def parse_schedule(text: str) -> dict:
    """Parse planner text into {blocks, tasks_flat, events}. Never drops content."""
    blocks: list[Block] = []
    prev24: int | None = None
    cur: Block | None = None
    last_task: Task | None = None

    for raw in (text or "").splitlines():
        if not raw.strip():
            continue
        level = _indent_level(raw)
        stripped = raw.strip()

        if level == 0 and _HOUR_RE.match(stripped):
            label = int(stripped)
            h24 = _next_hour24(prev24, label)
            prev24 = h24
            cur = Block(
                hour_label=label,
                hour24=h24 % 24,
                day_offset=h24 // 24,
                time_str=_fmt_time(h24),
            )
            blocks.append(cur)
            last_task = None
            continue

        text_val, important, critical = _strip_important(stripped)
        if not text_val:
            continue

        # A deeper-indented line is a subtask of the most recent task.
        if level >= 2 and last_task is not None:
            last_task.subtasks.append({"text": text_val, "important": important,
                                       "critical": critical})
            continue

        # Otherwise it's a task. Attach to the current hour (or an "unscheduled" block).
        if cur is None:
            cur = Block(hour_label=0, hour24=-1, day_offset=0, time_str="Unscheduled")
            blocks.append(cur)
        task = Task(text=text_val, important=important, critical=critical)
        cur.tasks.append(task)
        last_task = task

    return {
        "blocks": [b.to_dict() for b in blocks],
        "tasks_flat": _flatten(blocks),
        "events": _events(blocks),
    }


def _flatten(blocks: list[Block]) -> list:
    out = []
    for b in blocks:
        for t in b.tasks:
            out.append({
                "time": b.time_str,
                "text": t.text,
                "important": t.important,
                "subtasks": [s["text"] for s in t.subtasks],
            })
    return out


def _events(blocks: list[Block]) -> list:
    """One calendar event per top-level task; subtasks go in the description."""
    events = []
    for b in blocks:
        if b.hour24 < 0:
            continue
        for t in b.tasks:
            desc_lines = []
            for s in t.subtasks:
                mark = "* " if s.get("important") else "- "
                desc_lines.append(mark + s["text"])
            mark = "\u203c\ufe0f " if t.critical else ("\u2605 " if t.important else "")
            events.append({
                "summary": mark + t.text,
                "hour24": b.hour24,
                "minute": 0,
                "day_offset": b.day_offset,
                "duration_min": 60,
                "important": t.important,
                "description": "\n".join(desc_lines),
            })
    return events


def render_text(parsed: dict) -> str:
    """Human-readable full schedule (used in the email/text digest, no info loss)."""
    lines = []
    for b in parsed.get("blocks", []):
        if not b["tasks"]:
            continue
        lines.append(f"{b['time_str']}")
        for t in b["tasks"]:
            star = "\u203c\ufe0f " if t.get("critical") else ("\u2605 " if t["important"] else "")
            lines.append(f"  - {star}{t['text']}")
            for s in t["subtasks"]:
                sstar = "\u203c\ufe0f " if s.get("critical") else ("\u2605 " if s.get("important") else "")
                lines.append(f"      \u00b7 {sstar}{s['text']}")
    return "\n".join(lines)


def summary_counts(parsed: dict) -> dict:
    tasks = parsed.get("tasks_flat", [])
    return {
        "tasks": len(tasks),
        "important": sum(1 for t in tasks if t["important"]),
        "blocks": len([b for b in parsed.get("blocks", []) if b["tasks"]]),
    }
