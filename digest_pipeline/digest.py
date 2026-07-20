"""Build, render, and send the daily digest; decide when it's due.

Isolated from the resume pipeline. Uses ``store`` for data, ``llm`` to compose
(optional), and ``email_send`` to deliver.
"""

import html as _html
import re
from urllib.parse import quote
from datetime import datetime, date

import user_context

from . import (dayplan, email_send, english, gcal, inbox_commands, korean, llm,
               memory, news, schedule, schedule_gen, store, tasks, trackers)

# Language practice tracks (the "korean_enabled" flag is the generic on/off switch).
_LANG_META = {
    "korean": {"title": "Korean Practice", "icon": "\U0001F1F0\U0001F1F7"},
    "english": {"title": "English Vocabulary", "icon": "\U0001F4D6"},
}

PRIORITY_ORDER = {"critical": -1, "high": 0, "medium": 1, "low": 2}
PRIORITY_COLOR = {"critical": "#ff3d71", "high": "#ff8f9c", "medium": "#ffd479", "low": "#7c9bff"}

# Granular "reference" sections - rendered compact/muted and pushed below the brief.
DETAIL_TITLES = {
    "schedule", "this week's tasks", "rest of this week", "routine", "tasks",
    "calendar", "korean practice", "english vocabulary", "language practice",
    "completed", "long-term goals",
}


def _reminder_done_link(text: str) -> str:
    """A one-tap mailto that replies 'Reminder done: <text>' so it closes reliably."""
    try:
        to = email_send.from_address()
    except Exception:  # noqa: BLE001
        to = ""
    if not to or not (text or "").strip():
        return ""
    body = f"Reminder done: {text.strip()}"
    return f"mailto:{quote(to)}?subject={quote('Reminder update')}&body={quote(body)}"


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


def _reflection_view(when: datetime):
    """Return (reflection_text, reflection_obj) for a recent, unconsumed end-of-day
    reflection so the next morning can address blockers/mood/progress honestly.

    Only surfaces a reflection dated within the last ~2 days that hasn't already been
    folded into a sent digest."""
    refl = store.load_reflection()
    if not refl:
        return "", None
    created = refl.get("created_at") or ""
    if created and created == (store.load_state().get("reflection_consumed_at") or ""):
        return "", refl
    try:
        rdate = date.fromisoformat(refl.get("date", ""))
        if (when.date() - rdate).days > 2:
            return "", refl
    except (ValueError, TypeError):
        pass
    lines = []
    if refl.get("accomplished"):
        lines.append("Accomplished: " + "; ".join(refl["accomplished"]))
    if refl.get("blockers"):
        lines.append("Blockers: " + "; ".join(
            f"{b.get('type','')}: {b.get('text','')}" for b in refl["blockers"]))
    if refl.get("whats_next"):
        lines.append("What's next: " + "; ".join(refl["whats_next"]))
    if refl.get("mood"):
        lines.append("Mood: " + refl["mood"])
    if refl.get("progress_quality"):
        lines.append("Progress quality: " + refl["progress_quality"])
    return "\n".join(lines), refl


def _rough_day(refl: dict | None) -> bool:
    """True if the reflection signals a poor day (for honest, real-talk framing)."""
    if not refl:
        return False
    return (refl.get("progress_quality") in ("thin", "poor")
            or refl.get("mood") in ("rough", "bad"))


# --- composition -----------------------------------------------------------

# Gritty fallback lines for offline mode (no LLM). Rotated by day.
_OFFLINE_MOTIVATION = [
    "Nobody's coming to do it for you. Good. Go take it.",
    "Discipline now, or regret later. Pick one and move.",
    "The work doesn't care how you feel. Start anyway.",
    "Small, brutal, consistent reps. That's the whole secret.",
    "You don't rise to your goals; you fall to your habits. Sharpen them today.",
    "Hard is the point. Do the hard thing first.",
    "Win the morning, drag the rest of the day with you.",
    "Quiet grind beats loud excuses. Get to it.",
]


# Honest "real talk" lines for a day that went poorly (offline; no coddling).
_OFFLINE_ROUGH = [
    "Yesterday was thin. One bad day is noise; two is a trend. Break it today.",
    "That wasn't your best and you know it. Good - use the sting. Move.",
    "Blocked or unmotivated, the deadline doesn't move. So neither do you. Start.",
    "Own the slow day, then bury it under a good one. Begin now.",
    "No spin: progress was weak. The fix isn't a feeling, it's the next rep.",
]


def _offline_motivation(d: date, rough: bool = False) -> str:
    pool = _OFFLINE_ROUGH if rough else _OFFLINE_MOTIVATION
    return pool[d.toordinal() % len(pool)]


def _korean_items(lesson: dict, practice: list | None = None) -> list:
    """Flat items for the Korean Practice section (vocab + grammar + culture + grading).

    Every example shows the Korean and its English translation.
    """
    items = []
    prog = (lesson or {}).get("weekly_progress") or {}
    if prog.get("theme"):
        items.append({"text": f"\U0001F4DA Weekly theme: {prog['theme']} \u2014 "
                              f"{prog.get('completed',0)}/{prog.get('total',0)} words completed",
                      "priority": "medium", "url": ""})
    if (lesson or {}).get("challenge"):
        items.append({"text": "\u2705 " + lesson["challenge"], "priority": "high", "url": ""})
    for v in (lesson or {}).get("vocab", []):
        rom = f" ({v['romanization']})" if v.get("romanization") else ""
        pos = f" [{v['pos']}]" if v.get("pos") else ""
        items.append({"text": f"{v.get('korean','')}{rom} \u2014 {v.get('english','')}{pos}",
                      "priority": "low", "url": ""})
        if v.get("example_ko"):
            ex = v["example_ko"] + (f"  =  {v['example_en']}" if v.get("example_en") else "")
            items.append({"text": "\u21B3 " + ex, "priority": "low", "url": ""})
    for g in (lesson or {}).get("grammar", []):
        form = f"  ({g['form']})" if g.get("form") else ""
        items.append({"text": f"\U0001F539 {g.get('point','')}{form} \u2014 {g.get('english','')}",
                      "priority": "low", "url": ""})
        if g.get("example_ko"):
            ex = g["example_ko"] + (f"  =  {g['example_en']}" if g.get("example_en") else "")
            items.append({"text": "\u21B3 " + ex, "priority": "low", "url": ""})
    if (lesson or {}).get("culture"):
        items.append({"text": "\U0001F3EF Culture: " + lesson["culture"], "priority": "low", "url": ""})
    if (lesson or {}).get("tip"):
        items.append({"text": "\U0001F4A1 Tip: " + lesson["tip"], "priority": "low", "url": ""})
    for p in (practice or []):
        items.append({"text": f"\u270D\uFE0F You: {p.get('sentence','')}  \u2014 {p.get('score','')}/100",
                      "priority": "low", "url": ""})
        fb = p.get("feedback", "")
        if p.get("corrected") and p.get("corrected") != p.get("sentence"):
            fb = f"\u2192 {p['corrected']}. {fb}"
        if fb:
            items.append({"text": "\u21B3 " + fb, "priority": "low", "url": ""})
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


def _resolve_headline_url(item: dict, news_items: list) -> str:
    """Map a composed headline to the EXACT fetched story URL. Prefers the model's
    'ref:N' index (reliable); falls back to keeping a real fetched URL, else a
    best-effort title match. Guarantees links never point to an unrelated place."""
    u = (item.get("url") or "").strip()
    m = re.match(r"^(?:ref:|#)\s*(\d+)\s*$", u, re.I)
    if m:
        i = int(m.group(1)) - 1
        if 0 <= i < len(news_items or []):
            return (news_items[i].get("url") or "").strip()
        return ""
    # A raw URL is only trusted if it's actually one of the fetched stories.
    if u and u in {(h.get("url") or "").strip() for h in (news_items or [])}:
        return u
    return _match_news_url(item.get("text", ""), news_items)


def _schedule_section(parsed: dict | None, title: str = "Schedule"):
    """Build a structured, time-chunked Schedule section from the parsed planner.

    Rendered specially (grouped by hour) for an easy-to-read email; goes dead last.
    """
    blocks = []
    for b in (parsed or {}).get("blocks", []):
        tasks = []
        for t in b.get("tasks", []):
            pr = "critical" if t.get("critical") else ("high" if t.get("important") else "medium")
            subs = [{"text": s.get("text", ""),
                     "priority": "critical" if s.get("critical") else ("high" if s.get("important") else "medium")}
                    for s in t.get("subtasks", []) if s.get("text")]
            if t.get("text"):
                tasks.append({"text": t["text"], "priority": pr, "subs": subs})
        if tasks:
            blocks.append({"time": b.get("time_str", ""), "tasks": tasks})
    if not blocks:
        return None
    return {"title": title, "icon": "\U0001F5D3\uFE0F", "kind": "schedule",
            "detail": True, "summary": "", "items": [], "blocks": blocks}


def _finalize_sections(data: dict, *, news_items=None, lang_title="",
                       lang_icon="", lang_items=None, schedule=None,
                       schedule_title="Schedule") -> dict:
    """Post-process the composed digest: real headline links, a complete language
    card, a clean time-chunked Schedule (dead last), and no empty cards."""
    secs = data.get("sections", [])
    if news_items:
        for s in secs:
            if s.get("title", "").strip().lower() == "headlines":
                kept = []
                for it in s.get("items", []):
                    it["url"] = _resolve_headline_url(it, news_items)
                    if it["url"]:  # drop any headline we can't link correctly
                        kept.append(it)
                s["items"] = kept
    # Replace whatever schedule the composer produced with our structured one.
    sched_section = _schedule_section(schedule, schedule_title)
    if sched_section:
        secs = [s for s in secs if s.get("title", "").strip().lower() != "schedule"
                and s.get("kind") != "schedule"]
    if lang_items:
        secs = [s for s in secs
                if s.get("title", "").strip().lower() not in
                (lang_title.lower(), "korean practice", "english vocabulary")]
        secs.append({"title": lang_title, "icon": lang_icon, "summary": "",
                     "items": lang_items, "detail": True})
    # Drop empty cards (prevents blank sections).
    secs = [s for s in secs if s.get("items") or (s.get("summary") or "").strip()]
    if sched_section:  # schedule goes at the very end
        secs.append(sched_section)
    data["sections"] = secs
    return data


def _deterministic_digest(cfg, updates, when_human, *, parsed_schedule=None,
                          calendar_events=None, findings=None, lang_title="",
                          lang_icon="", lang_items=None,
                          reminders=None, weekly_tasks=None, today=None,
                          news_items=None) -> dict:
    """A clean digest without the LLM: organize the raw inputs into sections."""
    def lines(blob):
        out = []
        for ln in (blob or "").splitlines():
            s = ln.strip().lstrip("-*").strip()
            if not s:
                continue
            text, pr, _imp = tasks._strip_priority(s)
            out.append({"text": text, "priority": pr})
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
            top.append({"title": "Reminders", "icon": "\u23F0", "items": ritems})

    # Headlines (contextual intel) - near the top, below priorities/deadlines.
    if news_items:
        hitems = [{"text": h["title"], "priority": "low", "url": h.get("url", "")}
                  for h in news_items[:6] if h.get("title")]
        if hitems:
            top.append({"title": "Headlines", "icon": "\U0001F4F0", "items": hitems})

    longterm_items = tasks.outline_items(cfg.get("longterm_goals") or cfg.get("goals") or "")
    if longterm_items:
        top.append({"title": "Long-Term Goals", "icon": "\U0001F3AF", "items": longterm_items})

    # --- BOTTOM: the granular day. Language practice sits ABOVE the full schedule,
    # which is the most granular item and goes dead last. ---
    if lang_items:
        bottom.append({"title": lang_title, "icon": lang_icon, "items": lang_items})

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
                pr = "critical" if t.get("critical") else ("high" if t["important"] else "medium")
                items.append({"text": txt, "priority": pr})
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
        "motivation": _offline_motivation(today or date.today()),
        "greeting": f"Good morning! Here's your plan for {when_human}.",
        "headline": "",
        "sections": sections,
        "closing": "Have a focused, productive day.",
    }


def _dayplan_block(plan: dict, reply_subject: str) -> dict:
    """A view model for the numbered, check-off-able 'Today's plan' card + mailto links."""
    from urllib.parse import quote
    to = email_send.from_address()
    sc = dayplan.score(plan)
    items = []
    for t in plan.get("tasks", []):
        body = f"done {t['idx']}"
        mailto = f"mailto:{quote(to)}?subject={quote(reply_subject)}&body={quote(body)}" if to else ""
        items.append({"idx": t["idx"], "text": t.get("text", ""),
                      "priority": t.get("priority", "medium"),
                      "annotation": t.get("annotation", ""),
                      "done": bool(t.get("done")), "mailto": mailto})
    return {"items": items, "score": sc}


def _normalize(data: dict) -> dict:
    """Coerce arbitrary model/deterministic output into a safe, sorted structure."""
    if not isinstance(data, dict):
        data = {}
    out = {
        "motivation": str(data.get("motivation") or "").strip(),
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
                 consume: bool = False, allow_defer: bool = False) -> dict:
    """Compose today's digest from every enabled module.

    ``consume`` True (a real send) advances tracker state so items aren't repeated;
    False (a preview) leaves state untouched. ``allow_defer`` enables the tiered
    AMD->OpenAI->offline fallback timeline (may raise SendDeferred before any work).
    """
    cfg = cfg or store.load_config()
    when = when or datetime.now()
    when_human = when.strftime("%A, %B %d, %Y")
    today_key = when.strftime("%Y-%m-%d")
    warnings = []

    # Choose the LLM provider for this whole run BEFORE any side effects (so a defer
    # consumes nothing). May raise SendDeferred for scheduled sends.
    chosen = _choose_llm(cfg, when, allow_defer=allow_defer)
    llm.set_active("openai" if chosen == "openai" else "anthropic", cfg.get("openai_model"))
    offline = (chosen == "offline")

    # On a real send with a working LLM: apply email replies first (reflections,
    # deadlines, plans), then evolve memory once per day so the brief reflects new
    # activity. When offline we must NOT try to parse replies (it would fail); they
    # stay unprocessed and we note that they weren't incorporated yet.
    if consume and not offline:
        try:
            inbox_commands.process_replies(model=(cfg.get("model") or None))
            cfg = store.load_config()  # reflect any preference changes
        except Exception:  # noqa: BLE001 - never let replies break the send
            pass
        if store.load_state().get("last_memory_evolve") != today_key:
            try:
                memory.evolve(model=(cfg.get("model") or None), when=when)
                store.save_state({"last_memory_evolve": today_key})
            except Exception:  # noqa: BLE001
                pass
    elif consume and offline and inbox_commands.is_configured():
        # Still apply terse check-in replies (indices) without the LLM; prose
        # reflections wait for a working AI.
        try:
            inbox_commands.process_replies(deterministic_only=True)
        except Exception:  # noqa: BLE001
            pass
        warnings.append("Offline: quick check-in replies were applied; any written "
                        "reflection will be incorporated once the AI is back.")

    updates = store.pending_updates()
    update_ids = [u["id"] for u in updates if u.get("id")]
    memory_text = memory.render_for_digest()
    profile_base = store.load_profile_base()
    reminders_text, reminder_rows = _reminders_view(when)
    reflection_text, reflection_obj = _reflection_view(when)
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

    # --- gather module inputs ---
    # Schedules are dated: only use the stored plan as "today's" if it was saved FOR
    # today. A stale carry-over is not presented as today's plan; instead we ask the
    # composer to suggest a light plan (and note it's auto-suggested).
    parsed_schedule = None
    schedule_text = ""
    schedule_note = ""
    if cfg.get("include_schedule", True):
        sched = store.load_schedule()
        stored_parsed = sched.get("parsed") or None
        for_date = sched.get("for_date") or ""
        if stored_parsed and for_date == today_key:
            parsed_schedule = stored_parsed
            schedule_text = schedule.render_text(parsed_schedule)
        else:
            # No schedule provided for today -> auto-assemble one (on a real send) from
            # the goals/tasks, deadlines, and recurring patterns in past schedules, and
            # save it FOR today so the check-in loop tracks concrete daily tasks.
            gen = None
            if consume and not offline:
                try:
                    gen = schedule_gen.generate_and_save(when, model=(cfg.get("model") or None))
                except Exception as exc:  # noqa: BLE001
                    warnings.append(f"Schedule generation failed ({exc}).")
            if gen:
                parsed_schedule = gen["parsed"]
                schedule_text = schedule.render_text(parsed_schedule)
                schedule_note = ("This schedule was auto-assembled from your goals, "
                                 "deadlines, and your usual daily patterns (you didn't "
                                 "provide one). Adjust by replying with how you want the day.")
            elif stored_parsed:
                schedule_note = (f"No schedule was set for today; the last saved plan was for "
                                 f"{for_date or 'a previous day'}. Suggest a light, realistic "
                                 f"plan for today from the open tasks and deadlines, and note "
                                 f"it's an auto-suggestion (not one I gave you).")
            else:
                schedule_note = ("No schedule was provided for today. Optionally suggest a "
                                 "light plan from the open tasks and deadlines, noting it's "
                                 "an auto-suggestion.")

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

    # Language practice (Korean or English vocab), dispatched by cfg.language.
    language = (cfg.get("language") or "korean").strip().lower()
    lang_meta = _LANG_META.get(language, _LANG_META["korean"])
    lang_title, lang_icon = lang_meta["title"], lang_meta["icon"]
    ui_ko = (cfg.get("ui_lang") or "en").lower().startswith("ko")
    if ui_ko:  # localize the deterministically-injected section titles
        lang_title = "\ud55c\uad6d\uc5b4 \uc5f0\uc2b5" if language == "korean" else "\uc601\uc5b4 \uc5b4\ud718"
    schedule_title = "\uc77c\uc815" if ui_ko else "Schedule"
    lang_text = ""
    lang_items = []
    if cfg.get("korean_enabled"):
        if language == "english":
            lesson = store.english_lesson_for(today_key)
            if lesson is None:
                try:
                    est = store.load_english()
                    lesson, nst = english.build_lesson(
                        est, level=cfg.get("english_level", "advanced"),
                        today=today_key, model=(cfg.get("model") or None), offline=offline)
                    store.save_english(nst)
                except llm.DigestLLMError as exc:
                    warnings.append(f"English lesson skipped ({exc}).")
            if lesson:
                lang_text = english.render_summary(lesson)
                lang_items = english.items(lesson)
        else:
            lesson = store.korean_lesson_for(today_key)
            if lesson is None:
                try:
                    kstate = store.load_korean()
                    lesson, new_kstate = korean.build_lesson(
                        kstate, level=cfg.get("korean_level", "intermediate"),
                        today=today_key, model=(cfg.get("model") or None), offline=offline)
                    store.save_korean(new_kstate)
                except llm.DigestLLMError as exc:
                    warnings.append(f"Korean lesson skipped ({exc}).")
            if lesson:
                lang_text = korean.render_summary(lesson)
                lang_items = _korean_items(lesson, store.get_korean_practice(today_key))

    # --- compose ---
    used_llm = False
    if offline:
        data = _deterministic_digest(cfg, updates, when_human,
                                     parsed_schedule=parsed_schedule,
                                     calendar_events=calendar_events,
                                     findings=findings, lang_title=lang_title,
                                     lang_icon=lang_icon, lang_items=lang_items,
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
                profile_base=profile_base,
                schedule_text=schedule_text,
                calendar_text=calendar_text,
                tracker_findings=findings,
                korean_summary=lang_text,
                language_title=lang_title,
                reminders_text=reminders_text,
                weekly_tasks_text=weekly_tasks_text,
                focus_load_text=focus_load_text,
                headlines_text=headlines_text,
                interests=interests,
                reflection_text=reflection_text,
                schedule_note=schedule_note,
                report_lang=cfg.get("ui_lang", "en"),
                model=(cfg.get("model") or None),
            )
            used_llm = True
        except llm.DigestLLMError as exc:
            data = _deterministic_digest(cfg, updates, when_human,
                                         parsed_schedule=parsed_schedule,
                                         calendar_events=calendar_events,
                                         findings=findings, lang_title=lang_title,
                                         lang_icon=lang_icon, lang_items=lang_items,
                                         reminders=reminder_rows, weekly_tasks=weekly_tasks,
                                         today=when.date(), news_items=news_items)
            warnings.append(f"LLM unavailable ({exc}); sent a plain digest instead.")

    data = _normalize(data)
    data = _finalize_sections(data, news_items=news_items, lang_title=lang_title,
                              lang_icon=lang_icon, lang_items=lang_items,
                              schedule=parsed_schedule, schedule_title=schedule_title)
    # Reminders due today / overdue: surfaced conspicuously at the very top.
    data["reminder_alerts"] = [r for r in reminder_rows
                               if r.get("days") is not None and r["days"] <= 0]
    if not data.get("motivation"):
        data["motivation"] = _offline_motivation(when.date(), rough=_rough_day(reflection_obj))

    # On a real send, mark this reflection as consumed so it isn't re-surfaced.
    if consume and reflection_obj and reflection_text:
        store.save_state({"reflection_consumed_at": reflection_obj.get("created_at", "")})
    llm.set_active("anthropic", None)  # reset provider context after the run
    headline = data["headline"] or "Your daily digest"
    subject = f"\u2600\ufe0f Daily Digest \u2014 {when.strftime('%a, %b %d')}"

    # Numbered, check-off-able plan for the accountability loop (only when the user
    # has turned on check-ins or the recap). Built on a real send so indices are stable.
    if consume and (cfg.get("checkins_enabled") or cfg.get("eod_recap_enabled")):
        try:
            plan = dayplan.build_day_plan(when, rebuild=True)
            data["dayplan"] = _dayplan_block(plan, f"Re: {subject}")
        except Exception:  # noqa: BLE001 - never let this break the send
            pass
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
    "reminders": ("#ff8f9c", "rgba(255,143,156,0.16)"),
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


# Sections that belong in the top "at a glance" zone (in this order). Everything
# else is pushed into the compact reference zone below the divider.
GLANCE_ORDER = {"today's focus": 0, "priorities": 0, "schedule": 1,
                "reminders": 2, "deadlines": 2}


def _section_key(sec: dict) -> str:
    if sec.get("kind") == "schedule":
        return "schedule"
    return (sec.get("title") or "").strip().lower()


def render_html(data: dict, when_human: str) -> str:
    """Inline-styled 'day at a glance' HTML email.

    The top is a tight, high-signal glance: top priority, the numbered check-off
    plan, and today's schedule timeline - what you act on. Everything else (news,
    progress, this week's full list, language practice, etc.) is compacted into a
    quiet reference zone below a divider, so the morning read is fast and focused.
    """
    bg = "#0b0e1a"
    card = "#141829"
    brd = "#232842"
    line = "rgba(255,255,255,0.06)"
    text = "#eef1fb"
    soft = "#b8bfd8"
    faint = "#7d86a5"
    fam = ("-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,"
           "sans-serif")
    shadow = "0 4px 16px rgba(5,7,20,0.35)"

    parts = [
        f'<div style="margin:0;padding:0;background:{bg};">',
        f'<div style="max-width:600px;margin:0 auto;padding:16px 14px 30px;'
        f'font-family:{fam};">',
        # Slim gradient header; the greeting is folded in so the top isn't stacked.
        f'<div style="background:linear-gradient(135deg,#5b6bf0,#8a5cf0);'
        f'border-radius:20px;padding:22px 22px;box-shadow:0 8px 24px rgba(91,107,240,0.28);">'
        f'<div style="font-size:12.5px;letter-spacing:3px;text-transform:uppercase;'
        f'color:rgba(255,255,255,0.85);font-weight:700;">\u2600\ufe0f Daily Brief</div>'
        f'<div style="font-size:25px;font-weight:800;color:#fff;margin-top:6px;'
        f'letter-spacing:-0.3px;">{_esc(when_human)}</div>'
        + (f'<div style="font-size:16px;line-height:1.5;color:rgba(255,255,255,0.9);'
           f'margin-top:8px;">{_esc(data["greeting"])}</div>' if data.get("greeting") else "")
        + '</div>',
    ]

    # Conspicuous alert for reminders due today / overdue - the one loud element.
    alerts = data.get("reminder_alerts") or []
    if alerts:
        rows_html = []
        for x in alerts:
            days = x.get("days")
            if days is not None and days < 0:
                tag, tagbg = f"OVERDUE {-days}d", "#ff2d55"
            else:
                tag, tagbg = "TODAY", "#ff8f2e"
            due = x.get("due") or ""
            due_html = (f" <span style='color:#ffd9d9;font-weight:600;font-size:14px;'>({_esc(due)})</span>"
                        if due else "")
            done_link = _reminder_done_link(x.get("text", ""))
            done_html = (f' <a href="{_esc(done_link)}" style="color:#5fe6b4;font-size:13px;'
                         f'font-weight:800;text-decoration:none;white-space:nowrap;">[\u2713 done]</a>'
                         if done_link else "")
            rows_html.append(
                f'<div style="padding:8px 0;border-top:1px solid rgba(255,255,255,0.12);">'
                f'<span style="background:{tagbg};color:#1a0000;font-size:11px;font-weight:800;'
                f'letter-spacing:.4px;padding:2px 7px;border-radius:5px;margin-right:8px;'
                f'white-space:nowrap;">{_esc(tag)}</span>'
                f'<span style="font-size:17px;line-height:1.5;color:#fff;font-weight:700;">'
                f'{_esc(x.get("text",""))}{due_html}</span>{done_html}</div>'
            )
        parts.append(
            f'<div style="margin:16px 2px 0;padding:14px 18px;border-radius:14px;'
            f'background:#2a0e18;border:1px solid #ff2d55;">'
            f'<div style="font-size:13px;letter-spacing:1.4px;text-transform:uppercase;'
            f'color:#ff7a95;font-weight:800;margin-bottom:2px;">\u23F0 Due today</div>'
            + "".join(rows_html) + '</div>'
        )

    if data.get("motivation"):
        parts.append(
            f'<div style="margin:16px 2px 0;padding:14px 16px;border-radius:12px;'
            f'background:rgba(255,126,182,0.08);border-left:4px solid #ff7eb6;">'
            f'<div style="font-size:17.5px;line-height:1.5;color:{text};font-weight:600;'
            f'font-style:italic;">{_esc(data["motivation"])}</div></div>'
        )

    if data.get("headline"):
        parts.append(
            f'<div style="background:{card};border:1px solid {brd};border-left:4px solid #8aa0ff;'
            f'border-radius:14px;padding:16px 18px;margin:16px 2px 4px;box-shadow:{shadow};">'
            f'<div style="font-size:11.5px;letter-spacing:1.4px;text-transform:uppercase;'
            f'color:#8aa0ff;font-weight:800;margin-bottom:5px;">\u2b50 Top priority</div>'
            f'<div style="font-size:20px;line-height:1.45;color:#fff;font-weight:700;">'
            f'{_esc(data["headline"])}</div></div>'
        )

    # Numbered "Today's plan" card (accountability loop): tap [✓ done] or reply "done N".
    dp = data.get("dayplan")
    have_plan = bool(dp and dp.get("items"))
    if have_plan:
        sc = dp.get("score", {})
        rows = []
        for it in dp["items"]:
            if it.get("done"):
                mark = '\u2705'
                tstyle = f'color:{faint};text-decoration:line-through;'
                quick = ""
            else:
                mark = (f'<span style="display:inline-block;min-width:22px;color:{soft};'
                        f'font-weight:800;">{it["idx"]}.</span>')
                tstyle = f'color:{text};font-weight:600;'
                quick = (f' <a href="{_esc(it["mailto"])}" style="color:#34d399;font-size:13px;'
                         f'font-weight:700;text-decoration:none;white-space:nowrap;">[\u2713 done]</a>'
                         if it.get("mailto") else "")
            flag = ("\u203c\ufe0f " if it["priority"] == "critical"
                    else ("\u2b50 " if it["priority"] == "high" else ""))
            ann = (f' <span style="color:{faint};font-size:13.5px;">({_esc(it["annotation"])})</span>'
                   if it.get("annotation") else "")
            rows.append(
                f'<div style="padding:8px 0;border-top:1px solid {line};">'
                f'<span style="display:inline-block;width:26px;">{mark}</span>'
                f'<span style="font-size:16.5px;line-height:1.5;{tstyle}">{flag}{_esc(it["text"])}</span>'
                f'{ann}{quick}</div>')
        parts.append(
            f'<div style="background:{card};border:1px solid {brd};border-left:4px solid #34d399;'
            f'border-radius:14px;padding:15px 18px;margin:16px 2px 4px;box-shadow:{shadow};">'
            f'<div style="margin-bottom:6px;"><span style="font-size:18.5px;font-weight:800;'
            f'color:{text};">\u2705 Today\u2019s plan</span>'
            f'<span style="float:right;font-size:13.5px;color:{soft};font-weight:700;padding-top:5px;">'
            f'{sc.get("done",0)}/{sc.get("count",0)} \u00b7 {sc.get("total",0)} pts</span></div>'
            + "".join(rows)
            + f'<div style="margin-top:10px;font-size:13.5px;color:{faint};line-height:1.5;">'
            f'Reply <strong style="color:{soft};">done 1 3</strong> as you finish. '
            f'I\u2019ll check in later and total your score.</div></div>')

    # --- partition sections into the glance zone vs. the reference zone ---
    glance, reference = [], []
    for sec in data.get("sections", []):
        k = _section_key(sec)
        if k in GLANCE_ORDER:
            # When the numbered plan is present it IS the focus list - don't also
            # show the LLM's "Today's Focus" prose (that's the clutter we're cutting).
            if have_plan and k in ("today's focus", "priorities"):
                continue
            glance.append(sec)
        else:
            reference.append(sec)
    glance.sort(key=lambda s: GLANCE_ORDER.get(_section_key(s), 9))

    def render_schedule(sec, color, icon, *, prominent):
        p = [
            f'<div style="background:{card};border:1px solid {brd};'
            f'border-left:{"4px" if prominent else "3px"} solid {color};'
            f'border-radius:14px;padding:15px 18px 9px;margin:0 2px {"14px" if prominent else "10px"};'
            f'{f"box-shadow:{shadow};" if prominent else ""}">'
            f'<div style="font-size:{"15px" if prominent else "12.5px"};font-weight:800;'
            f'letter-spacing:.4px;text-transform:uppercase;color:{color};margin-bottom:11px;">'
            f'{_esc(icon)} {_esc(sec.get("title",""))}</div>'
        ]
        for blk in sec.get("blocks", []):
            p.append(
                f'<div style="display:flex;gap:12px;padding:8px 0;border-top:1px solid {line};">'
                f'<div style="flex:0 0 60px;">'
                f'<span style="display:inline-block;background:{color};color:#0b0e1a;'
                f'font-size:12px;font-weight:800;padding:3px 8px;border-radius:6px;'
                f'white-space:nowrap;">{_esc(blk.get("time", ""))}</span></div>'
                f'<div style="flex:1 1 auto;">'
            )
            for t in blk.get("tasks", []):
                mark = ("\u203c\ufe0f " if t["priority"] == "critical"
                        else ("\u2b50 " if t["priority"] == "high" else ""))
                p.append(
                    f'<div style="font-size:16px;line-height:1.5;color:{text};'
                    f'font-weight:600;margin:0 0 2px;">{mark}{_esc(t["text"])}</div>'
                )
                for s in t.get("subs", []):
                    smark = ("\u203c\ufe0f " if s["priority"] == "critical"
                             else ("\u2b50 " if s["priority"] == "high" else "\u00b7 "))
                    p.append(
                        f'<div style="font-size:14px;line-height:1.45;color:{soft};'
                        f'margin:1px 0 1px 6px;">{smark}{_esc(s["text"])}</div>'
                    )
            p.append('</div></div>')
        p.append('</div>')
        return "".join(p)

    def render_brief(sec, color, tint, icon):
        p = [
            f'<div style="background:{card};border:1px solid {brd};border-left:4px solid {color};'
            f'border-radius:14px;padding:16px 18px;margin:0 2px 14px;box-shadow:{shadow};">'
            f'<div style="margin-bottom:10px;">{_badge(icon, tint)}'
            f'<span style="font-size:18.5px;font-weight:800;color:{color};'
            f'vertical-align:middle;">{_esc(sec.get("title",""))}</span></div>'
        ]
        if sec.get("summary"):
            p.append(
                f'<p style="font-size:17px;line-height:1.65;color:{text};margin:0 0 '
                f'{"12px" if sec.get("items") else "0"};">{_esc(sec["summary"])}</p>')
        for it in sec.get("items", []):
            dot = PRIORITY_COLOR.get(it.get("priority", "medium"), color)
            p.append(
                f'<div style="margin:0 0 9px;">'
                f'<span style="display:inline-block;width:9px;height:9px;border-radius:50%;'
                f'background:{dot};margin:0 10px 1px 0;vertical-align:middle;"></span>'
                f'<span style="font-size:16.5px;line-height:1.55;color:{text};">'
                f'{_esc(it.get("text"))}{_link(it.get("url"), color)}</span></div>'
            )
        p.append('</div>')
        return "".join(p)

    def render_compact(sec, color, icon):
        p = [
            f'<div style="background:rgba(255,255,255,0.02);border:1px solid {line};'
            f'border-left:3px solid {color};border-radius:12px;padding:12px 15px;margin:0 2px 10px;">'
            f'<div style="font-size:12.5px;font-weight:800;letter-spacing:.5px;'
            f'text-transform:uppercase;color:{color};margin-bottom:8px;">'
            f'{_esc(icon)} {_esc(sec.get("title",""))}</div>'
        ]
        if sec.get("summary"):
            p.append(
                f'<p style="font-size:14.5px;line-height:1.6;color:{soft};margin:0 0 '
                f'{"8px" if sec.get("items") else "0"};">{_esc(sec["summary"])}</p>')
        for it in sec.get("items", []):
            p.append(
                f'<div style="font-size:14.5px;line-height:1.55;color:{soft};'
                f'margin:0 0 5px;">{_esc(it.get("text"))}{_link(it.get("url"), color)}</div>'
            )
        p.append('</div>')
        return "".join(p)

    # --- glance zone (prominent) ---
    for sec in glance:
        color, tint = _theme(sec.get("title", ""))
        icon = (sec.get("icon") or "").strip()
        if sec.get("kind") == "schedule":
            parts.append(render_schedule(sec, color, icon, prominent=True))
        else:
            parts.append(render_brief(sec, color, tint, icon))

    # --- reference zone (compact), behind a subtle divider ---
    if reference:
        parts.append(
            f'<div style="margin:24px 6px 14px;border-top:1px solid {brd};line-height:0;">'
            f'<span style="display:inline-block;background:{bg};padding:0 12px;'
            f'position:relative;top:-8px;font-size:10.5px;letter-spacing:2.5px;'
            f'text-transform:uppercase;color:{faint};font-weight:700;">for reference</span></div>'
        )
        for sec in reference:
            color, tint = _theme(sec.get("title", ""))
            icon = (sec.get("icon") or "").strip()
            if sec.get("kind") == "schedule":
                parts.append(render_schedule(sec, color, icon, prominent=False))
            else:
                parts.append(render_compact(sec, color, icon))

    if data.get("closing"):
        parts.append(
            f'<p style="font-size:16px;line-height:1.6;color:{soft};margin:20px 4px 8px;'
            f'font-style:italic;">{_esc(data["closing"])}</p>'
        )
    parts.append(
        f'<div style="margin:20px 2px 0;padding:15px 16px;background:rgba(124,155,255,0.08);'
        f'border:1px solid {brd};border-radius:12px;font-size:14.5px;line-height:1.6;'
        f'color:{soft};">\U0001F4AC <strong style="color:{text};">Reply</strong> to update anything '
        f'\u2014 "finished the PR", "add: book flights by Friday", "more compilers, less crypto". '
        f'It shapes tomorrow\u2019s brief.</div>'
    )
    parts.append(
        f'<div style="text-align:center;color:{faint};font-size:12px;margin:16px 6px 4px;">'
        f'Daily Digest \u00b7 reply anytime</div>'
    )
    parts.append("</div></div>")
    return "".join(parts)


def render_text(data: dict, when_human: str) -> str:
    lines = [f"DAILY DIGEST  -  {when_human}", "=" * 48, ""]
    alerts = data.get("reminder_alerts") or []
    if alerts:
        lines.append("!! REMINDERS FOR TODAY !!")
        for x in alerts:
            days = x.get("days")
            tag = f"OVERDUE {-days}d" if (days is not None and days < 0) else "TODAY"
            due = f" ({x.get('due')})" if x.get("due") else ""
            lines.append(f"  [{tag}] {x.get('text','')}{due}")
        lines.append("")
    if data.get("motivation"):
        lines += [f">> {data['motivation']}", ""]
    if data.get("greeting"):
        lines += [data["greeting"], ""]
    if data.get("headline"):
        lines += [f"** {data['headline']} **", ""]
    dp = data.get("dayplan")
    if dp and dp.get("items"):
        sc = dp.get("score", {})
        lines.append(f"TODAY'S PLAN  ({sc.get('done',0)}/{sc.get('count',0)} done, "
                     f"{sc.get('total',0)} pts)")
        lines.append("-" * 40)
        for it in dp["items"]:
            box = "[x]" if it.get("done") else f"{it['idx']}."
            flag = "!! " if it["priority"] == "critical" else ("* " if it["priority"] == "high" else "")
            ann = f"  ({it['annotation']})" if it.get("annotation") else ""
            lines.append(f"  {box} {flag}{it['text']}{ann}")
        lines += ["", "Reply 'done 1 3' as you finish (or say it in words).", ""]
    for sec in data.get("sections", []):
        icon = (sec.get("icon") or "").strip()
        lines.append(f"{icon + ' ' if icon else ''}{sec.get('title','').upper()}")
        lines.append("-" * 40)
        if sec.get("kind") == "schedule":
            for blk in sec.get("blocks", []):
                lines.append(f"  {blk.get('time','')}")
                for t in blk.get("tasks", []):
                    mark = "!! " if t["priority"] == "critical" else ("* " if t["priority"] == "high" else "")
                    lines.append(f"      - {mark}{t['text']}")
                    for s in t.get("subs", []):
                        lines.append(f"          . {s['text']}")
            lines.append("")
            continue
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

class SendDeferred(Exception):
    """Raised when a scheduled send is postponed (waiting for a better LLM)."""


# Tiered fallback timeline after send time (scheduled sends):
#   0-1h: AMD gateway only (defer/retry if down)
#   1-2h: AMD down -> use the chosen OpenAI model
#   >=2h: both down -> plain offline digest
_OPENAI_AFTER_HOURS = 1
_OFFLINE_AFTER_HOURS = 2


def _hours_since_send_time(cfg: dict, when: datetime) -> float:
    send_time = (cfg.get("send_time") or "07:00").strip()
    try:
        hh, mm = (int(x) for x in send_time.split(":", 1))
    except (ValueError, TypeError):
        hh, mm = 7, 0
    target = when.replace(hour=hh, minute=mm, second=0, microsecond=0)
    return (when - target).total_seconds() / 3600.0


def _choose_llm(cfg: dict, when: datetime, *, allow_defer: bool):
    """Decide which provider to use: 'anthropic' | 'openai' | 'offline'.

    Scheduled sends (allow_defer=True) follow the AMD->1h OpenAI->2h offline timeline.
    Interactive builds (preview/manual) just use the best provider available now.
    """
    if cfg.get("offline"):
        return "offline"
    anthropic_in_play = llm.have_key()          # is an AMD/Anthropic gateway configured?
    anthropic_ok = anthropic_in_play and llm.reachable()
    if anthropic_ok:
        return "anthropic"
    openai_ok = llm.openai_configured() and llm.openai_reachable()
    # No primary gateway configured at all (e.g. AMD gone) -> use OpenAI now; no waiting.
    if not anthropic_in_play:
        return "openai" if openai_ok else "offline"
    if not allow_defer:
        return "openai" if openai_ok else "offline"
    elapsed = _hours_since_send_time(cfg, when)
    if elapsed >= _OFFLINE_AFTER_HOURS:
        return "openai" if openai_ok else "offline"
    if elapsed >= _OPENAI_AFTER_HOURS and openai_ok:
        return "openai"
    raise SendDeferred("Primary LLM down; waiting before falling back.")


def send_now(cfg: dict | None = None, *, when: datetime | None = None,
             defer_if_llm_down: bool = False) -> dict:
    """Build and email the digest immediately. Returns the build result + status.

    Scheduled sends pass ``defer_if_llm_down`` so the tiered fallback applies; if the
    primary LLM is down and it's too early to fall back, ``SendDeferred`` is raised
    BEFORE building (no side effects consumed) and the caller retries later.
    """
    cfg = cfg or store.load_config()
    when = when or datetime.now()
    built = build_digest(cfg, when=when, consume=True, allow_defer=defer_if_llm_down)
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
        built = send_now(cfg, when=when, defer_if_llm_down=True)
        return {"sent": True, "reason": "sent", "subject": built["subject"],
                "to": built.get("sent_to", "")}
    except SendDeferred:
        store.release_send_slot(today)  # not sent; retry on a later tick
        return {"sent": False, "reason": "deferred (LLM unreachable; will retry)"}
    except Exception as exc:  # noqa: BLE001 - record and keep the loop alive
        store.release_send_slot(today)  # let a later retry run
        store.save_state({
            "last_error": f"{type(exc).__name__}: {exc}",
            "last_error_at": when.strftime("%Y-%m-%d %H:%M:%S"),
        })
        return {"sent": False, "reason": f"error: {exc}"}


def run_scheduled_for_all_users(when: datetime | None = None) -> list:
    """Send each user's digest if it's due (per-user send time + enabled flag).

    Iterates every user with their own isolated data; failures for one user never
    block the others. Used by both the in-server scheduler and the headless task.
    """
    when = when or datetime.now()
    results = []
    for u in user_context.list_users():
        with user_context.using_user(u["id"]):
            try:
                res = run_scheduled_if_due(when)
            except Exception as exc:  # noqa: BLE001 - isolate per-user failures
                res = {"sent": False, "reason": f"error: {exc}"}
        results.append({"user": u["id"], "name": u.get("name", ""), **res})
    return results


def force_send_for_all_users(when: datetime | None = None) -> list:
    """Send every enabled user's digest now, ignoring the send-time/already-sent
    guards (used by ``send_digest.py --force`` for testing). Still requires a
    recipient and SMTP to be configured."""
    when = when or datetime.now()
    results = []
    if not email_send.is_configured():
        return [{"user": "*", "sent": False, "reason": "SMTP not configured"}]
    for u in user_context.list_users():
        with user_context.using_user(u["id"]):
            cfg = store.load_config()
            to = (cfg.get("email_to") or "").strip()
            if not to:
                results.append({"user": u["id"], "name": u.get("name", ""),
                                "sent": False, "reason": "no recipient"})
                continue
            try:
                built = send_now(cfg, when=when, defer_if_llm_down=False)
                res = {"sent": True, "reason": "sent", "to": built.get("sent_to", "")}
            except Exception as exc:  # noqa: BLE001
                res = {"sent": False, "reason": f"error: {exc}"}
            results.append({"user": u["id"], "name": u.get("name", ""), **res})
    return results


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