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
from datetime import datetime
from urllib.parse import quote

import user_context

from . import dayplan, email_send, store


def _esc(s) -> str:
    return _html.escape(str(s or ""))


def _hhmm_passed(slot: str, when: datetime) -> bool:
    try:
        hh, mm = (int(x) for x in str(slot).split(":", 1))
    except (ValueError, TypeError):
        return False
    target = when.replace(hour=hh, minute=mm, second=0, microsecond=0)
    return when >= target


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


def _task_rows(plan: dict, reply_subject: str, *, interactive: bool) -> str:
    rows = []
    for t in plan.get("tasks", []):
        done = t.get("done")
        mark = "\u2705" if done else f'<span style="color:{_FAINT};font-weight:800;">{t["idx"]}.</span>'
        txt_style = (f'color:{_FAINT};text-decoration:line-through;' if done
                     else f'color:{_TEXT};font-weight:600;')
        pr = t.get("priority")
        flag = ("\u203c\ufe0f " if pr == "critical" else ("\u2b50 " if pr == "high" else ""))
        ann = f' <span style="color:{_FAINT};font-size:12px;">({_esc(t["annotation"])})</span>' if t.get("annotation") else ""
        quick = ""
        if interactive and not done:
            link = _mailto(reply_subject, f"done {t['idx']}")
            quick = (f' <a href="{_esc(link)}" style="color:{_OK};font-size:12px;font-weight:700;'
                     f'text-decoration:none;white-space:nowrap;">[\u2713 done]</a>')
        rows.append(
            f'<div style="padding:9px 0;border-top:1px solid rgba(255,255,255,0.07);">'
            f'<span style="display:inline-block;width:26px;">{mark}</span>'
            f'<span style="font-size:15px;line-height:1.5;{txt_style}">{flag}{_esc(t["text"])}</span>'
            f'{ann}{quick}</div>')
    return "".join(rows)


def _reply_hint() -> str:
    return (f'<div style="margin:14px 4px 0;padding:14px 16px;border-radius:12px;'
            f'background:linear-gradient(135deg,rgba(124,155,255,0.12),rgba(95,230,180,0.12));'
            f'border:1px solid #2a2f4d;font-size:14px;line-height:1.6;color:{_SOFT};">'
            f'\U0001F4AC <strong style="color:{_TEXT};">Reply</strong> with the numbers you finished '
            f'\u2014 e.g. <strong style="color:{_TEXT};">done 1 3</strong> \u2014 or just say it in words '
            f'("wrapped the API docs and the review"). Use <strong>undo 2</strong> to reopen one.</div>')


# --- check-in --------------------------------------------------------------

def build_checkin(plan: dict, when: datetime, slot: str) -> dict:
    sc = dayplan.score(plan)
    # Build a 12-hour clock manually (%-I / %I are not portable across platforms).
    hour12 = when.hour % 12 or 12
    ampm = "AM" if when.hour < 12 else "PM"
    subject = f"\u23f1\ufe0f Check-in \u2014 {hour12}:{when.minute:02d} {ampm}"
    reply_subject = f"Re: {subject}"
    remaining = sc["count"] - sc["done"]
    lead = (f"You're at <strong style=\"color:{_TEXT};\">{sc['total']} pts</strong> with "
            f"<strong style=\"color:{_TEXT};\">{remaining}</strong> task(s) left. What's done?")
    if remaining == 0:
        lead = "Everything on today's plan is done \u2014 excellent. Anything else to log?"
    inner = (
        f'<div style="background:linear-gradient(135deg,#6b7bff,#9a6bff);border-radius:18px;'
        f'padding:22px;text-align:center;"><div style="font-size:12px;letter-spacing:3px;'
        f'text-transform:uppercase;color:rgba(255,255,255,0.9);font-weight:700;">Progress check-in</div>'
        f'<div style="font-size:20px;font-weight:800;color:#fff;margin-top:6px;">{hour12}:{when.minute:02d} {ampm}</div></div>'
        f'{_score_strip(sc)}'
        f'<p style="font-size:16px;line-height:1.6;color:{_TEXT};margin:14px 4px 4px;">{lead}</p>'
        f'<div style="background:{_CARD};border:1px solid #2a2f4d;border-radius:16px;padding:6px 16px 12px;margin:8px 4px;">'
        f'{_task_rows(plan, reply_subject, interactive=True)}</div>'
        f'{_reply_hint()}')
    return {"subject": subject, "html": _shell(inner), "text": _checkin_text(plan, sc, hour12, ampm)}


def _checkin_text(plan: dict, sc: dict, hour12: int, ampm: str) -> str:
    lines = [f"CHECK-IN  -  {hour12}:{plan.get('date','')}", "=" * 40,
             f"Score: {sc['total']} pts | {sc['done']}/{sc['count']} tasks | {sc['pct']}%", ""]
    for t in plan.get("tasks", []):
        box = "[x]" if t.get("done") else f"{t['idx']}."
        lines.append(f"  {box} {t['text']}" + (f"  ({t['annotation']})" if t.get("annotation") else ""))
    lines += ["", "Reply 'done 1 3' with what you finished (or say it in words). 'undo 2' reopens one."]
    return "\n".join(lines)


# --- recap -----------------------------------------------------------------

def build_recap(plan: dict, sc: dict, when: datetime) -> dict:
    week = dayplan.week_summary(when)
    board = dayplan.leaderboard(when)
    rank = next((r["rank"] for r in board if r.get("points") is not None
                 and r["name"] and _is_me(r)), None)
    subject = f"\U0001F319 Day recap \u2014 {sc['done']}/{sc['count']} done \u00b7 {sc['total']} pts"
    reply_subject = f"Re: {subject}"
    done = [t for t in plan.get("tasks", []) if t.get("done")]
    left = [t for t in plan.get("tasks", []) if not t.get("done")]

    def _list(items, color):
        if not items:
            return f'<div style="color:{_FAINT};font-size:14px;padding:6px 0;">\u2014 none \u2014</div>'
        return "".join(
            f'<div style="padding:7px 0;border-top:1px solid rgba(255,255,255,0.07);'
            f'font-size:15px;color:{color};line-height:1.5;">{_esc(t["text"])}</div>'
            for t in items)

    bonus_bit = f' \u00b7 +{sc["bonus"]} check-in bonus' if sc["bonus"] else ""
    penalty_bit = (f' \u00b7 -{sc["penalty"]} for {sc["count"] - sc["done"]} unfinished'
                   if sc["penalty"] else "")
    breakdown = (f'<div style="font-size:13.5px;color:{_SOFT};line-height:1.9;">'
                 f'Earned <strong style="color:{_TEXT};">{sc["earned"]}</strong> of {sc["possible"]} task points'
                 f'{bonus_bit}{penalty_bit}'
                 f' \u2192 <strong style="color:{_TEXT};">{sc["total"]} pts</strong></div>')
    week_line = (f'<div style="margin-top:6px;font-size:13.5px;color:{_SOFT};">This week: '
                 f'<strong style="color:{_TEXT};">{week["total"]} pts</strong> over {week["days"]} day(s)'
                 f'{f" \u00b7 you\u2019re #{rank} on the leaderboard" if rank else ""}.</div>')

    inner = (
        f'<div style="background:linear-gradient(135deg,#241a3e,#1a2340);border-radius:18px;'
        f'padding:22px;text-align:center;"><div style="font-size:12px;letter-spacing:3px;'
        f'text-transform:uppercase;color:{_ACCENT};font-weight:700;">Day recap</div>'
        f'<div style="font-size:26px;font-weight:800;color:#fff;margin-top:6px;">{sc["total"]} points</div>'
        f'<div style="font-size:13px;color:{_SOFT};margin-top:2px;">{when.strftime("%A, %b %d")}</div></div>'
        f'{_score_strip(sc)}'
        f'<div style="background:{_CARD};border:1px solid #2a2f4d;border-radius:16px;padding:14px 16px;margin:10px 4px;">'
        f'<div style="font-size:13px;font-weight:800;text-transform:uppercase;letter-spacing:.5px;color:{_OK};">\u2705 Done</div>'
        f'{_list(done, _SOFT)}'
        f'<div style="font-size:13px;font-weight:800;text-transform:uppercase;letter-spacing:.5px;color:#ff9ec7;margin-top:12px;">\u25cb Still open</div>'
        f'{_list(left, _TEXT)}</div>'
        f'<div style="padding:0 6px;">{breakdown}{week_line}</div>'
        f'<div style="margin:14px 4px 0;padding:14px 16px;border-radius:12px;'
        f'background:linear-gradient(135deg,rgba(124,155,255,0.12),rgba(255,158,199,0.12));'
        f'border:1px solid #2a2f4d;font-size:14px;line-height:1.6;color:{_SOFT};">'
        f'\U0001F4AC <strong style="color:{_TEXT};">Reply</strong> to log the rest ("done 2"), reflect on the '
        f'day, or plan tomorrow ("tomorrow: deep work on the compiler at 9"). It shapes your morning brief.</div>')
    return {"subject": subject, "html": _shell(inner), "text": _recap_text(plan, sc, week)}


def _is_me(row) -> bool:
    try:
        return row.get("user") == user_context.current_user_id()
    except Exception:  # noqa: BLE001
        return False


def _recap_text(plan: dict, sc: dict, week: dict) -> str:
    lines = [f"DAY RECAP  -  {plan.get('date','')}", "=" * 40,
             f"Score: {sc['total']} pts | {sc['done']}/{sc['count']} done | {sc['pct']}%",
             f"This week: {week['total']} pts over {week['days']} day(s).", "", "Done:"]
    lines += [f"  [x] {t['text']}" for t in plan.get("tasks", []) if t.get("done")] or ["  (none)"]
    lines += ["", "Still open:"]
    lines += [f"  [ ] {t['text']}" for t in plan.get("tasks", []) if not t.get("done")] or ["  (none)"]
    lines += ["", "Reply to log the rest, reflect, or plan tomorrow."]
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
    st = store.load_state()
    sent_map = st.get("checkins_sent") or {}
    already = set(sent_map.get(today, []))
    sent = 0
    for slot in (cfg.get("checkin_times") or []):
        if slot in already or not _hhmm_passed(slot, when):
            continue
        msg = build_checkin(plan, when, slot)
        try:
            email_send.send_email(to_addr=cfg["email_to"], subject=msg["subject"],
                                  html=msg["html"], text=msg["text"])
        except email_send.EmailError:
            continue
        dayplan.record_checkin(slot, when)
        already.add(slot)
        sent += 1
    if sent:
        sent_map[today] = sorted(already)
        store.save_state({"checkins_sent": sent_map})
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
    if store.load_state().get("recap_sent_date") == today:
        return {"sent": 0, "reason": "already sent"}
    plan, sc = dayplan.finalize_day(when)
    msg = build_recap(plan, sc, when)
    try:
        email_send.send_email(to_addr=cfg["email_to"], subject=msg["subject"],
                              html=msg["html"], text=msg["text"])
    except email_send.EmailError as exc:
        return {"sent": 0, "reason": f"error: {exc}"}
    store.save_state({"recap_sent_date": today})
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
