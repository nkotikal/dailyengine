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

from . import llm, store, tasks


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
You convert a person's email reply into structured updates for their daily-digest
app. Respond with ONLY a JSON object:

{
  "complete": ["text of a task/subtask they say is done"],
  "add_tasks": [{"text": "...", "priority": "high|medium|low", "due": "YYYY-MM-DD or ''",
                 "parent": "optional: text of the task to nest this under"}],
  "add_interests": ["topic"],
  "remove_interests": ["topic"],
  "preferences": {"korean_enabled": true/false, "news_enabled": true/false,
                  "daily_capacity_hours": number, "send_time": "HH:MM"},
  "note": "one short sentence summarizing what you applied"
}

RULES:
- Only include keys the reply actually implies; omit the rest. Empty {}/[] are fine.
- "complete": match the user's wording to their existing tasks (provided below).
- Interests shape which news headlines they see and topics emphasized over time.
- Never invent tasks/preferences they didn't mention."""


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


def _apply(actions: dict) -> dict:
    applied = {"completed": 0, "added": 0, "interests_added": 0,
               "interests_removed": 0, "prefs": 0}
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
    return applied


def process_replies(*, model: str | None = None) -> dict:
    """Read new replies and apply them. Safe to call before each digest build."""
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
    for r in replies:
        try:
            actions = llm.post_json(
                PARSE_SYSTEM,
                f"CURRENT OPEN TASKS:\n{open_texts}\n\nMY REPLY:\n{r['body']}",
                model=model, temperature=0, max_tokens=1500)
            applied = _apply(actions)
            results.append({"note": str(actions.get("note") or "").strip(), "applied": applied})
        except llm.DigestLLMError as exc:
            results.append({"error": str(exc)})
        finally:
            store.mark_reply_processed(r["mid"])
    return {"processed": len(replies), "applied": results}
