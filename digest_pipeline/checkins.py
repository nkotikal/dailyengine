"""Email-based accountability loop: progress check-ins + an end-of-day recap.

Through the day (at the user's configured slots) a short check-in email lists the
numbered tasks from today's plan and the running score, and asks which are done.
Replies are applied deterministically (``done 1 3``) or via the LLM reply parser.
At night a recap email closes the day: what got done, the score, and the weekly
standing, with a nudge to plan tomorrow.

Everything is opt-in (``checkins_enabled`` / ``eod_recap_enabled``) and only fires
after the morning digest has gone out, so it never front-runs the brief.
"""

import html as _html
import re
from datetime import datetime
from urllib.parse import quote

import user_context

from . import dayplan, email_send, store


def _esc(s) -> str:
    return _html.escape(str(s or ""))


# A check-in fires at its slot and for a window afterward (so a machine that boots
# a bit late still sends it), but not hours later - avoids a 2pm boot firing the
# 11:30 nudge. The recap has no late cap (you always want the day's wrap-up).
CHECKIN_MAX_LATE_MIN = 75


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


def _checkin_due_now(slot: str, when: datetime) -> bool:
    m = _minutes_since_slot(slot, when)
    return m is not None and 0 <= m <= CHECKIN_MAX_LATE_MIN


def _mailto(subject: str, body: str) -> str:
    """A one-tap reply link that lands back in the digest mailbox."""
    to = email_send.from_address()
    return (f"mailto:{quote(to)}?subject={quote(subject)}&body={quote(body)}")


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


def _task_rows(items: list, reply_subject: str, *, interactive: bool) -> str:
    """Clean, table-based rows (robust across email clients): a left status marker,
    a time pill, the task, optional detail, and a right-aligned one-tap 'done' link."""
    if not items:
        return ""
    rows = []
    for t in items or []:
        done = t.get("done")
        pr = t.get("priority")
        accent = "#ff8f9c" if pr in ("critical", "high") else _ACCENT
        # left status
        if done:
            marker = f'<span style="color:{_OK};font-size:16px;font-weight:800;">\u2713</span>'
        else:
            marker = (f'<span style="display:inline-block;min-width:20px;height:20px;line-height:20px;'
                      f'text-align:center;border:1.5px solid {accent};border-radius:6px;'
                      f'color:{accent};font-size:12px;font-weight:800;">{t.get("idx","")}</span>')
        # time pill
        ann = _esc(t.get("annotation", "") or "")
        time_pill = (f'<span style="display:inline-block;font-size:11px;font-weight:700;'
                     f'color:{_ACCENT};background:rgba(124,155,255,0.14);border-radius:6px;'
                     f'padding:3px 7px;white-space:nowrap;">{ann}</span>' if ann else "")
        # task text + optional detail (2-tab subtasks)
        txt_style = (f'color:{_FAINT};text-decoration:line-through;' if done
                     else f'color:{_TEXT};font-weight:600;')
        star = "\u2b50 " if (pr in ("critical", "high") and not done) else ""
        detail = ""
        if t.get("detail"):
            detail = (f'<div style="font-size:12.5px;color:{_FAINT};line-height:1.5;margin-top:3px;">'
                      f'{_esc(t["detail"])}</div>')
        # right action
        action = ""
        if interactive and not done:
            link = _mailto(reply_subject, f"done {t['idx']}")
            action = (f'<a href="{_esc(link)}" style="display:inline-block;color:{_OK};font-size:12px;'
                      f'font-weight:700;text-decoration:none;white-space:nowrap;'
                      f'border:1px solid rgba(95,230,180,0.4);border-radius:7px;padding:4px 9px;">\u2713 done</a>')
        rows.append(
            f'<tr>'
            f'<td valign="top" style="width:26px;padding:9px 0;border-top:1px solid rgba(255,255,255,0.07);">{marker}</td>'
            + (f'<td valign="top" style="width:60px;padding:9px 8px 9px 4px;border-top:1px solid rgba(255,255,255,0.07);">{time_pill}</td>'
               if time_pill else '<td style="width:0;border-top:1px solid rgba(255,255,255,0.07);padding:9px 0;"></td>')
            + f'<td valign="top" style="padding:9px 8px;border-top:1px solid rgba(255,255,255,0.07);">'
            f'<span style="font-size:15px;line-height:1.45;{txt_style}">{star}{_esc(t.get("text",""))}</span>{detail}</td>'
            f'<td valign="top" align="right" style="padding:9px 0;border-top:1px solid rgba(255,255,255,0.07);white-space:nowrap;">{action}</td>'
            f'</tr>')
    return ('<table width="100%" cellpadding="0" cellspacing="0" role="presentation" '
            'style="border-collapse:collapse;">' + "".join(rows) + '</table>')


def _reply_hint() -> str:
    return (f'<div style="margin:14px 4px 0;padding:14px 16px;border-radius:12px;'
            f'background:linear-gradient(135deg,rgba(124,155,255,0.12),rgba(95,230,180,0.12));'
            f'border:1px solid #2a2f4d;font-size:14px;line-height:1.6;color:{_SOFT};">'
            f'\U0001F4AC <strong style="color:{_TEXT};">Reply</strong> with the numbers you finished '
            f'\u2014 e.g. <strong style="color:{_TEXT};">done 1 3</strong> \u2014 or just say it in words '
            f'("wrapped the API docs and the review"). Use <strong>undo 2</strong> to reopen one.</div>')


# --- schedule-time awareness (focus on what's due "by now") ----------------

def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9 ]", "", (s or "").lower()).strip()


def _schedule_hours() -> dict:
    """Map normalized planner-task text -> earliest scheduled hour (today only).

    Uses the saved schedule (the hour-blocked planner) so a plan task can be tied
    to the time you meant to do it. Next-day blocks (e.g. SLEEP) are ignored.
    """
    parsed = (store.load_schedule() or {}).get("parsed") or {}
    out = {}
    for b in parsed.get("blocks", []):
        if b.get("day_offset"):
            continue
        h = b.get("hour24")
        if h is None or h < 0:
            continue
        for t in b.get("tasks", []):
            key = _norm(t.get("text", ""))
            if key and (key not in out or h < out[key]):
                out[key] = h
    return out


def _task_hour(text: str, sched: dict):
    """Best-effort scheduled hour for a plan task by matching the planner text."""
    key = _norm(text)
    if not key or not sched:
        return None
    if key in sched:
        return sched[key]
    for k, h in sched.items():  # fuzzy: either contains the other
        if k and (k in key or key in k):
            return h
    return None


def _split_by_now(plan: dict, when: datetime):
    """Partition plan tasks into (due_by_now, later_or_untimed, has_schedule).

    A task is 'due by now' when its scheduled hour is at or before the current time.
    Schedule-sourced plans carry ``sched_hour`` directly; for weekly-sourced plans we
    fall back to matching the task text against the saved planner. The full plan is
    always the union of both lists (nothing is dropped)."""
    now_h = when.hour + when.minute / 60.0
    have_hours = any(t.get("sched_hour") is not None for t in plan.get("tasks", []))
    sched = None if have_hours else _schedule_hours()
    by_now, later = [], []
    for t in plan.get("tasks", []):
        h = t.get("sched_hour")
        if h is None and sched:
            h = _task_hour(t.get("text", ""), sched)
        t = dict(t, _hour=h)
        if h is not None and h <= now_h + 1e-6:
            by_now.append(t)
        else:
            later.append(t)
    by_now.sort(key=lambda x: (x["_hour"] if x["_hour"] is not None else 99, x["idx"]))
    later.sort(key=lambda x: (x["_hour"] if x["_hour"] is not None else 99, x["idx"]))
    return by_now, later, bool(have_hours or sched)


def _section_header(label: str, color: str) -> str:
    return (f'<div style="font-size:12px;font-weight:800;text-transform:uppercase;'
            f'letter-spacing:.6px;color:{color};margin:2px 2px 2px;">{_esc(label)}</div>')


# --- check-in --------------------------------------------------------------

def build_checkin(plan: dict, when: datetime, slot: str, cfg: dict | None = None) -> dict:
    cfg = cfg or store.load_config()
    show_score = cfg.get("checkin_show_score", True)
    show_later = cfg.get("checkin_show_later", True)
    show_hint = cfg.get("checkin_show_hint", True)
    full_day = (cfg.get("checkin_scope") or "up_to_now") == "full_day"

    sc = dayplan.score(plan)
    # Build a 12-hour clock manually (%-I / %I are not portable across platforms).
    hour12 = when.hour % 12 or 12
    ampm = "AM" if when.hour < 12 else "PM"
    now_str = f"{hour12}:{when.minute:02d} {ampm}"
    subject = f"\u23f1\ufe0f Check-in \u2014 {now_str}"
    reply_subject = f"Re: {subject}"

    by_now, later, has_sched = _split_by_now(plan, when)

    if has_sched and by_now and not full_day:
        # Focus the check-in on what was scheduled up to this point in the day,
        # optionally still listing the rest of the plan below.
        done_now = sum(1 for t in by_now if t.get("done"))
        lead = (f"By <strong style=\"color:{_TEXT};\">{now_str}</strong> you'd planned to be "
                f"through <strong style=\"color:{_TEXT};\">{len(by_now)}</strong> task(s) \u2014 "
                f"<strong style=\"color:{_TEXT};\">{done_now}/{len(by_now)}</strong> done so far. "
                f"What have you finished?")
        tasks_block = (
            f'<div style="background:{_CARD};border:1px solid #2a2f4d;border-radius:16px;padding:10px 16px 12px;margin:8px 4px;">'
            f'{_section_header(f"\u23f1 Up to {now_str}", _ACCENT)}'
            f'{_task_rows(by_now, reply_subject, interactive=True)}')
        if later and show_later:
            tasks_block += (
                f'<div style="height:6px;"></div>'
                f'{_section_header("Later today", _FAINT)}'
                f'{_task_rows(later, reply_subject, interactive=True)}')
        tasks_block += "</div>"
    else:
        # Full-day scope, no schedule times, or nothing due yet: show the whole plan.
        remaining = sc["count"] - sc["done"]
        lead = (f"You're at <strong style=\"color:{_TEXT};\">{sc['total']} pts</strong> with "
                f"<strong style=\"color:{_TEXT};\">{remaining}</strong> task(s) left. What's done?")
        if remaining == 0:
            lead = "Everything on today's plan is done \u2014 excellent. Anything else to log?"
        elif has_sched and not full_day:
            lead = ("Nothing was scheduled to be wrapped up just yet \u2014 here's the full "
                    "plan for today. What's done?")
        tasks_block = (
            f'<div style="background:{_CARD};border:1px solid #2a2f4d;border-radius:16px;padding:6px 16px 12px;margin:8px 4px;">'
            f'{_task_rows(plan.get("tasks", []), reply_subject, interactive=True)}</div>')

    inner = (
        f'<div style="background:linear-gradient(135deg,#6b7bff,#9a6bff);border-radius:18px;'
        f'padding:22px;text-align:center;"><div style="font-size:12px;letter-spacing:3px;'
        f'text-transform:uppercase;color:rgba(255,255,255,0.9);font-weight:700;">Progress check-in</div>'
        f'<div style="font-size:20px;font-weight:800;color:#fff;margin-top:6px;">{now_str}</div></div>'
        f'{_score_strip(sc) if show_score else ""}'
        f'<p style="font-size:16px;line-height:1.6;color:{_TEXT};margin:14px 4px 4px;">{lead}</p>'
        f'{tasks_block}'
        f'{_reply_hint() if show_hint else ""}')
    return {"subject": subject, "html": _shell(inner),
            "text": _checkin_text(plan, sc, hour12, ampm, when, cfg)}


def _checkin_text(plan: dict, sc: dict, hour12: int, ampm: str, when: datetime,
                  cfg: dict | None = None) -> str:
    cfg = cfg or {}
    show_later = cfg.get("checkin_show_later", True)
    full_day = (cfg.get("checkin_scope") or "up_to_now") == "full_day"
    now_str = f"{hour12}:{when.minute:02d} {ampm}"
    lines = [f"CHECK-IN  -  {now_str}  ({plan.get('date','')})", "=" * 40]
    if cfg.get("checkin_show_score", True):
        lines += [f"Score: {sc['total']} pts | {sc['done']}/{sc['count']} tasks | {sc['pct']}%"]
    lines += [""]

    def _row(t):
        box = "[x]" if t.get("done") else f"{t['idx']}."
        return f"  {box} {t['text']}" + (f"  ({t['annotation']})" if t.get("annotation") else "")

    by_now, later, has_sched = _split_by_now(plan, when)
    if has_sched and by_now and not full_day:
        lines.append(f"UP TO {now_str.upper()}:")
        lines += [_row(t) for t in by_now]
        if later and show_later:
            lines += ["", "LATER TODAY:"]
            lines += [_row(t) for t in later]
    else:
        lines += [_row(t) for t in plan.get("tasks", [])]

    if cfg.get("checkin_show_hint", True):
        lines += ["", "Reply 'done 1 3' with what you finished (or say it in words). 'undo 2' reopens one."]
    return "\n".join(lines)


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

    bonus_bit = f' \u00b7 +{sc["bonus"]} check-in bonus' if sc["bonus"] else ""
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
    """Common gate: enabled feature, email set up, and the morning brief already sent."""
    if not (cfg.get("email_to") or "").strip() or not email_send.is_configured():
        return False, None
    plan = dayplan.get_day_plan(when)
    if not plan or not plan.get("tasks"):
        return False, None
    if store.load_state().get("last_sent_date") != when.strftime("%Y-%m-%d"):
        return False, None  # don't check in before the morning digest
    return True, plan


def send_checkins_if_due(when: datetime | None = None) -> dict:
    """Send any due check-in for the active user. Returns a small status dict."""
    when = when or datetime.now()
    cfg = store.load_config()
    if not cfg.get("checkins_enabled"):
        return {"sent": 0, "reason": "disabled"}
    ok, plan = _ready(cfg, when)
    if not ok:
        return {"sent": 0, "reason": "not ready"}
    sc = dayplan.score(plan)
    if sc["done"] >= sc["count"]:
        return {"sent": 0, "reason": "all done"}  # nothing to nudge about
    today = when.strftime("%Y-%m-%d")
    sent = 0
    for slot in (cfg.get("checkin_times") or []):
        if not _checkin_due_now(slot, when):
            continue
        # Cross-process claim so the Windows task and any running server never
        # double-send the same slot.
        claim = f"checkin-{today}-{slot}"
        if not store.claim_once(claim):
            continue
        msg = build_checkin(plan, when, slot, cfg)
        try:
            email_send.send_email(to_addr=cfg["email_to"], subject=msg["subject"],
                                  html=msg["html"], text=msg["text"])
        except email_send.EmailError:
            store.release_claim(claim)  # let a later tick retry
            continue
        dayplan.record_checkin(slot, when)
        sent += 1
    return {"sent": sent, "reason": "ok" if sent else "none due"}


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
    """Dispatch check-ins + recap for every user (isolated). Safe to call each tick."""
    when = when or datetime.now()
    results = []
    if not email_send.is_configured():
        return results
    for u in user_context.list_users():
        with user_context.using_user(u["id"]):
            try:
                ci = send_checkins_if_due(when)
                rc = send_recap_if_due(when)
            except Exception as exc:  # noqa: BLE001 - isolate per-user failures
                ci, rc = {"sent": 0, "reason": f"error: {exc}"}, {"sent": 0}
        results.append({"user": u["id"], "checkins": ci, "recap": rc})
    return results
