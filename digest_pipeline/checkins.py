"""Email-based accountability: the end-of-day recap.

The morning digest carries a numbered plan you steer by replying (``done 1 3``,
handled in ``inbox_commands`` + ``dayplan``). At night, an opt-in recap email closes
the day: today's schedule (done/open), this week's tasks, the score, and the weekly
standing, with a nudge to plan tomorrow.

The recap is opt-in (``eod_recap_enabled``) and only fires after the morning digest
has gone out, so it never front-runs the brief.
"""

import html as _html
from datetime import datetime

import user_context

from . import dayplan, email_send, store


def _esc(s) -> str:
    return _html.escape(str(s or ""))


def _minutes_since_slot(slot: str, when: datetime):
    try:
        hh, mm = (int(x) for x in str(slot).split(":", 1))
    except (ValueError, TypeError):
        return None
    target = when.replace(hour=hh, minute=mm, second=0, microsecond=0)
    return (when - target).total_seconds() / 60.0


def _hhmm_passed(slot: str, when: datetime) -> bool:
    m = _minutes_since_slot(slot, when)
    return m is not None and m >= 0


# --- shared styling --------------------------------------------------------

_BG = "#0a0c18"
_CARD = "#161a2e"
_TEXT = "#f1f4ff"
_SOFT = "#c3c9de"
_FAINT = "#828aa6"
_FAM = ("-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif")
_ACCENT = "#7c9bff"
_OK = "#5fe6b4"


def _shell(inner: str) -> str:
    return (f'<div style="margin:0;padding:0;background:{_BG};">'
            f'<div style="max-width:560px;margin:0 auto;padding:18px 14px 28px;'
            f'font-family:{_FAM};">{inner}'
            f'<div style="text-align:center;color:{_FAINT};font-size:12px;margin:20px 6px 4px;">'
            f'\u2728 Daily Digest \u00b7 reply to update \u2728</div></div></div>')


def _score_strip(sc: dict) -> str:
    return (f'<div style="display:flex;gap:8px;margin:12px 0 6px;">'
            f'<div style="flex:1;background:{_CARD};border:1px solid #2a2f4d;border-radius:12px;'
            f'padding:12px;text-align:center;"><div style="font-size:22px;font-weight:800;color:{_TEXT};">'
            f'{sc["total"]}</div><div style="font-size:11px;color:{_SOFT};">points today</div></div>'
            f'<div style="flex:1;background:{_CARD};border:1px solid #2a2f4d;border-radius:12px;'
            f'padding:12px;text-align:center;"><div style="font-size:22px;font-weight:800;color:{_OK};">'
            f'{sc["done"]}/{sc["count"]}</div><div style="font-size:11px;color:{_SOFT};">tasks done</div></div>'
            f'<div style="flex:1;background:{_CARD};border:1px solid #2a2f4d;border-radius:12px;'
            f'padding:12px;text-align:center;"><div style="font-size:22px;font-weight:800;color:{_ACCENT};">'
            f'{sc["pct"]}%</div><div style="font-size:11px;color:{_SOFT};">of plan</div></div></div>')


# --- recap (focused on the WEEKLY tasks) -----------------------------------

def _weekly_task_groups() -> list:
    """Weekly tasks grouped by category -> the ACTUAL tasks (one tab in).

    Top-level entries are categories (e.g. AMD, neuromorphic); their direct children
    are the real tasks. Deeper descendants are extra detail, not listed as tasks. A
    bare top-level entry with no children is treated as its own task.
    """
    groups = []
    for node in store.list_weekly_tasks():
        subs = [s for s in (node.get("subtasks") or []) if (s.get("text") or "").strip()]
        actual = subs if subs else [node]
        items = [{"text": s.get("text", ""),
                  "done": bool(s.get("done")),
                  "detail": [d.get("text", "") for d in (s.get("subtasks") or [])
                             if (d.get("text") or "").strip()]}
                 for s in actual]
        if items:
            groups.append({"category": node.get("text", ""), "tasks": items})
    return groups


def _weekly_groups_html(groups: list) -> str:
    if not groups:
        return f'<div style="color:{_FAINT};font-size:14px;padding:6px 0;">\u2014 no weekly tasks set \u2014</div>'
    out = []
    for g in groups:
        done_n = sum(1 for t in g["tasks"] if t["done"])
        out.append(
            f'<div style="margin-top:12px;font-size:12px;font-weight:800;text-transform:uppercase;'
            f'letter-spacing:.5px;color:{_ACCENT};">{_esc(g["category"])} '
            f'<span style="color:{_FAINT};">({done_n}/{len(g["tasks"])})</span></div>')
        for t in g["tasks"]:
            if t["done"]:
                mark, style = f'<span style="color:{_OK};">\u2714</span>', f'color:{_FAINT};text-decoration:line-through;'
            else:
                mark, style = f'<span style="color:{_FAINT};">\u25cb</span>', f'color:{_TEXT};'
            out.append(
                f'<div style="padding:6px 0;border-top:1px solid rgba(255,255,255,0.06);'
                f'font-size:14.5px;line-height:1.5;{style}">'
                f'<span style="display:inline-block;width:22px;">{mark}</span>{_esc(t["text"])}</div>')
    return "".join(out)


def _today_tasks_html(plan: dict) -> str:
    """The day's schedule tasks (done/open) - what the recap is 'based around'."""
    tasks_ = plan.get("tasks", [])
    if not tasks_:
        return f'<div style="color:{_FAINT};font-size:14px;padding:6px 0;">\u2014 no schedule for today \u2014</div>'
    out = []
    for t in tasks_:
        if t.get("done"):
            mark, style = f'<span style="color:{_OK};">\u2714</span>', f'color:{_FAINT};text-decoration:line-through;'
        else:
            mark, style = f'<span style="color:{_FAINT};">\u25cb</span>', f'color:{_TEXT};'
        when_tag = (f' <span style="color:{_FAINT};font-size:12px;">({_esc(t["annotation"])})</span>'
                    if t.get("annotation") else "")
        out.append(
            f'<div style="padding:6px 0;border-top:1px solid rgba(255,255,255,0.06);'
            f'font-size:14.5px;line-height:1.5;{style}">'
            f'<span style="display:inline-block;width:22px;">{mark}</span>{_esc(t["text"])}{when_tag}</div>')
    return "".join(out)


def build_recap(plan: dict, sc: dict, when: datetime) -> dict:
    week = dayplan.week_summary(when)
    board = dayplan.leaderboard(when)
    rank = next((r["rank"] for r in board if r.get("points") is not None
                 and r["name"] and _is_me(r)), None)

    groups = _weekly_task_groups()
    leaf_total = sum(len(g["tasks"]) for g in groups)
    leaf_done = sum(1 for g in groups for t in g["tasks"] if t["done"])
    subject = (f"\U0001F319 Day recap \u2014 {leaf_done}/{leaf_total} weekly tasks"
               f" \u00b7 {sc['done']}/{sc['count']} scheduled today")

    bonus_bit = f' \u00b7 +{sc["bonus"]} bonus' if sc["bonus"] else ""
    penalty_bit = (f' \u00b7 -{sc["penalty"]} for {sc["count"] - sc["done"]} unfinished'
                   if sc["penalty"] else "")
    breakdown = (f'<div style="font-size:13.5px;color:{_SOFT};line-height:1.9;">'
                 f'Today you finished <strong style="color:{_TEXT};">{sc["done"]}/{sc["count"]}</strong> '
                 f'scheduled items ({sc["total"]} pts{bonus_bit}{penalty_bit}).</div>')
    week_line = (f'<div style="margin-top:6px;font-size:13.5px;color:{_SOFT};">This week: '
                 f'<strong style="color:{_TEXT};">{week["total"]} pts</strong> over {week["days"]} day(s)'
                 f'{f" \u00b7 you\u2019re #{rank} on the leaderboard" if rank else ""}.</div>')

    inner = (
        f'<div style="background:linear-gradient(135deg,#241a3e,#1a2340);border-radius:18px;'
        f'padding:22px;text-align:center;"><div style="font-size:12px;letter-spacing:3px;'
        f'text-transform:uppercase;color:{_ACCENT};font-weight:700;">Day recap</div>'
        f'<div style="font-size:26px;font-weight:800;color:#fff;margin-top:6px;">{leaf_done}/{leaf_total} weekly tasks</div>'
        f'<div style="font-size:13px;color:{_SOFT};margin-top:2px;">{when.strftime("%A, %b %d")}</div></div>'
        f'{_score_strip(sc)}'
        f'<div style="background:{_CARD};border:1px solid #2a2f4d;border-radius:16px;padding:8px 16px 14px;margin:10px 4px;">'
        f'<div style="font-size:13px;font-weight:800;text-transform:uppercase;letter-spacing:.5px;color:{_ACCENT};margin-top:8px;">Today\u2019s schedule</div>'
        f'{_today_tasks_html(plan)}</div>'
        f'<div style="background:{_CARD};border:1px solid #2a2f4d;border-radius:16px;padding:8px 16px 14px;margin:10px 4px;">'
        f'<div style="font-size:13px;font-weight:800;text-transform:uppercase;letter-spacing:.5px;color:{_OK};margin-top:8px;">This week\u2019s tasks</div>'
        f'{_weekly_groups_html(groups)}</div>'
        f'<div style="padding:0 6px;">{breakdown}{week_line}</div>'
        f'<div style="margin:14px 4px 0;padding:14px 16px;border-radius:12px;'
        f'background:linear-gradient(135deg,rgba(124,155,255,0.12),rgba(255,158,199,0.12));'
        f'border:1px solid #2a2f4d;font-size:14px;line-height:1.6;color:{_SOFT};">'
        f'\U0001F4AC <strong style="color:{_TEXT};">Reply</strong> to log what you finished, reflect on the '
        f'day, or plan tomorrow ("tomorrow: deep work on the compiler at 9"). It shapes your morning brief.</div>')
    return {"subject": subject, "html": _shell(inner), "text": _recap_text(plan, sc, week)}


def _is_me(row) -> bool:
    try:
        return row.get("user") == user_context.current_user_id()
    except Exception:  # noqa: BLE001
        return False


def _recap_text(plan: dict, sc: dict, week: dict) -> str:
    groups = _weekly_task_groups()
    leaf_total = sum(len(g["tasks"]) for g in groups)
    leaf_done = sum(1 for g in groups for t in g["tasks"] if t["done"])
    lines = [f"DAY RECAP  -  {plan.get('date','')}", "=" * 40,
             f"Today (schedule): {sc['done']}/{sc['count']} done | {sc['total']} pts",
             f"This week: {week['total']} pts over {week['days']} day(s).", "",
             "TODAY'S SCHEDULE:"]
    if plan.get("tasks"):
        for t in plan["tasks"]:
            box = "[x]" if t.get("done") else "[ ]"
            tag = f"  ({t['annotation']})" if t.get("annotation") else ""
            lines.append(f"  {box} {t['text']}{tag}")
    else:
        lines.append("  (no schedule for today)")
    lines += ["", f"THIS WEEK'S TASKS ({leaf_done}/{leaf_total} done):"]
    if not groups:
        lines.append("  (no weekly tasks set)")
    for g in groups:
        lines.append(f"  {g['category']}:")
        for t in g["tasks"]:
            box = "[x]" if t["done"] else "[ ]"
            lines.append(f"    {box} {t['text']}")
    lines += ["", "Reply to log what you finished, reflect, or plan tomorrow."]
    return "\n".join(lines)


# --- dispatch --------------------------------------------------------------

def _ready(cfg: dict, when: datetime) -> tuple:
    """Common gate: email set up, a day plan exists, and the morning brief already sent."""
    if not (cfg.get("email_to") or "").strip() or not email_send.is_configured():
        return False, None
    plan = dayplan.get_day_plan(when)
    if not plan or not plan.get("tasks"):
        return False, None
    if store.load_state().get("last_sent_date") != when.strftime("%Y-%m-%d"):
        return False, None  # don't send the recap before the morning digest
    return True, plan


def send_recap_if_due(when: datetime | None = None) -> dict:
    """Send the end-of-day recap for the active user (once/day) and finalize the score."""
    when = when or datetime.now()
    cfg = store.load_config()
    if not cfg.get("eod_recap_enabled"):
        return {"sent": 0, "reason": "disabled"}
    ok, plan = _ready(cfg, when)
    if not ok:
        return {"sent": 0, "reason": "not ready"}
    if not _hhmm_passed(cfg.get("eod_recap_time") or "21:00", when):
        return {"sent": 0, "reason": "before recap time"}
    today = when.strftime("%Y-%m-%d")
    claim = f"recap-{today}"
    if not store.claim_once(claim):  # cross-process once-per-day guard
        return {"sent": 0, "reason": "already sent"}
    plan, sc = dayplan.finalize_day(when)
    msg = build_recap(plan, sc, when)
    try:
        email_send.send_email(to_addr=cfg["email_to"], subject=msg["subject"],
                              html=msg["html"], text=msg["text"])
    except email_send.EmailError as exc:
        store.release_claim(claim)  # let a later tick retry
        return {"sent": 0, "reason": f"error: {exc}"}
    return {"sent": 1, "reason": "ok"}


def run_interactivity_for_all_users(when: datetime | None = None) -> list:
    """Dispatch the end-of-day recap for every user (isolated). Safe to call each tick."""
    when = when or datetime.now()
    results = []
    if not email_send.is_configured():
        return results
    for u in user_context.list_users():
        with user_context.using_user(u["id"]):
            try:
                rc = send_recap_if_due(when)
            except Exception as exc:  # noqa: BLE001 - isolate per-user failures
                rc = {"sent": 0, "reason": f"error: {exc}"}
        results.append({"user": u["id"], "recap": rc})
    return results
