"""Weekly task list with nesting: derive concrete tasks from the 'Goals this week'
box, where tab-indented lines under a line are subtasks.

The freeform weekly-goals text is the seed. ``derive`` breaks it into discrete,
actionable tasks (via the LLM, with a deterministic outline-parse fallback),
preserving nesting (parent task -> subtasks). The list lives in ``store`` and is
fully editable, and is woven into the digest where open tasks drive "Today's Focus".

``parse_outline`` is reused to render the daily/standing tasks and goals boxes with
their nesting too.
"""

import re
from datetime import date

from . import llm, store

DERIVE_SYSTEM = """\
You turn a person's weekly goals/notes into a concrete, actionable task list for
the week. The input may be NESTED: lines indented (tabbed) under a line are
SUBTASKS of that line. Preserve that structure. Respond with ONLY a JSON object:

{ "tasks": [ {"text": "a concrete task starting with a verb", "priority": "critical|high|medium|low",
              "due": "YYYY-MM-DD or empty", "est_minutes": 0,
              "subtasks": [ {"text": "a concrete subtask", "priority": "critical|high|medium|low",
                             "subtasks": [ {"text": "deeper step"} ] } ] } ] }

Subtasks may nest to ANY depth - mirror however deep the input is tabbed.
PRIORITY MARKERS: a line starting with ''' (triple apostrophe) is CRITICAL (double
priority); a single ' is high. Preserve that as the item's "priority".

RULES:
- Keep the nesting from the input: a tabbed line becomes a subtask of the line above.
- You may also break a broad parent into subtasks when it clearly implies steps.
- Preserve every distinct intention - do not drop anything.
- Mark items the user emphasized (leading apostrophe, or words like deadline/due/
  submit/important) as "high".
- If the text states a deadline ("by Friday", "due 7/3"), set "due" to that calendar
  date in YYYY-MM-DD; otherwise leave it "". If it states an effort/time estimate
  ("~2h", "30 min"), set "est_minutes" to that many minutes; otherwise 0.
- Keep each item one short line. "subtasks" is optional/empty when there are none."""


# --- estimated time helpers ------------------------------------------------

def parse_est(value) -> int:
    """Parse an effort estimate into minutes. Accepts '2h', '90m', '1.5h', '2h30m',
    or a bare number (minutes). Returns 0 if unparseable/empty."""
    if value is None:
        return 0
    if isinstance(value, (int, float)):
        return max(0, int(value))
    s = str(value).strip().lower()
    if not s:
        return 0
    total = 0.0
    matched = False
    for num, unit in re.findall(r"(\d+(?:\.\d+)?)\s*(h|hr|hrs|hour|hours|m|min|mins|minutes)?", s):
        if not num:
            continue
        n = float(num)
        if unit and unit.startswith("h"):
            total += n * 60
        elif unit and unit.startswith("m"):
            total += n
        else:
            total += n  # bare number -> minutes
        matched = True
    return int(round(total)) if matched else 0


def fmt_est(minutes: int) -> str:
    minutes = int(minutes or 0)
    if minutes <= 0:
        return ""
    h, m = divmod(minutes, 60)
    if h and m:
        return f"{h}h {m}m"
    if h:
        return f"{h}h"
    return f"{m}m"


# --- outline parsing (tabs -> nesting) -------------------------------------

def _indent_level(line: str) -> int:
    n = 0
    for ch in line:
        if ch == "\t":
            n += 1
        elif ch == " ":
            n += 0.25
        else:
            break
    return int(n)


def _strip_priority(s: str):
    """Leading apostrophes set priority: ''' (3+) = critical, ' (1-2) = high, else medium."""
    s = s.strip()
    n = 0
    while n < len(s) and s[n] == "'":
        n += 1
    pr = "critical" if n >= 3 else ("high" if n >= 1 else "medium")
    return s[n:].strip(), pr, n >= 1


def parse_outline(text: str) -> list:
    """Parse indented text into a tree: [{text, important, priority, children:[...]}]."""
    roots, stack = [], []  # stack: list of (level, node)
    for raw in (text or "").splitlines():
        if not raw.strip():
            continue
        level = _indent_level(raw)
        s = raw.strip().lstrip("-*\u2022").strip()
        s, priority, important = _strip_priority(s)
        if not s:
            continue
        node = {"text": s, "important": important, "priority": priority, "children": []}
        while stack and stack[-1][0] >= level:
            stack.pop()
        (stack[-1][1]["children"] if stack else roots).append(node)
        stack.append((level, node))
    return roots


def _children_to_subtasks(children: list) -> list:
    """Convert outline children into a (recursive) subtask tree, preserving depth + priority."""
    return [{"text": c["text"], "priority": c.get("priority", "medium"),
             "subtasks": _children_to_subtasks(c["children"])} for c in children]


def outline_items(text: str, *, top_priority_from_important: bool = True) -> list:
    """Flat [{text, priority}] for digest sections, with indentation showing depth."""
    def walk(nodes, depth):
        items = []
        for n in nodes:
            prefix = ("    " * depth) + ("\u21B3 " if depth else "")
            np = n.get("priority", "medium")
            if depth == 0:
                pr = np
            else:
                pr = np if np in ("critical", "high") else "low"
            items.append({"text": prefix + n["text"], "priority": pr})
            items += walk(n["children"], depth + 1)
        return items
    return walk(parse_outline(text), 0)


# --- derivation ------------------------------------------------------------

def _fallback(weekly_text: str) -> list:
    """Deterministic: top-level outline nodes -> tasks; descendants -> nested subtasks."""
    tasks = []
    for node in parse_outline(weekly_text):
        tasks.append({
            "text": node["text"],
            "priority": node.get("priority", "medium"),
            "due": "", "est_minutes": 0,
            "subtasks": _children_to_subtasks(node["children"]),
        })
    return tasks


_VALID_PR = ("critical", "high", "medium", "low")


def _norm_subs(items) -> list:
    out = []
    for s in items or []:
        if isinstance(s, dict) and (s.get("text") or "").strip():
            pr = str(s.get("priority", "medium")).lower()
            out.append({"text": s["text"].strip(),
                        "priority": pr if pr in _VALID_PR else "medium",
                        "subtasks": _norm_subs(s.get("subtasks"))})
        elif isinstance(s, str) and s.strip():
            out.append({"text": s.strip(), "subtasks": []})
    return out


def _normalize_derived(raw_tasks) -> list:
    out = []
    for t in (raw_tasks or []):
        if isinstance(t, str) and t.strip():
            out.append({"text": t.strip(), "priority": "medium",
                        "due": "", "est_minutes": 0, "subtasks": []})
            continue
        if not isinstance(t, dict) or not t.get("text"):
            continue
        pr = str(t.get("priority", "medium")).lower()
        due = str(t.get("due", "") or "").strip()
        if due and not re.match(r"^\d{4}-\d{2}-\d{2}$", due):
            due = ""  # only accept ISO dates
        out.append({"text": str(t["text"]).strip(),
                    "priority": pr if pr in _VALID_PR else "medium",
                    "due": due, "est_minutes": parse_est(t.get("est_minutes")),
                    "subtasks": _norm_subs(t.get("subtasks"))})
    return out


def derive(weekly_text: str, *, model: str | None = None, use_llm: bool = True) -> list:
    """Return [{text, priority, subtasks:[{text}]}] derived from the weekly text."""
    weekly_text = (weekly_text or "").strip()
    if not weekly_text:
        return []
    if not use_llm or not llm.have_key():
        return _fallback(weekly_text)
    try:
        data = llm.post_json(DERIVE_SYSTEM, "WEEKLY GOALS / NOTES (tabs = subtasks):\n" + weekly_text,
                             model=model, temperature=0.2, max_tokens=2000)
    except llm.DigestLLMError:
        return _fallback(weekly_text)
    tasks = _normalize_derived(data.get("tasks"))
    return tasks or _fallback(weekly_text)


def derive_and_merge(weekly_text: str, *, model: str | None = None,
                     use_llm: bool = True) -> dict:
    derived = derive(weekly_text, model=model, use_llm=use_llm)
    return store.merge_weekly_tasks(derived, source="derived")


def derive_and_replace(weekly_text: str, *, model: str | None = None,
                       use_llm: bool = True) -> dict:
    """Refresh the whole weekly task list from a new suite (e.g. a new week).

    Derives the new tasks FIRST, then clears the existing weekly tasks and installs
    the new set. Reminders live in a separate store and are never touched. If the
    new text yields no tasks, the current list is left intact (nothing is wiped).
    """
    derived = derive(weekly_text, model=model, use_llm=use_llm)
    if not derived:
        return {"added": 0, "added_subtasks": 0, "removed": 0,
                "tasks": store.list_weekly_tasks(),
                "error": "No tasks could be derived from the text; kept existing tasks."}
    removed = store.clear_weekly_tasks(False)  # tasks only; reminders untouched
    result = store.merge_weekly_tasks(derived, source="derived")
    result["removed"] = removed
    return result


# --- triage ----------------------------------------------------------------

_PR_ORDER = {"critical": -1, "high": 0, "medium": 1, "low": 2}
_IMP_WEIGHT = {"critical": 6, "high": 3, "medium": 2, "low": 1}  # critical = double of high


def _max_priority(task: dict) -> str:
    """Highest priority across the task and all its subtasks (critical bubbles up)."""
    best = task.get("priority", "medium")

    def walk(subs):
        nonlocal best
        for s in subs or []:
            if _IMP_WEIGHT.get(s.get("priority", "medium"), 2) > _IMP_WEIGHT.get(best, 2):
                best = s.get("priority", "medium")
            walk(s.get("subtasks"))
    walk(task.get("subtasks"))
    return best


def _due_days(due: str, today: date):
    if not due:
        return None
    try:
        return (date.fromisoformat(due) - today).days
    except (ValueError, TypeError):
        return None


def _earliest_due_days(task: dict, today: date):
    """Most-imminent due across the task AND all its (nested) subtasks."""
    best = _due_days(task.get("due", ""), today)

    def walk(subs):
        nonlocal best
        for s in subs or []:
            d = _due_days(s.get("due", ""), today)
            if d is not None and (best is None or d < best):
                best = d
            walk(s.get("subtasks"))
    walk(task.get("subtasks"))
    return best


def _due_short(due: str, today: date) -> str:
    d = _due_days(due, today)
    if d is None:
        return ""
    if d < 0:
        return "OVERDUE"
    if d == 0:
        return "today"
    if d == 1:
        return "tomorrow"
    return f"in {d}d"


def triage_score(task: dict, today: date) -> dict:
    """Return {score, urgent, reasons, annotation} for an open task.

    Score blends importance, due-date proximity, and (for soon+large work) effort.
    """
    eff_priority = _max_priority(task)
    imp = _IMP_WEIGHT.get(eff_priority, 2)
    score = imp * 10
    reasons = []
    if eff_priority == "critical":
        score += 35  # floor so critical reliably leads even without a deadline
        reasons.append("CRITICAL (double priority)")
    # Urgency is driven by the most imminent due date in the whole subtree, so a
    # subtask due today makes its parent task urgent too.
    days = _earliest_due_days(task, today)
    own_days = _due_days(task.get("due", ""), today)
    from_sub = days is not None and days != own_days
    urgent = False
    if days is not None:
        tag = " (subtask)" if from_sub else ""
        if days < 0:
            score += 100; reasons.append(f"overdue by {abs(days)}d{tag}"); urgent = True
        elif days == 0:
            score += 80; reasons.append(f"due today{tag}"); urgent = True
        elif days == 1:
            score += 60; reasons.append(f"due tomorrow{tag}"); urgent = True
        elif days <= 3:
            score += 40; reasons.append(f"due in {days}d{tag}"); urgent = True
        elif days <= 7:
            score += 20; reasons.append(f"due in {days}d{tag}")
        else:
            score += 5; reasons.append(f"due in {days}d{tag}")
        est = int(task.get("est_minutes") or 0)
        if days <= 3 and est >= 120:
            score += 15; reasons.append("sizable & soon")
    if eff_priority == "high":
        reasons.append("high importance")
    # Build a compact annotation: due + estimate.
    bits = []
    if days is not None:
        if days < 0:
            bits.append("OVERDUE")
        elif days == 0:
            bits.append("today")
        elif days == 1:
            bits.append("tomorrow")
        else:
            bits.append(f"in {days}d")
    est_str = fmt_est(task.get("est_minutes"))
    if est_str:
        bits.append(f"~{est_str}")
    annotation = ", ".join(bits)
    # Highlight-worthy: imminent (<=3 days incl. overdue) OR high/critical importance.
    highlight = urgent or eff_priority in ("high", "critical")
    return {"score": score, "urgent": urgent, "highlight": highlight,
            "eff_priority": eff_priority, "reasons": reasons, "annotation": annotation}


def _open(tasks_list):
    return [t for t in tasks_list if not t.get("done")]


def load_summary(today: date | None = None, capacity_minutes: int = 360) -> dict:
    """Focus/headspace summary: how much is on the plate vs. a realistic daily capacity.

    Supports the "protect your headspace" philosophy - surfaces over-commitment so the
    day can be deliberately trimmed instead of silently overwhelming.
    """
    today = today or date.today()
    open_tasks = _open(store.list_weekly_tasks())
    focus = [t for t in open_tasks if triage_score(t, today)["highlight"]]
    focus_min = sum(int(t.get("est_minutes") or 0) for t in focus)
    open_min = sum(int(t.get("est_minutes") or 0) for t in open_tasks)
    overloaded = capacity_minutes > 0 and focus_min > capacity_minutes
    return {
        "focus_count": len(focus),
        "open_count": len(open_tasks),
        "focus_minutes": focus_min,
        "open_minutes": open_min,
        "capacity_minutes": capacity_minutes,
        "overloaded": overloaded,
        "focus_est": fmt_est(focus_min),
        "open_est": fmt_est(open_min),
    }


# --- rendering -------------------------------------------------------------

def _task_line(t, today, *, with_annotation):
    pr = _max_priority(t)
    star = "\u203c\ufe0f " if pr == "critical" else ("(!) " if pr == "high" else "")
    text = star + t.get("text", "")
    if with_annotation:
        ann = triage_score(t, today)["annotation"]
        if ann:
            text += f"  ({ann})"
    return text


def build_sections(today: date | None = None, capacity_minutes: int = 360) -> list:
    """Triaged digest sections shaped to protect headspace.

    Leads with one clear focus, highlights only important/imminent work, surfaces the
    day's load vs. capacity (a gentle nudge if overcommitted), and tucks the rest into
    a compact list so nothing is lost without cluttering the mind.
    """
    today = today or date.today()
    items = store.list_weekly_tasks()
    if not items:
        return []
    open_tasks = _open(items)
    scored = [(t, triage_score(t, today)) for t in open_tasks]
    scored.sort(key=lambda ts: -ts[1]["score"])

    focus = [(t, s) for t, s in scored if s["highlight"]][:6]
    focus_ids = {t["id"] for t, _ in focus}
    rest = [(t, s) for t, s in scored if t["id"] not in focus_ids]

    sections = []
    if focus:
        fitems = []
        # The single most important thing, called out first to anchor the day.
        top_t, _ = focus[0]
        fitems.append({"text": "\u2b50 One thing: " + top_t.get("text", ""), "priority": "high"})
        def emit_subs(node, depth):
            for sub in node.get("subtasks", []):
                if sub.get("done"):
                    continue  # hide completed subtasks in the focus area (less clutter)
                dtag = _due_short(sub.get("due", ""), today)
                txt = ("    " * depth) + "\u21B3 " + sub.get("text", "")
                if dtag:
                    txt += f" ({dtag})"
                fitems.append({"text": txt,
                               "priority": "high" if dtag in ("OVERDUE", "today") else "low"})
                emit_subs(sub, depth + 1)
        for t, s in focus:
            if s["eff_priority"] == "critical":
                pr = "critical"
            elif s["urgent"] or s["eff_priority"] == "high":
                pr = "high"
            else:
                pr = "medium"
            fitems.append({"text": _task_line(t, today, with_annotation=True), "priority": pr})
            emit_subs(t, 1)
        # Headspace: load vs capacity.
        load = load_summary(today, capacity_minutes)
        if load["focus_est"]:
            cap = fmt_est(capacity_minutes)
            note = f"Focus load: ~{load['focus_est']} across {load['focus_count']} task(s)"
            if load["overloaded"]:
                note += (f" \u2014 over your ~{cap} of focus time. Pick the top 1-2 and "
                         "let the rest wait; a clear, finishable day beats an overloaded one.")
            fitems.append({"text": note, "priority": "low"})
        sections.append({"title": "Priorities \u2014 focus now", "icon": "\U0001F3AF",
                         "items": fitems})

    # The rest of this week (compact: parent lines only, with light annotations).
    if rest:
        ritems = [{"text": _task_line(t, today, with_annotation=True),
                   "priority": "low"} for t, _ in rest]
        sections.append({"title": "Rest of this week", "icon": "\U0001F4CB", "items": ritems})

    done_n = sum(1 for t in items if t.get("done"))
    if done_n:
        sections.append({"title": "Completed", "icon": "\u2714\uFE0F",
                         "items": [{"text": f"{done_n} task(s) done this week \u2014 nice.",
                                    "priority": "low"}]})
    return sections


def render_for_llm(today: date | None = None) -> str:
    """Rich, triaged text of the weekly tasks for the composer (marks FOCUS items)."""
    today = today or date.today()
    items = store.list_weekly_tasks()
    if not items:
        return ""
    open_tasks = _open(items)
    scored = sorted(((t, triage_score(t, today)) for t in open_tasks),
                    key=lambda ts: -ts[1]["score"])
    focus_ids = {t["id"] for t, s in scored if s["highlight"]}
    sm = summary()
    lines = [f"PROGRESS: top-level entries are CATEGORIES/areas (not tasks). Across "
             f"{sm['areas']} areas, {sm['leaf_done']}/{sm['leaf_total']} concrete tasks "
             f"are done. Frame progress by area, not by counting categories as tasks."]
    for t, s in scored:
        tag = "[FOCUS] " if t["id"] in focus_ids else ""
        meta = []
        meta.append(f"importance={t.get('priority','medium')}")
        if t.get("due"):
            meta.append(f"due={t['due']}")
        if t.get("est_minutes"):
            meta.append(f"est={fmt_est(t['est_minutes'])}")
        if s["reasons"]:
            meta.append("; ".join(s["reasons"]))
        lines.append(f"[ ] {tag}{t.get('text','')}  <{', '.join(meta)}>")

        def emit(node, depth):
            for sub in node.get("subtasks", []):
                sbox = "[x]" if sub.get("done") else "[ ]"
                due = f"  <due={sub['due']}>" if sub.get("due") else ""
                lines.append(("    " * depth) + f"{sbox} {sub.get('text','')}{due}")
                emit(sub, depth + 1)
        emit(t, 1)
    done = [t for t in items if t.get("done")]
    if done:
        lines.append(f"(completed this week: {len(done)})")
    return "\n".join(lines)


def _count_subs(nodes):
    total = done = 0
    for s in nodes or []:
        total += 1
        if s.get("done"):
            done += 1
        ct, cd = _count_subs(s.get("subtasks"))
        total += ct
        done += cd
    return total, done


def _count_leaves(nodes):
    """Count LEAF items (the actual to-dos). Top-level entries are categories, and a
    node with children is a grouping, so only childless nodes count as real tasks."""
    total = done = 0
    for n in nodes or []:
        kids = n.get("subtasks") or []
        if kids:
            ct, cd = _count_leaves(kids)
            total += ct
            done += cd
        else:
            total += 1
            if n.get("done"):
                done += 1
    return total, done


def summary() -> dict:
    items = store.list_weekly_tasks()
    done = sum(1 for t in items if t.get("done"))
    subs = subs_done = 0
    for t in items:
        ct, cd = _count_subs(t.get("subtasks"))
        subs += ct
        subs_done += cd
    leaf_total, leaf_done = _count_leaves(items)
    return {"total": len(items), "done": done, "open": len(items) - done,
            "subtasks": subs, "subtasks_done": subs_done,
            "areas": len(items), "leaf_total": leaf_total, "leaf_done": leaf_done}
