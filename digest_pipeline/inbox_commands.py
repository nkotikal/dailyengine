"""Two-way digest: parse REPLIES to the digest email into actions.

When you reply to the morning email (it's sent from the Gmail account, so replies
land back there), this reads those replies over IMAP and uses the LLM to turn your
natural language into updates: complete/add tasks, add/remove interest topics, and
adjust a few preferences. Processed messages are remembered so they're applied once.
"""

import email as _email
import imaplib
import os
import re
from email.header import decode_header

from datetime import datetime, timedelta

from . import dayplan, korean, llm, memory, schedule, store, tasks


def _imap_cfg():
    return {
        "host": os.environ.get("IMAP_HOST", "imap.gmail.com"),
        "port": int(os.environ.get("IMAP_PORT", "993") or "993"),
        "user": os.environ.get("IMAP_USER") or os.environ.get("SMTP_USER"),
        "password": os.environ.get("IMAP_PASSWORD") or os.environ.get("SMTP_PASSWORD"),
    }


def is_configured() -> bool:
    c = _imap_cfg()
    return bool(c["user"] and c["password"])


def _decode(s) -> str:
    if not s:
        return ""
    out = []
    for part, enc in decode_header(s):
        if isinstance(part, bytes):
            try:
                out.append(part.decode(enc or "utf-8", errors="replace"))
            except (LookupError, TypeError):
                out.append(part.decode("utf-8", errors="replace"))
        else:
            out.append(part)
    return "".join(out)


def _body_text(msg) -> str:
    """Extract the plain-text body from an email.message.Message."""
    if msg.is_multipart():
        for part in msg.walk():
            if part.get_content_type() == "text/plain" and "attachment" not in str(
                    part.get("Content-Disposition", "")):
                payload = part.get_payload(decode=True)
                if payload:
                    return payload.decode(part.get_content_charset() or "utf-8", errors="replace")
        # fall back to any text
        for part in msg.walk():
            if part.get_content_type() == "text/html":
                payload = part.get_payload(decode=True)
                if payload:
                    return re.sub(r"(?s)<[^>]+>", " ",
                                  payload.decode(part.get_content_charset() or "utf-8", errors="replace"))
        return ""
    payload = msg.get_payload(decode=True)
    return payload.decode(msg.get_content_charset() or "utf-8", errors="replace") if payload else ""


def _strip_quoted(body: str) -> str:
    """Keep only the NEW text of a reply, dropping quoted history."""
    lines = []
    for ln in (body or "").splitlines():
        s = ln.strip()
        # Common quote separators.
        if re.match(r"^On .*wrote:$", s):
            break
        if s.startswith(">"):
            continue
        if re.match(r"^-{2,}\s*Original Message", s, re.I):
            break
        if re.match(r"^From:\s", s):  # forwarded/quoted header block
            break
        lines.append(ln)
    return "\n".join(lines).strip()


def fetch_replies(recipient: str) -> list:
    """Return unprocessed reply emails FROM the digest recipient."""
    c = _imap_cfg()
    if not (c["user"] and c["password"]):
        raise RuntimeError("IMAP not configured (set IMAP_USER/IMAP_PASSWORD or SMTP_*).")
    out = []
    M = imaplib.IMAP4_SSL(c["host"], c["port"])
    try:
        M.login(c["user"], c["password"])
        M.select("INBOX", readonly=True)
        crit = ["FROM", recipient] if recipient else ["ALL"]
        typ, data = M.search(None, *crit)
        ids = (data[0].split() if data and data[0] else [])[-25:]
        for i in reversed(ids):
            typ, msg_data = M.fetch(i, "(RFC822)")
            if not msg_data or not msg_data[0]:
                continue
            msg = _email.message_from_bytes(msg_data[0][1])
            mid = (msg.get("Message-ID") or msg.get("Message-Id") or i.decode()).strip()
            if store.reply_processed(mid):
                continue
            subj = _decode(msg.get("Subject"))
            body = _strip_quoted(_body_text(msg))
            if not body:
                store.mark_reply_processed(mid)
                continue
            out.append({"mid": mid, "subject": subj, "body": body[:4000]})
    finally:
        try:
            M.logout()
        except Exception:  # noqa: BLE001
            pass
    return out


PARSE_SYSTEM = """\
You convert a person's free-form email reply (often an END-OF-DAY reflection) into
structured updates for their daily-digest app. Capture EVERYTHING meaningful - no
detail may be lost, especially deadlines - while staying precise. Respond with ONLY
a JSON object:

{
  "complete": ["text of a task/subtask they say is done"],
  "accomplished": ["short factual statement of something they got done today"],
  "add_tasks": [{"text": "...", "priority": "critical|high|medium|low", "due": "YYYY-MM-DD or ''",
                 "parent": "optional: text of the task to nest this under"}],
  "reminders": [{"text": "a deadline/commitment", "due": "YYYY-MM-DD", "priority": "high|medium|low"}],
  "blockers": [{"type": "time|blocked|motivation|scope|health|other", "text": "what is holding them back"}],
  "mood": "great|good|ok|rough|bad or ''",
  "progress_quality": "strong|solid|mixed|thin|poor or ''",
  "whats_next": ["short statement of what they plan to do next"],
  "weekly_targets": ["a target/goal line for the rest of this week"],
  "schedule_for_tomorrow": "OPTIONAL planner-format text for tomorrow (see FORMAT) - ONLY if they described how they want to block/spend tomorrow",
  "add_interests": ["topic"],
  "remove_interests": ["topic"],
  "preferences": {"korean_enabled": true/false, "news_enabled": true/false,
                  "daily_capacity_hours": number, "send_time": "HH:MM"},
  "korean_practice": ["a Korean practice sentence the user wrote to be graded"],
  "note": "one short sentence summarizing what you applied"
}

RULES:
- Only include keys the reply actually implies; omit the rest. Empty {}/[] are fine.
- DEADLINES ARE CRITICAL: any due date, presentation, submission, or commitment with a
  time ("mid-internship presentation due next Friday") MUST go in "reminders" with an
  absolute "due" date. Resolve relative dates ("next Friday", "in two weeks", "by end
  of month") to YYYY-MM-DD using TODAY'S DATE given below. Never drop a deadline.
- "complete": match the user's wording to their existing tasks (listed below).
- "accomplished": what they did today (feeds "What's New" and long-term memory).
- "blockers": things impeding them (e.g. "lacking time", "blocked by xyz conflict",
  "lacking motivation"). Capture the type and a short description.
- "mood"/"progress_quality": your honest read of how the day went from their words.
- "weekly_targets": if they describe how they want to spend the coming days
  ("Friday focus on neuromorphic lab, Saturday finish compiler project"), turn each
  into a concise target line (include the day). These update the Weekly goals.
- "schedule_for_tomorrow": if (and only if) they described how to block TOMORROW,
  synthesize a planner-format schedule from their intent plus their open tasks.
- "korean_practice": ONLY Korean sentences the user explicitly wrote as practice.
- Never invent tasks, deadlines, or preferences they didn't mention.

PLANNER FORMAT (for schedule_for_tomorrow): a bare hour number on its own line is an
hour marker (9 = 9 AM, 12 = noon, 1 = 1 PM...). Lines indented one tab under an hour
are tasks; two tabs are subtasks. A leading ' marks important, ''' marks critical.
Example: "9\\n\\t'Deep work: compiler\\n12\\n\\tLunch\\n1\\n\\tNeuromorphic lab"."""


def _open_task_texts() -> str:
    lines = []

    def walk(nodes, depth):
        for n in nodes:
            if not n.get("done"):
                lines.append(("  " * depth) + "- " + n.get("text", ""))
            walk(n.get("subtasks") or [], depth + 1)
    walk(store.list_weekly_tasks(), 0)
    return "\n".join(lines) or "(none)"


def _find_node_id_by_text(phrase: str):
    """Best-effort match of a phrase to an existing task/subtask node id."""
    phrase = (phrase or "").strip().lower()
    if not phrase:
        return None
    best, best_score = None, 0

    def score(text):
        t = text.lower()
        if phrase in t or t in phrase:
            return max(len(phrase), 1)
        pw, tw = set(phrase.split()), set(t.split())
        return len(pw & tw)

    def walk(nodes):
        nonlocal best, best_score
        for n in nodes:
            sc = score(n.get("text", ""))
            if sc > best_score:
                best, best_score = n.get("id"), sc
            walk(n.get("subtasks") or [])
    walk(store.list_weekly_tasks())
    return best if best_score > 0 else None


def _apply(actions: dict, *, model: str | None = None) -> dict:
    applied = {"completed": 0, "added": 0, "reminders": 0, "accomplished": 0,
               "interests_added": 0, "interests_removed": 0, "prefs": 0,
               "reflection": False, "schedule_tomorrow": False, "weekly_targets": 0,
               "memory": {"added": 0, "updated": 0}}
    for phrase in actions.get("complete") or []:
        nid = _find_node_id_by_text(phrase)
        if nid and store.update_node(nid, {"done": True}):
            applied["completed"] += 1
    for t in actions.get("add_tasks") or []:
        if not isinstance(t, dict) or not t.get("text"):
            continue
        parent = t.get("parent")
        pid = _find_node_id_by_text(parent) if parent else None
        if pid:
            store.add_subtask(pid, t["text"], t.get("due", ""))
        else:
            store.add_weekly_task(t["text"], t.get("priority", "medium"),
                                  due=t.get("due", ""),
                                  est_minutes=tasks.parse_est(t.get("est_minutes", 0)))
        applied["added"] += 1

    # Deadlines: never dropped. Each becomes a dated reminder that escalates as it nears.
    for rem in actions.get("reminders") or []:
        if not isinstance(rem, dict) or not rem.get("text"):
            continue
        pr = rem.get("priority", "medium")
        pr = pr if pr in ("low", "medium", "high") else "medium"
        store.add_reminder(rem["text"], due=(rem.get("due") or "").strip(), priority=pr)
        applied["reminders"] += 1

    # Accomplishments -> "What's New" updates (folded into memory below too).
    accomplished = [str(a).strip() for a in (actions.get("accomplished") or []) if str(a).strip()]
    for a in accomplished:
        try:
            store.add_update(a)
            applied["accomplished"] += 1
        except ValueError:
            pass

    # Weekly targets / time-blocking for coming days -> merge into Weekly goals
    # (kept in the existing section to minimize clutter).
    targets = [str(x).strip() for x in (actions.get("weekly_targets") or []) if str(x).strip()]
    if targets:
        store.merge_weekly_goals(targets)
        applied["weekly_targets"] = len(targets)

    # A dynamically generated plan for tomorrow (dated so the morning digest knows
    # it's a fresh, for-today schedule when tomorrow arrives).
    sched_text = (actions.get("schedule_for_tomorrow") or "").strip()
    if sched_text:
        try:
            parsed = schedule.parse_schedule(sched_text)
            if parsed.get("blocks"):
                tomorrow = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")
                store.save_schedule(sched_text, parsed, for_date=tomorrow)
                applied["schedule_tomorrow"] = True
        except Exception:  # noqa: BLE001 - never let a bad plan break processing
            pass

    # End-of-day reflection (blockers / mood / progress) -> feeds next morning.
    blockers = [b for b in (actions.get("blockers") or []) if isinstance(b, dict) and b.get("text")]
    whats_next = [str(x).strip() for x in (actions.get("whats_next") or []) if str(x).strip()]
    mood = str(actions.get("mood") or "").strip()
    progress_quality = str(actions.get("progress_quality") or "").strip()
    if accomplished or blockers or whats_next or mood or progress_quality:
        reflection = {
            "accomplished": accomplished, "blockers": blockers,
            "whats_next": whats_next, "mood": mood,
            "progress_quality": progress_quality,
        }
        store.save_reflection(reflection)
        applied["reflection"] = True
        # Robustly fold durable parts of the reflection into long-term memory.
        try:
            mem = memory.incorporate_reflection(reflection, model=model)
            applied["memory"] = mem.get("applied", applied["memory"])
        except llm.DigestLLMError:
            pass

    if actions.get("add_interests"):
        store.add_interests(actions["add_interests"])
        applied["interests_added"] += len(actions["add_interests"])
    if actions.get("remove_interests"):
        store.remove_interests(actions["remove_interests"])
        applied["interests_removed"] += len(actions["remove_interests"])
    prefs = actions.get("preferences") or {}
    allowed = {}
    if "korean_enabled" in prefs:
        allowed["korean_enabled"] = bool(prefs["korean_enabled"])
    if "news_enabled" in prefs:
        allowed["news_enabled"] = bool(prefs["news_enabled"])
    if "daily_capacity_hours" in prefs:
        try:
            allowed["daily_capacity_hours"] = float(prefs["daily_capacity_hours"])
        except (TypeError, ValueError):
            pass
    if "send_time" in prefs and re.match(r"^\d{1,2}:\d{2}$", str(prefs["send_time"])):
        allowed["send_time"] = str(prefs["send_time"])
    if allowed:
        store.save_config(allowed)
        applied["prefs"] = len(allowed)
    # Grade any Korean practice sentences, store for today's card, and mark the
    # matching weekly theme words COMPLETE (completion = your own example sentence).
    practice = [s for s in (actions.get("korean_practice") or []) if str(s).strip()]
    if practice:
        today = datetime.now().strftime("%Y-%m-%d")
        kstate = store.load_korean()
        theme_words = [w.get("korean", "") for w in
                       (kstate.get("weekly") or {}).get("words", []) if w.get("korean")]
        lesson = store.korean_lesson_for(today) or {}
        vocab_ctx = ", ".join(f"{v.get('korean','')} ({v.get('english','')})"
                              for v in lesson.get("vocab", []))
        try:
            results = korean.grade_practice(practice, vocab_context=vocab_ctx,
                                            theme_words=theme_words, model=model)
            if results:
                store.save_korean_practice(today, results)
                applied["korean_graded"] = len(results)
                done_words = [r["word"] for r in results if r.get("word")]
                if done_words:
                    n = korean.mark_theme_completion(kstate, done_words, today)
                    if n:
                        store.save_korean(kstate)
                        applied["korean_completed"] = n
        except llm.DigestLLMError:
            pass
    return applied


def process_replies(*, model: str | None = None, deterministic_only: bool = False) -> dict:
    """Read new replies and apply them. Safe to call before each digest build.

    ``deterministic_only`` (used on OFFLINE sends) skips the LLM entirely: it applies
    only terse check-in replies (``done 1 3``) and leaves prose reflections unprocessed
    so they're picked up by the full LLM pass once the AI is reachable again.
    """
    cfg = store.load_config()
    recipient = (cfg.get("email_to") or "").strip()
    if not is_configured() or not recipient:
        return {"processed": 0, "applied": [], "skipped": "not configured"}
    try:
        replies = fetch_replies(recipient)
    except Exception as exc:  # noqa: BLE001 - never let this break the digest
        return {"processed": 0, "error": str(exc)}

    results = []
    open_texts = _open_task_texts()
    now = datetime.now()
    today = now.strftime("%Y-%m-%d")
    weekday = now.strftime("%A")
    processed = 0
    deferred = False
    for r in replies:
        body = r["body"]
        if deterministic_only:
            # Offline: only consume replies that are clearly just check-in commands.
            if dayplan.looks_like_checkin(body):
                results.append({"checkin": dayplan.apply_reply(body, now)})
                store.mark_reply_processed(r["mid"])
                processed += 1
            continue
        try:
            actions = llm.post_json(
                PARSE_SYSTEM,
                f"TODAY'S DATE: {today} ({weekday}). Resolve all relative dates to "
                f"absolute YYYY-MM-DD from this.\n\nCURRENT OPEN TASKS:\n{open_texts}\n\n"
                f"MY REPLY:\n{body}",
                model=model, temperature=0, max_tokens=2000)
        except llm.DigestLLMError as exc:
            # Provider down: DON'T mark processed (so the reply is retried once AI is
            # back) and DON'T lose it. Note the deferral for the digest to surface.
            deferred = True
            results.append({"error": str(exc), "deferred": True})
            break
        # Deterministic check-in first (numbered indices + response credit); this also
        # counts a reply as "responding" to the latest check-in for the score.
        checkin = dayplan.apply_reply(body, now)
        applied = _apply(actions, model=model)
        applied["checkin"] = checkin
        results.append({"note": str(actions.get("note") or "").strip(), "applied": applied})
        store.mark_reply_processed(r["mid"])
        processed += 1

    if deferred:
        store.save_state({"replies_deferred_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")})
    elif processed and not deterministic_only:
        store.save_state({"replies_deferred_at": ""})
    return {"processed": processed, "deferred": deferred, "applied": results}
