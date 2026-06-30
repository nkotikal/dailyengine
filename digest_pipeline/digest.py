"""Build, render, and send the daily digest; decide when it's due.

Isolated from the resume pipeline. Uses ``store`` for data, ``llm`` to compose
(optional), and ``email_send`` to deliver.
"""

import html as _html
import re
from datetime import datetime, date

from . import (email_send, gcal, inbox_commands, korean, llm, memory, news,
               schedule, store, tasks, trackers)

PRIORITY_ORDER = {"high": 0, "medium": 1, "low": 2}
PRIORITY_COLOR = {"high": "#ff8f9c", "medium": "#ffd479", "low": "#7c9bff"}

# Granular "reference" sections - rendered compact/muted and pushed below the brief.
DETAIL_TITLES = {
    "schedule", "this week's tasks", "rest of this week", "routine", "tasks",
    "calendar", "korean practice", "completed", "long-term goals",
}


def _reminders_view(when: datetime):
    """Return (text, items) for active reminders, with days-until + escalation."""
    today = when.date()
    rows = []
    for r in store.active_reminders():
        due = (r.get("due") or "").strip()
        days = None
        if due:
            try:
                days = (date.fromisoformat(due) - today).days
            except ValueError:
                days = None
        pr = r.get("priority", "medium")
        if days is not None:
            if days <= 2:
                pr = "high"
            elif days <= 7 and pr == "low":
                pr = "medium"
        rows.append({"text": r["text"], "due": due, "days": days, "priority": pr})
    rows.sort(key=lambda x: (x["days"] is None, x["days"] if x["days"] is not None else 9999))

    lines = []
    for x in rows:
        if x["days"] is None:
            when_s = "no date"
        elif x["days"] < 0:
            when_s = f"OVERDUE by {-x['days']}d ({x['due']})"
        elif x["days"] == 0:
            when_s = f"DUE TODAY ({x['due']})"
        else:
            when_s = f"in {x['days']}d ({x['due']})"
        lines.append(f"- [{x['priority']}] {x['text']} - {when_s}")
    return "\n".join(lines), rows


# --- composition -----------------------------------------------------------

def _korean_items(lesson: dict) -> list:
    """Flat items for the Korean Practice section (vocab + grammar + tip)."""
    items = []
    for v in (lesson or {}).get("vocab", []):
        rom = f" ({v['romanization']})" if v.get("romanization") else ""
        t = f"{v.get('korean','')}{rom} \u2014 {v.get('english','')}"
        if v.get("example_ko"):
            t += f"  \u00b7  {v['example_ko']}"
        items.append({"text": t, "priority": "low", "url": ""})
    for g in (lesson or {}).get("grammar", []):
        t = f"{g.get('point','')} \u2014 {g.get('english','')}"
        if g.get("example_ko"):
            t += f"  \u00b7  {g['example_ko']}"
        items.append({"text": t, "priority": "low", "url": ""})
    if (lesson or {}).get("tip"):
        items.append({"text": "Tip: " + lesson["tip"], "priority": "low", "url": ""})
    return items


def _match_news_url(text: str, news_items: list) -> str:
    """Best-effort link for a headline item by token overlap with fetched stories."""
    tw = set(re.findall(r"[a-z0-9]+", (text or "").lower()))
    best, best_score = None, 0
    for h in news_items or []:
        hw = set(re.findall(r"[a-z0-9]+", (h.get("title") or "").lower()))
        sc = len(tw & hw)
        if sc > best_score:
            best, best_score = h, sc
    return best.get("url", "") if best and best_score >= 2 else ""


def _finalize_sections(data: dict, *, korean_lesson=None, news_items=None) -> dict:
    """Post-process the composed digest: real headline links, a complete Korean card
    (placed above the schedule), and no empty cards."""
    secs = data.get("sections", [])
    if news_items:
        for s in secs:
            if s.get("title", "").strip().lower() == "headlines":
                for it in s.get("items", []):
                    if not it.get("url"):
                        it["url"] = _match_news_url(it.get("text", ""), news_items)
    if korean_lesson:
        kitems = _korean_items(korean_lesson)
        if kitems:
            secs = [s for s in secs if s.get("title", "").strip().lower() != "korean practice"]
            ksec = {"title": "Korean Practice", "icon": "\U0001F1F0\U0001F1F7",
                    "summary": "", "items": kitems}
            idx = next((i for i, s in enumerate(secs)
                        if s.get("title", "").strip().lower() == "schedule"), len(secs))
            secs.insert(idx, ksec)
    # Drop any empty cards (prevents blank sections).
    secs = [s for s in secs if s.get("items") or (s.get("summary") or "").strip()]
    data["sections"] = secs
    return data


def _deterministic_digest(cfg, updates, when_human, *, parsed_schedule=None,
                          calendar_events=None, findings=None, korean_lesson=None,
                          reminders=None, weekly_tasks=None, today=None,
                          news_items=None) -> dict:
    """A clean digest without the LLM: organize the raw inputs into sections."""
    def lines(blob):
        out = []
        for ln in (blob or "").splitlines():
            s = ln.strip().lstrip("-*").strip()
            if s:
                imp = s.startswith("'")
                out.append({"text": s.lstrip("'").strip(),
                            "priority": "high" if imp else "medium"})
        return out

    # Build each block, then assemble TOP->BOTTOM like a CEO brief (what matters
    # first; granular day last).
    top, bottom = [], []

    # --- TOP: priorities, key developments, deadlines, goals ---
    if weekly_tasks:
        try:
            cap_min = int(float(cfg.get("daily_capacity_hours", 6)) * 60)
        except (TypeError, ValueError):
            cap_min = 360
        # Priorities go up top; "Rest of this week"/"Completed" sink to the detail zone.
        for sec in tasks.build_sections(today, cap_min):
            if sec["title"].strip().lower() in DETAIL_TITLES:
                bottom.append(sec)
            else:
                top.append(sec)
    else:
        weekly_items = tasks.outline_items(cfg.get("weekly_goals", ""))
        if weekly_items:
            top.append({"title": "Goals This Week", "icon": "\U0001F4C6", "items": weekly_items})

    new_items = [{"text": u.get("text", "").strip(), "priority": "medium"}
                 for u in (updates or []) if u.get("text")]
    new_items += [{"text": f"[{f.get('source','')}] {f.get('text','')}", "priority": "medium"}
                  for f in (findings or [])]
    if new_items:
        top.append({"title": "Key Developments", "icon": "\U0001F4E5", "items": new_items})

    if reminders:
        ritems = []
        for x in reminders:
            if x["days"] is None:
                tail = ""
            elif x["days"] < 0:
                tail = f" (OVERDUE {x['due']})"
            elif x["days"] == 0:
                tail = " (due today)"
            else:
                tail = f" (in {x['days']}d, {x['due']})"
            ritems.append({"text": x["text"] + tail, "priority": x["priority"]})
        if ritems:
            top.append({"title": "Deadlines", "icon": "\u23F0", "items": ritems})

    # Headlines (contextual intel) - near the top, below priorities/deadlines.
    if news_items:
        hitems = [{"text": h["title"], "priority": "low", "url": h.get("url", "")}
                  for h in news_items[:6] if h.get("title")]
        if hitems:
            top.append({"title": "Headlines", "icon": "\U0001F4F0", "items": hitems})

    longterm_items = tasks.outline_items(cfg.get("longterm_goals") or cfg.get("goals") or "")
    if longterm_items:
        top.append({"title": "Long-Term Goals", "icon": "\U0001F3AF", "items": longterm_items})

    # --- BOTTOM: the granular day. Korean sits ABOVE the full schedule, which is the
    # most granular item and goes dead last. ---
    routine_items = tasks.outline_items(cfg.get("tasks", ""))
    if routine_items:
        bottom.append({"title": "Routine", "icon": "\u2705", "items": routine_items})

    if korean_lesson:
        kitems = _korean_items(korean_lesson)
        if kitems:
            bottom.append({"title": "Korean Practice", "icon": "\U0001F1F0\U0001F1F7", "items": kitems})

    if calendar_events:
        bottom.append({
            "title": "Calendar",
            "icon": "\U0001F4C5",
            "items": [{"text": f"{e['start']} - {e['summary']}", "priority": "medium"}
                      for e in calendar_events],
        })

    if parsed_schedule and parsed_schedule.get("blocks"):
        items = []
        for b in parsed_schedule["blocks"]:
            for t in b["tasks"]:
                detail = "; ".join(s["text"] for s in t.get("subtasks", []))
                txt = f"{b['time_str']} - {t['text']}"
                if detail:
                    txt += f" ({detail})"
                items.append({"text": txt, "priority": "high" if t["important"] else "medium"})
        if items:
            bottom.append({"title": "Schedule", "icon": "\U0001F5D3\uFE0F", "items": items})

    sections = top + bottom

    if not sections:
        sections.append({
            "title": "Getting started",
            "icon": "\U0001F44B",
            "items": [{"text": "Add your about/goals/tasks, a schedule, or trackers to get a richer digest.",
                       "priority": "low"}],
        })

    return {
        "greeting": f"Good morning! Here's your plan for {when_human}.",
        "headline": "",
        "sections": sections,
        "closing": "Have a focused, productive day.",
    }


def _normalize(data: dict) -> dict:
    """Coerce arbitrary model/deterministic output into a safe, sorted structure."""
    if not isinstance(data, dict):
        data = {}
    out = {
        "greeting": str(data.get("greeting") or "").strip(),
        "headline": str(data.get("headline") or "").strip(),
        "closing": str(data.get("closing") or "").strip(),
        "sections": [],
    }
    for sec in data.get("sections") or []:
        if not isinstance(sec, dict):
            continue
        title = str(sec.get("title") or "").strip()
        if not title:
            continue
        summary = str(sec.get("summary") or "").strip()
        items = []
        for it in sec.get("items") or []:
            url = ""
            if isinstance(it, dict):
                text = str(it.get("text") or "").strip()
                pr = str(it.get("priority") or "medium").lower()
                url = str(it.get("url") or "").strip()
            else:
                text, pr = str(it).strip(), "medium"
            if not text:
                continue
            if pr not in PRIORITY_ORDER:
                pr = "medium"
            items.append({"text": text, "priority": pr, "url": url})
        # Preserve given order (deterministic build is pre-sorted/nested; the LLM
        # orders deliberately). Keep a section if it has prose and/or items.
        if items or summary:
            out["sections"].append({
                "title": title,
                "icon": str(sec.get("icon") or "").strip(),
                "summary": summary,
                "items": items,
            })
    return out


def build_digest(cfg: dict | None = None, *, when: datetime | None = None,
                 consume: bool = False) -> dict:
    """Compose today's digest from every enabled module.

    ``consume`` True (a real send) advances tracker state so items aren't repeated;
    False (a preview) leaves state untouched.
    """
    cfg = cfg or store.load_config()
    when = when or datetime.now()
    when_human = when.strftime("%A, %B %d, %Y")
    today_key = when.strftime("%Y-%m-%d")
    warnings = []

    # On a real send, first apply any email replies (complete/add tasks, interests,
    # preferences) so the morning digest reflects them.
    if consume:
        try:
            inbox_commands.process_replies(model=(cfg.get("model") or None))
            cfg = store.load_config()  # reflect any preference changes
        except Exception:  # noqa: BLE001 - never let replies break the send
            pass

    updates = store.pending_updates()
    update_ids = [u["id"] for u in updates if u.get("id")]
    memory_text = memory.render_for_digest()
    reminders_text, reminder_rows = _reminders_view(when)
    weekly_tasks = store.list_weekly_tasks()
    weekly_tasks_text = tasks.render_for_llm(when.date())

    # Headlines from configured news sources, ranked later by the composer to the
    # user's interests.
    news_items = []
    headlines_text = ""
    interests = cfg.get("interests") or []
    if cfg.get("news_enabled", True):
        try:
            news_items = news.fetch_all(cfg.get("news_sources") or [])
            headlines_text = news.render_for_llm(news_items)
        except Exception as exc:  # noqa: BLE001
            warnings.append(f"News unavailable ({exc}).")
    try:
        capacity_min = int(float(cfg.get("daily_capacity_hours", 6)) * 60)
    except (TypeError, ValueError):
        capacity_min = 360
    load = tasks.load_summary(when.date(), capacity_min)
    if load["focus_est"]:
        focus_load_text = (f"~{load['focus_est']} of focus work across "
                           f"{load['focus_count']} task(s); your realistic daily "
                           f"capacity is ~{tasks.fmt_est(capacity_min)}."
                           + (" OVER CAPACITY - gently suggest deferring lower items."
                              if load["overloaded"] else ""))
    else:
        focus_load_text = ""

    offline = bool(cfg.get("offline")) or not llm.have_key()

    # --- gather module inputs ---
    parsed_schedule = None
    schedule_text = ""
    if cfg.get("include_schedule", True):
        sched = store.load_schedule()
        parsed_schedule = sched.get("parsed") or None
        if parsed_schedule:
            schedule_text = schedule.render_text(parsed_schedule)

    calendar_events = []
    calendar_text = ""
    if cfg.get("include_calendar", True) and gcal.is_configured():
        try:
            calendar_events = gcal.list_events(when)
            calendar_text = gcal.render_events_text(calendar_events)
        except gcal.GCalError as exc:
            warnings.append(f"Calendar unavailable ({exc}).")

    findings = []
    if cfg.get("include_trackers", True):
        try:
            findings = trackers.poll_all(persist=consume)
        except Exception as exc:  # noqa: BLE001
            warnings.append(f"Trackers error ({exc}).")

    korean_lesson = None
    korean_text = ""
    if cfg.get("korean_enabled"):
        korean_lesson = store.korean_lesson_for(today_key)
        if korean_lesson is None:
            try:
                kstate = store.load_korean()
                korean_lesson, new_kstate = korean.build_lesson(
                    kstate,
                    level=cfg.get("korean_level", "intermediate"),
                    today=today_key,
                    model=(cfg.get("model") or None),
                    offline=offline,
                )
                store.save_korean(new_kstate)
            except llm.DigestLLMError as exc:
                warnings.append(f"Korean lesson skipped ({exc}).")
        if korean_lesson:
            korean_text = korean.render_summary(korean_lesson)

    # --- compose ---
    used_llm = False
    if offline:
        data = _deterministic_digest(cfg, updates, when_human,
                                     parsed_schedule=parsed_schedule,
                                     calendar_events=calendar_events,
                                     findings=findings, korean_lesson=korean_lesson,
                                     reminders=reminder_rows, weekly_tasks=weekly_tasks,
                                     today=when.date(), news_items=news_items)
        if not cfg.get("offline") and not llm.have_key():
            warnings.append("No API key configured; built a plain (offline) digest.")
    else:
        try:
            data = llm.compose_digest(
                about=cfg.get("about", ""),
                weekly_goals=cfg.get("weekly_goals", ""),
                longterm_goals=cfg.get("longterm_goals") or cfg.get("goals", ""),
                tasks=cfg.get("tasks", ""),
                updates=updates,
                when_human=when_human,
                tone=cfg.get("tone", "friendly and concise"),
                memory_text=memory_text,
                schedule_text=schedule_text,
                calendar_text=calendar_text,
                tracker_findings=findings,
                korean_summary=korean_text,
                reminders_text=reminders_text,
                weekly_tasks_text=weekly_tasks_text,
                focus_load_text=focus_load_text,
                headlines_text=headlines_text,
                interests=interests,
                model=(cfg.get("model") or None),
            )
            used_llm = True
        except llm.DigestLLMError as exc:
            data = _deterministic_digest(cfg, updates, when_human,
                                         parsed_schedule=parsed_schedule,
                                         calendar_events=calendar_events,
                                         findings=findings, korean_lesson=korean_lesson,
                                         reminders=reminder_rows, weekly_tasks=weekly_tasks,
                                         today=when.date(), news_items=news_items)
            warnings.append(f"LLM unavailable ({exc}); sent a plain digest instead.")

    data = _normalize(data)
    data = _finalize_sections(data, korean_lesson=korean_lesson, news_items=news_items)
    headline = data["headline"] or "Your daily digest"
    subject = f"\u2600\ufe0f Daily Digest \u2014 {when.strftime('%a, %b %d')}"
    return {
        "data": data,
        "html": render_html(data, when_human),
        "text": render_text(data, when_human),
        "subject": subject,
        "used_llm": used_llm,
        "offline": offline,
        "warning": " ".join(warnings),
        "update_ids": update_ids,
        "update_count": len(update_ids),
        "finding_count": len(findings),
        "headline": headline,
    }


# --- rendering -------------------------------------------------------------

def _esc(s: str) -> str:
    return _html.escape(str(s or ""))


# Per-section color theme: (accent, tint background). Keeps the whole email lively.
SECTION_THEME = {
    "today's focus": ("#8aa0ff", "rgba(124,155,255,0.16)"),
    "deadlines": ("#ff8f9c", "rgba(255,143,156,0.16)"),
    "headlines": ("#5fe6b4", "rgba(95,230,180,0.15)"),
    "what's new": ("#ffd479", "rgba(255,212,121,0.15)"),
    "key developments": ("#ffd479", "rgba(255,212,121,0.15)"),
    "progress": ("#c08cff", "rgba(192,140,255,0.17)"),
    "this week's tasks": ("#8ab4ff", "rgba(138,180,255,0.15)"),
    "rest of this week": ("#8ab4ff", "rgba(138,180,255,0.13)"),
    "completed": ("#5fe6b4", "rgba(95,230,180,0.13)"),
    "routine": ("#9fd0ff", "rgba(159,208,255,0.13)"),
    "korean practice": ("#ff9ec7", "rgba(255,158,199,0.16)"),
    "schedule": ("#6fd3ff", "rgba(111,211,255,0.15)"),
    "long-term goals": ("#ffb37a", "rgba(255,179,122,0.16)"),
}
_DEFAULT_THEME = ("#7c9bff", "rgba(124,155,255,0.15)")


def _theme(title: str):
    return SECTION_THEME.get((title or "").strip().lower(), _DEFAULT_THEME)


def _badge(icon: str, tint: str) -> str:
    """A colored rounded icon badge."""
    icon = (icon or "\u2022").strip() or "\u2022"
    return (f'<span style="display:inline-block;width:30px;height:30px;border-radius:9px;'
            f'background:{tint};text-align:center;line-height:30px;font-size:16px;'
            f'margin-right:10px;vertical-align:middle;">{_esc(icon)}</span>')


def _link(url: str, color: str) -> str:
    if not url:
        return ""
    return (f' <a href="{_esc(url)}" style="color:{color};font-size:12.5px;'
            f'font-weight:700;text-decoration:none;white-space:nowrap;">open \u2197</a>')


def render_html(data: dict, when_human: str) -> str:
    """Inline-styled HTML email - colorful card layout, large type, single column."""
    bg = "#0a0c18"
    card = "#161a2e"
    text = "#f1f4ff"
    soft = "#c3c9de"
    faint = "#828aa6"
    fam = ("-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,"
           "sans-serif")

    parts = [
        f'<div style="margin:0;padding:0;background:{bg};">',
        f'<div style="max-width:600px;margin:0 auto;padding:18px 14px 32px;'
        f'font-family:{fam};">',
        # decorative gradient header banner with a subtle pattern feel
        f'<div style="background:linear-gradient(135deg,#6b7bff 0%,#9a6bff 50%,#ff7eb6 100%);'
        f'border-radius:22px;padding:30px 24px;text-align:center;'
        f'box-shadow:0 10px 30px rgba(124,109,255,0.35);">'
        f'<div style="font-size:13px;letter-spacing:4px;text-transform:uppercase;'
        f'color:rgba(255,255,255,0.9);font-weight:700;">\u2600\ufe0f  Daily Brief</div>'
        f'<div style="font-size:23px;font-weight:800;color:#fff;margin-top:8px;'
        f'letter-spacing:-0.3px;">{_esc(when_human)}</div>'
        f'<div style="margin-top:12px;font-size:20px;letter-spacing:6px;">'
        f'\U0001F3AF \U0001F4F0 \U0001F4C5 \U0001F1F0\U0001F1F7</div></div>',
    ]
    if data.get("greeting"):
        parts.append(
            f'<p style="font-size:18px;line-height:1.6;color:{text};margin:22px 4px 8px;">'
            f'{_esc(data["greeting"])}</p>'
        )
    if data.get("headline"):
        parts.append(
            f'<div style="background:linear-gradient(135deg,#2a2358,#1c2350);'
            f'border-left:5px solid #8aa0ff;border-radius:14px;padding:18px 20px;'
            f'margin:14px 4px 24px;box-shadow:0 6px 20px rgba(20,16,50,0.5);">'
            f'<div style="font-size:11px;letter-spacing:1.4px;text-transform:uppercase;'
            f'color:#8aa0ff;font-weight:800;margin-bottom:6px;">\u2b50 Top priority today</div>'
            f'<div style="font-size:19px;line-height:1.5;color:#fff;font-weight:700;">'
            f'{_esc(data["headline"])}</div></div>'
        )

    detail_started = False
    for sec in data.get("sections", []):
        title = sec.get("title", "")
        is_detail = title.strip().lower() in DETAIL_TITLES
        color, tint = _theme(title)
        icon = (sec.get("icon") or "").strip()

        if is_detail and not detail_started:
            detail_started = True
            parts.append(
                f'<div style="margin:28px 4px 14px;text-align:center;font-size:11px;'
                f'letter-spacing:3px;text-transform:uppercase;color:{faint};font-weight:700;">'
                f'\u2022 \u2022 \u2022 &nbsp; the granular day &nbsp; \u2022 \u2022 \u2022</div>'
            )

        if is_detail:
            # Colored (not gray) compact card.
            parts.append(
                f'<div style="background:{tint};border-left:4px solid {color};'
                f'border-radius:12px;padding:14px 16px;margin:0 4px 12px;">'
                f'<div style="font-size:14.5px;font-weight:800;letter-spacing:.4px;'
                f'text-transform:uppercase;color:{color};margin-bottom:9px;">'
                f'{_badge(icon, "rgba(255,255,255,0.10)")}{_esc(title)}</div>'
            )
            for it in sec.get("items", []):
                parts.append(
                    f'<div style="font-size:14.5px;line-height:1.55;color:{soft};'
                    f'margin:0 0 5px;padding-left:2px;">{_esc(it.get("text"))}'
                    f'{_link(it.get("url"), color)}</div>'
                )
            parts.append('</div>')
            continue

        # Brief sections: prominent colorful card with tinted header + badge.
        parts.append(
            f'<div style="background:{card};border:1px solid #2a2f4d;border-radius:18px;'
            f'padding:0;margin:0 4px 18px;overflow:hidden;'
            f'box-shadow:0 6px 18px rgba(8,10,30,0.4);">'
            f'<div style="background:{tint};padding:14px 18px;border-bottom:1px solid #2a2f4d;'
            f'font-size:18px;font-weight:800;color:{text};">'
            f'{_badge(icon, "rgba(255,255,255,0.12)")}{_esc(title)}</div>'
            f'<div style="padding:16px 18px 18px;">'
        )
        if sec.get("summary"):
            parts.append(
                f'<p style="font-size:16.5px;line-height:1.7;color:{text};margin:0 0 '
                f'{"14px" if sec.get("items") else "0"};">{_esc(sec["summary"])}</p>'
            )
        for it in sec.get("items", []):
            dot = PRIORITY_COLOR.get(it.get("priority", "medium"), color)
            parts.append(
                f'<div style="margin:0 0 11px;padding-left:18px;position:relative;'
                f'border-left:0;">'
                f'<span style="display:inline-block;width:9px;height:9px;border-radius:50%;'
                f'background:{dot};margin:0 10px 1px 0;vertical-align:middle;"></span>'
                f'<span style="font-size:16px;line-height:1.55;color:{text};">'
                f'{_esc(it.get("text"))}{_link(it.get("url"), color)}</span></div>'
            )
        parts.append('</div></div>')

    if data.get("closing"):
        parts.append(
            f'<p style="font-size:16.5px;line-height:1.6;color:{soft};margin:22px 4px 8px;'
            f'font-style:italic;">{_esc(data["closing"])}</p>'
        )
    parts.append(
        f'<div style="margin:22px 4px 0;padding:16px 18px;'
        f'background:linear-gradient(135deg,rgba(124,155,255,0.12),rgba(192,140,255,0.12));'
        f'border:1px solid #2a2f4d;border-radius:14px;font-size:14.5px;line-height:1.65;'
        f'color:{soft};">\U0001F4AC <strong style="color:{text};">Reply to this email</strong> '
        f'to update anything - e.g. "finished the MAD-private PR", "add: book flights by Friday", '
        f'"more compilers, less crypto". I\'ll fold it into tomorrow\'s brief.</div>'
    )
    parts.append(
        f'<div style="text-align:center;color:{faint};font-size:12px;margin:18px 6px 4px;">'
        f'\u2728 Your personal Daily Digest \u00b7 reply anytime \u2728</div>'
    )
    parts.append("</div></div>")
    return "".join(parts)


def render_text(data: dict, when_human: str) -> str:
    lines = [f"DAILY DIGEST  -  {when_human}", "=" * 48, ""]
    if data.get("greeting"):
        lines += [data["greeting"], ""]
    if data.get("headline"):
        lines += [f"** {data['headline']} **", ""]
    for sec in data.get("sections", []):
        icon = (sec.get("icon") or "").strip()
        lines.append(f"{icon + ' ' if icon else ''}{sec.get('title','').upper()}")
        lines.append("-" * 40)
        if sec.get("summary"):
            lines.append(sec["summary"])
            if sec.get("items"):
                lines.append("")
        for it in sec.get("items", []):
            tag = {"high": "[!]", "medium": "[ ]", "low": "[.]"}.get(it.get("priority"), "[ ]")
            url = f"  {it['url']}" if it.get("url") else ""
            lines.append(f"  {tag} {it.get('text','')}{url}")
        lines.append("")
    if data.get("closing"):
        lines += [data["closing"], ""]
    return "\n".join(lines)


# --- delivery + scheduling -------------------------------------------------

def send_now(cfg: dict | None = None, *, when: datetime | None = None) -> dict:
    """Build and email the digest immediately. Returns the build result + status."""
    cfg = cfg or store.load_config()
    built = build_digest(cfg, when=when, consume=True)
    to_addr = (cfg.get("email_to") or "").strip()
    email_send.send_email(
        to_addr=to_addr,
        subject=built["subject"],
        html=built["html"],
        text=built["text"],
    )
    # Mark these updates as delivered so they don't repeat tomorrow.
    store.mark_included(built["update_ids"])
    today = (when or datetime.now()).strftime("%Y-%m-%d")
    store.save_state({
        "last_sent_date": today,
        "last_sent_at": (when or datetime.now()).strftime("%Y-%m-%d %H:%M:%S"),
        "last_subject": built["subject"],
        "last_update_count": built["update_count"],
        "last_used_llm": built["used_llm"],
        "last_error": "",
    })
    built["sent_to"] = to_addr
    return built


def is_due(cfg: dict | None = None, *, when: datetime | None = None) -> tuple:
    """Return (due: bool, reason: str) for the scheduler."""
    cfg = cfg or store.load_config()
    when = when or datetime.now()
    if not cfg.get("enabled"):
        return False, "scheduler disabled"
    if not (cfg.get("email_to") or "").strip():
        return False, "no recipient set"
    if not email_send.is_configured():
        return False, "SMTP not configured"
    send_time = (cfg.get("send_time") or "07:00").strip()
    try:
        hh, mm = (int(x) for x in send_time.split(":", 1))
    except (ValueError, TypeError):
        hh, mm = 7, 0
    target = when.replace(hour=hh, minute=mm, second=0, microsecond=0)
    if when < target:
        return False, f"before send time ({send_time})"
    today = when.strftime("%Y-%m-%d")
    if store.load_state().get("last_sent_date") == today:
        return False, "already sent today"
    return True, "due"


def run_scheduled_if_due(when: datetime | None = None) -> dict:
    """Called by the scheduler loop. Sends iff due; records any error in state."""
    when = when or datetime.now()
    cfg = store.load_config()
    due, reason = is_due(cfg, when=when)
    if not due:
        return {"sent": False, "reason": reason}
    # Atomically claim today's send across processes (prevents the Windows task and
    # this in-server scheduler from both sending). Only the winner proceeds.
    today = when.strftime("%Y-%m-%d")
    if not store.claim_send_slot(today):
        return {"sent": False, "reason": "already handled today"}
    try:
        built = send_now(cfg, when=when)
        return {"sent": True, "reason": "sent", "subject": built["subject"],
                "to": built.get("sent_to", "")}
    except Exception as exc:  # noqa: BLE001 - record and keep the loop alive
        store.release_send_slot(today)  # let a later retry run
        store.save_state({
            "last_error": f"{type(exc).__name__}: {exc}",
            "last_error_at": when.strftime("%Y-%m-%d %H:%M:%S"),
        })
        return {"sent": False, "reason": f"error: {exc}"}


def next_run_human(cfg: dict | None = None, *, when: datetime | None = None) -> str:
    cfg = cfg or store.load_config()
    if not cfg.get("enabled"):
        return "scheduler off"
    when = when or datetime.now()
    send_time = (cfg.get("send_time") or "07:00").strip()
    try:
        hh, mm = (int(x) for x in send_time.split(":", 1))
    except (ValueError, TypeError):
        hh, mm = 7, 0
    target = when.replace(hour=hh, minute=mm, second=0, microsecond=0)
    today = when.strftime("%Y-%m-%d")
    already = store.load_state().get("last_sent_date") == today
    if when < target and not already:
        return f"today at {send_time}"
    return f"tomorrow at {send_time}"
