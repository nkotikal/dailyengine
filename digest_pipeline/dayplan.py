"""Daily accountability: a numbered plan of today's tasks + a running score.

Turns the day into an email loop. The morning digest lists today's tasks with
stable numbers; check-in and recap emails ask which are done; replies (either
deterministic indices like ``done 1 3`` or natural language) mark them complete and
move a gentle, mostly-additive score. Finalized daily scores roll up into weekly and
monthly totals and a (multi-user-ready) leaderboard.

Design goals:
- Deterministic first: everything here works with NO LLM (indices + arithmetic).
- Gentle: points are earned for doing/reporting work; penalties are small so a rough
  day never feels punishing.
- Idempotent per day: the plan is snapshotted once each morning and reused.
"""

import re
from datetime import datetime, date, timedelta

import user_context

from . import store, tasks

# Points per task by (effective) priority - mirrors tasks._IMP_WEIGHT so critical
# work is worth double a high task.
POINTS = {"critical": 6, "high": 3, "medium": 2, "low": 1}

RESPONSE_BONUS = 2       # answered a check-in promptly
RESPONSE_LATE_BONUS = 1  # answered, but after the grace window
GRACE_MINUTES = 90       # "prompt" window after a check-in is sent
INCOMPLETE_PENALTY = 1   # gentle: points lost per task left undone at end of day
MAX_PLAN_TASKS = 8       # keep the numbered list scannable


def _key(when: datetime) -> str:
    return when.strftime("%Y-%m-%d")


def _stamp(when: datetime) -> str:
    return when.strftime("%Y-%m-%d %H:%M:%S")


def _focus_tasks(when: datetime) -> list:
    """The open top-level tasks that make up today's plan (triaged, highest first)."""
    today = when.date()
    open_tasks = [t for t in store.list_weekly_tasks() if not t.get("done")]
    scored = sorted(((t, tasks.triage_score(t, today)) for t in open_tasks),
                    key=lambda ts: -ts[1]["score"])
    focus = [t for t, s in scored if s["highlight"]]
    if not focus:  # nothing flagged urgent/important -> take the top few open tasks
        focus = [t for t, _ in scored]
    return focus[:MAX_PLAN_TASKS]


def _done_map() -> dict:
    return {t.get("id"): bool(t.get("done")) for t in store.list_weekly_tasks()}


def refresh_from_store(plan: dict) -> dict:
    """Reflect completions made elsewhere (dashboard, email 'complete') into the plan."""
    dm = _done_map()
    for t in plan.get("tasks", []):
        if t.get("node_id") in dm:
            t["done"] = dm[t["node_id"]]
    return plan


def build_day_plan(when: datetime | None = None, *, rebuild: bool = False) -> dict:
    """Snapshot today's numbered plan (idempotent per date). Returns the plan dict."""
    when = when or datetime.now()
    key = _key(when)
    plan = store.load_dayplan()
    if plan.get("date") == key and plan.get("tasks") and not rebuild:
        return refresh_from_store(plan)
    items = []
    for i, t in enumerate(_focus_tasks(when), 1):
        pr = tasks._max_priority(t)
        items.append({
            "idx": i,
            "node_id": t.get("id"),
            "text": t.get("text", ""),
            "priority": pr,
            "points": POINTS.get(pr, 2),
            "annotation": tasks.triage_score(t, when.date())["annotation"],
            "done": bool(t.get("done")),
            "done_at": "",
        })
    plan = {
        "date": key,
        "created_at": _stamp(when),
        "tasks": items,
        "checkins": [],
        "response_bonus": 0,
        "finalized": False,
    }
    store.save_dayplan(plan)
    return plan


def get_day_plan(when: datetime | None = None) -> dict:
    """Load today's plan if present (does not create one). Empty dict if none/other day."""
    when = when or datetime.now()
    plan = store.load_dayplan()
    if plan.get("date") == _key(when):
        return refresh_from_store(plan)
    return {}


def score(plan: dict) -> dict:
    """Compute the current score breakdown for a plan."""
    ptasks = plan.get("tasks", []) if plan else []
    possible = sum(t.get("points", 0) for t in ptasks)
    earned = sum(t.get("points", 0) for t in ptasks if t.get("done"))
    done_n = sum(1 for t in ptasks if t.get("done"))
    count = len(ptasks)
    bonus = int(plan.get("response_bonus", 0) or 0)
    penalty = 0
    if plan.get("finalized"):
        penalty = INCOMPLETE_PENALTY * (count - done_n)
    total = max(0, earned + bonus - penalty)
    pct = round(100 * earned / possible) if possible else 0
    return {"earned": earned, "possible": possible, "bonus": bonus,
            "penalty": penalty, "total": total, "pct": pct,
            "done": done_n, "count": count}


def mark_indices(indices, when: datetime | None = None, *, done: bool = True) -> dict:
    """Mark the given plan indices done/undone (also syncs the weekly task list)."""
    when = when or datetime.now()
    plan = build_day_plan(when)
    by_idx = {t["idx"]: t for t in plan.get("tasks", [])}
    changed = []
    for i in indices or []:
        t = by_idx.get(int(i)) if str(i).isdigit() or isinstance(i, int) else None
        if t and bool(t.get("done")) != done:
            t["done"] = done
            t["done_at"] = _stamp(when) if done else ""
            if t.get("node_id"):
                store.update_node(t["node_id"], {"done": done})
            changed.append(t["idx"])
    store.save_dayplan(plan)
    return {"changed": changed, "score": score(plan)}


def mark_node_ids(node_ids, when: datetime | None = None, *, done: bool = True) -> dict:
    """Mark plan tasks done by their weekly-task node id (used by LLM 'complete' matches)."""
    when = when or datetime.now()
    ids = {str(n) for n in (node_ids or [])}
    plan = build_day_plan(when)
    changed = []
    for t in plan.get("tasks", []):
        if t.get("node_id") in ids and bool(t.get("done")) != done:
            t["done"] = done
            t["done_at"] = _stamp(when) if done else ""
            changed.append(t["idx"])
    if changed:
        store.save_dayplan(plan)
    return {"changed": changed, "score": score(plan)}


def record_checkin(slot: str, when: datetime | None = None) -> dict:
    """Record that a check-in email was sent for ``slot`` (HH:MM)."""
    when = when or datetime.now()
    plan = build_day_plan(when)
    plan.setdefault("checkins", []).append(
        {"slot": slot, "sent_at": _stamp(when), "responded": False, "responded_at": ""})
    store.save_dayplan(plan)
    return plan


def record_response(when: datetime | None = None) -> int:
    """Credit a reply against the most recent unanswered check-in. Returns bonus added."""
    when = when or datetime.now()
    plan = get_day_plan(when)
    if not plan:
        return 0
    added = 0
    for ck in reversed(plan.get("checkins", [])):
        if not ck.get("responded"):
            ck["responded"] = True
            ck["responded_at"] = _stamp(when)
            try:
                sent = datetime.strptime(ck.get("sent_at", ""), "%Y-%m-%d %H:%M:%S")
                mins = (when - sent).total_seconds() / 60.0
            except (ValueError, TypeError):
                mins = 0
            added = RESPONSE_BONUS if mins <= GRACE_MINUTES else RESPONSE_LATE_BONUS
            plan["response_bonus"] = int(plan.get("response_bonus", 0) or 0) + added
            break
    if added:
        store.save_dayplan(plan)
    return added


def finalize_day(when: datetime | None = None) -> tuple:
    """Close out a day: apply the incomplete penalty and write it to score history.

    Returns (plan, score_dict). Idempotent - a finalized day is not re-scored.
    """
    when = when or datetime.now()
    plan = get_day_plan(when)
    if not plan:
        return {}, score({})
    if not plan.get("finalized"):
        plan["finalized"] = True
        store.save_dayplan(plan)
    sc = score(plan)
    scores = store.load_scores()
    scores[plan["date"]] = {
        "earned": sc["earned"], "possible": sc["possible"], "total": sc["total"],
        "pct": sc["pct"], "done": sc["done"], "count": sc["count"],
    }
    store.save_scores(scores)
    return plan, sc


# --- rollups ---------------------------------------------------------------

def _week_start(d: date) -> date:
    """Sunday on/before d (weeks start Sunday, matching the Korean tracker)."""
    return d - timedelta(days=(d.weekday() + 1) % 7)


def _aggregate(rows) -> dict:
    total = sum(r.get("total", 0) for r in rows)
    earned = sum(r.get("earned", 0) for r in rows)
    possible = sum(r.get("possible", 0) for r in rows)
    done = sum(r.get("done", 0) for r in rows)
    count = sum(r.get("count", 0) for r in rows)
    return {"total": total, "earned": earned, "possible": possible,
            "done": done, "count": count, "days": len(rows),
            "pct": round(100 * earned / possible) if possible else 0}


def _live_row(when: datetime) -> tuple:
    """Today's not-yet-finalized score as a (date_key, row) pair, if a plan exists."""
    plan = get_day_plan(when)
    if not plan:
        return None, None
    sc = score(plan)
    return plan["date"], {"earned": sc["earned"], "possible": sc["possible"],
                          "total": sc["total"], "pct": sc["pct"],
                          "done": sc["done"], "count": sc["count"]}


def _merged_scores(when: datetime) -> dict:
    """History plus today's live (in-progress) score so rollups feel current."""
    scores = dict(store.load_scores())
    k, row = _live_row(when)
    if k:
        scores[k] = row  # live overrides any stale finalized entry for today
    return scores


def week_summary(when: datetime | None = None) -> dict:
    when = when or datetime.now()
    ws = _week_start(when.date())
    scores = _merged_scores(when)
    rows = [v for d, v in scores.items()
            if _safe_date(d) and ws <= _safe_date(d) <= when.date()]
    out = _aggregate(rows)
    out["week_start"] = ws.strftime("%Y-%m-%d")
    return out


def month_summary(when: datetime | None = None) -> dict:
    when = when or datetime.now()
    prefix = when.strftime("%Y-%m")
    scores = _merged_scores(when)
    rows = [v for d, v in scores.items() if d.startswith(prefix)]
    out = _aggregate(rows)
    out["month"] = prefix
    return out


def recent_weeks(when: datetime | None = None, n: int = 6) -> list:
    """Totals for the last ``n`` weeks (oldest first) for trend comparison."""
    when = when or datetime.now()
    scores = _merged_scores(when)
    out = []
    ws = _week_start(when.date())
    for i in range(n - 1, -1, -1):
        start = ws - timedelta(days=7 * i)
        end = start + timedelta(days=6)
        rows = [v for d, v in scores.items()
                if _safe_date(d) and start <= _safe_date(d) <= end]
        agg = _aggregate(rows)
        agg["week_start"] = start.strftime("%Y-%m-%d")
        out.append(agg)
    return out


def _safe_date(s: str):
    try:
        return date.fromisoformat(s)
    except (ValueError, TypeError):
        return None


def leaderboard(when: datetime | None = None) -> list:
    """This week's totals across ALL users (works with a single user today).

    Iterates every user in isolation so per-user data stays separate.
    """
    when = when or datetime.now()
    rows = []
    for u in user_context.list_users():
        with user_context.using_user(u["id"]):
            wk = week_summary(when)
        rows.append({"user": u["id"], "name": u.get("name", "") or u["id"],
                     "points": wk["total"], "pct": wk["pct"], "days": wk["days"]})
    rows.sort(key=lambda r: -r["points"])
    for i, r in enumerate(rows, 1):
        r["rank"] = i
    return rows


# --- deterministic reply parsing -------------------------------------------

# Verbs that, followed by numbers, mean "these plan items are done".
_DONE_RE = re.compile(
    r"(?:^|\b)(?:done|did|finished|complete[d]?|completed|✓|x)\b[\s:]*([0-9,\sand&]+)",
    re.I)
# "1 2 3 done" (numbers first)
_DONE_TRAILING_RE = re.compile(r"^([0-9,\sand&]+?)\s*(?:are\s+)?(?:done|finished|complete[d]?)\b", re.I)
_UNDO_RE = re.compile(r"(?:^|\b)(?:undo|not\s+done|reopen|undone)\b[\s:]*([0-9,\sand&]+)", re.I)
_NUMS_RE = re.compile(r"\d+")


def _nums(blob: str) -> list:
    return [int(x) for x in _NUMS_RE.findall(blob or "")]


def parse_reply(body: str) -> dict:
    """Extract deterministic check-in commands from a reply body.

    Returns {"done": [idx...], "undo": [idx...]} - plan indices the user reported.
    Understands: 'done 1 3 5', 'done: 1,3', 'finished 2 and 4', '1 2 done',
    'undo 3'. Purely lexical - no LLM required.
    """
    done, undo = set(), set()
    for m in _DONE_RE.finditer(body or ""):
        done.update(_nums(m.group(1)))
    for m in _DONE_TRAILING_RE.finditer(body or ""):
        done.update(_nums(m.group(1)))
    for m in _UNDO_RE.finditer(body or ""):
        undo.update(_nums(m.group(1)))
    done -= undo
    return {"done": sorted(done), "undo": sorted(undo)}


def looks_like_checkin(body: str) -> bool:
    """True if the reply is (mostly) a terse check-in command we can apply offline.

    Used so an OFFLINE send can safely consume 'done 1 3' replies without an LLM,
    while leaving prose reflections for the LLM pass later.
    """
    body = (body or "").strip()
    if not body or len(body) > 160:
        return False
    parsed = parse_reply(body)
    if not (parsed["done"] or parsed["undo"]):
        return False
    # Mostly digits/command words -> safe to treat as a pure check-in.
    letters = re.sub(r"[^a-z]", "", body.lower())
    cmd_letters = re.sub(r"[^a-z]", "",
                         re.sub(r"(done|did|finished|complete[d]?|undo|reopen|and|not|are)",
                                "", body.lower()))
    return len(cmd_letters) <= 6  # little non-command text remains


def apply_reply(body: str, when: datetime | None = None) -> dict:
    """Apply a deterministic check-in reply: mark indices + credit the response."""
    when = when or datetime.now()
    parsed = parse_reply(body)
    result = {"done": [], "undo": [], "bonus": 0}
    if parsed["done"]:
        result["done"] = mark_indices(parsed["done"], when, done=True)["changed"]
    if parsed["undo"]:
        result["undo"] = mark_indices(parsed["undo"], when, done=False)["changed"]
    result["bonus"] = record_response(when)
    result["score"] = score(get_day_plan(when))
    return result
