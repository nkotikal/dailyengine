"""Self-contained Anthropic-compatible gateway client for the Daily Digest.

Deliberately independent of the resume pipeline (so neither can break the other),
but it reads the SAME environment variables so one .env configures both:
  ANTHROPIC_API_KEY, ANTHROPIC_BASE_URL, ANTHROPIC_AUTH_STYLE, ANTHROPIC_MODEL.

Standard library only (urllib).
"""

import json
import os
import urllib.error
import urllib.request

DEFAULT_BASE_URL = "https://api.anthropic.com"
ANTHROPIC_VERSION = "2023-06-01"
DEFAULT_MODEL = "claude-opus-4-8"
API_KEY_ENV = "ANTHROPIC_API_KEY"
BASE_URL_ENV = "ANTHROPIC_BASE_URL"
AUTH_STYLE_ENV = "ANTHROPIC_AUTH_STYLE"
MODEL_ENV = "ANTHROPIC_MODEL"


class DigestLLMError(RuntimeError):
    pass


def have_key() -> bool:
    return bool(os.environ.get(API_KEY_ENV))


# Active provider context: build_digest sets this so every LLM call in a run (compose,
# korean, memory, replies) uses the same provider/model. ("anthropic" or "openai").
_ACTIVE = {"provider": "anthropic", "model": None}


def set_active(provider: str, model: str | None = None) -> None:
    _ACTIVE["provider"] = provider if provider in ("anthropic", "openai") else "anthropic"
    _ACTIVE["model"] = model


def openai_configured() -> bool:
    import openai_compat
    return openai_compat.configured()


def openai_reachable() -> bool:
    import openai_compat
    return openai_compat.reachable()


def reachable(timeout: int = 4) -> bool:
    """Cheap check that the LLM gateway host resolves (catches the off-VPN/DNS case
    that silently degrades the morning digest)."""
    import socket
    import urllib.parse
    base = os.environ.get(BASE_URL_ENV) or DEFAULT_BASE_URL
    host = urllib.parse.urlparse(base).hostname
    if not host:
        return False
    try:
        socket.setdefaulttimeout(timeout)
        socket.getaddrinfo(host, 443)
        return True
    except OSError:
        return False


def resolve_model(model: str | None) -> str:
    return model or os.environ.get(MODEL_ENV) or DEFAULT_MODEL


SYSTEM_PROMPT = """\
You are a calm, trusted personal chief-of-staff who writes a person's morning daily
digest. Your guiding philosophy: organization of life and headspace is key. The
digest should leave the reader feeling clear and grounded, not overwhelmed - it
exists to OFFLOAD mental clutter, not add to it. You receive what the person told
you about themselves, their goals, their standing tasks, and NEW UPDATES since the
last digest. Produce a clear, compartmentalized, calm plan for their day.

HEADSPACE PRINCIPLES (apply throughout):
- Lead with ONE clear thing to focus on first; never open with a wall of items.
- Protect attention: surface only what matters today; defer or briefly list the rest.
- Be concise and scannable - short lines, no filler, no nagging. White space is calm.
- Respect capacity: if the day looks overloaded, gently suggest deferring lower items
  rather than implying everything must happen today.
- Close with a short, steadying encouragement.

VOICE - A CREATIVE, WARM SECRETARY WRITING A REAL REPORT (not a robot, not a list dump):
- Imagine a sharp, personable executive secretary briefing someone they genuinely
  care about. Warm, human, articulate - a little personality and color is welcome.
- This is a REPORT: each top section opens with a few sentences of real prose that
  frame what matters, why, and what to do - then a few bullets where a list helps.
- Track progress and momentum out loud ("the PR work is basically closed; kernels are
  the next front"). Connect things; add insight, not just status.
- EMPHASIZE PRIORITY ITEMS: a leading ' marks a high priority; a leading ''' marks a
  CRITICAL ("double") priority. Critical items must lead Today's Focus and be clearly
  emphasized (use priority "critical"); high ones come next. Treat overdue / due-today
  items as urgent too.
- Length: a proper morning report, roughly 250-450 words. Substantial enough to feel
  like a briefing, tight enough to read in ~2 minutes. Don't pad; don't be terse to
  the point of cold.

OUTPUT FORMAT (strict):
- Respond with ONLY a single valid JSON object. No markdown, no code fences, no
  commentary before or after.
- Schema:
  {
    "motivation": "a short, GRITTY line for the very top - punchy and a little raw, like "
                  "a coach before a hard day. No corny clichés or hashtags; earned, real, "
                  "a bit edgy. If a reflection is provided and the day went poorly or I was "
                  "blocked/unmotivated, be HONEST and direct about it (tell it like it is, "
                  "constructively) instead of generic hype. 1-2 sentences, fresh each day.",
    "greeting": "a warm, personal 1-2 sentence opener referencing the day",
    "headline": "one sentence: the single most important thing today",
    "sections": [
      {
        "title": "Section name",
        "icon": "one emoji that fits the section",
        "summary": "TOP sections: 1-3 sentences of warm, insightful prose that frames "
                   "and interprets. BOTTOM/detail sections: usually \"\" (just a list).",
        "items": [ {"text": "a concrete line", "priority": "critical|high|medium|low",
                    "url": "optional link (REQUIRED for headline items)"} ]
      }
    ],
    "closing": "a warm, genuine sign-off (1 sentence)"
  }
- "items" is optional per section; lean on prose where it reads better, lists where
  enumeration helps.

STRUCTURE - inverted pyramid (what matters up top, granular day at the very bottom):
  THE BRIEF (top - prose-rich, the heart of the report):
  1. "Today's Focus" - the 2-4 things that move the needle, the single most important
     first. Open with a few sentences; PRIORITY (') tasks must be emphasized here.
  2. "Reminders" - upcoming deadlines: overdue / due-soon items and approaching dates.
     Each: what + when + why it matters; flag overdue/today as high. DEADLINES MUST
     NEVER BE DROPPED - include every active reminder, and as a date nears make it more
     prominent. Omit the section only if there are truly none.
  3. "Headlines" - the 3-5 news items most relevant to my interests, one crisp take
     each. Omit if none.
  4. "What's New" - notable updates/tracker developments, synthesized. Omit if none.

  QUICK SITUATIONAL AWARENESS:
  5. "Progress" - a sentence or two on momentum. NOTE: my weekly top-level entries
     are CATEGORIES/areas (e.g. "AMD", "Applications"), not individual tasks - never
     say "0/5 tasks". Speak in terms of concrete tasks completed within areas, or by
     area (e.g. "AMD is moving - PRs nearly merged; Applications not started yet").

  THE DETAIL (bottom - leaner, mostly lists, minimal prose):
  6. "This Week's Tasks" - remaining open tasks not already in Today's Focus.
  7. Language practice / vocab - if provided; include verbatim. Goes ABOVE the schedule.
  8. Schedule - do NOT create your own "Schedule" section; the full time-blocked day
     is appended automatically from my planner. Instead, pull the important scheduled
     items up into "Today's Focus". Only if NO schedule was provided (see SCHEDULE
     STATUS) may you add a light suggested plan labeled "(auto-suggested)"; never
     fabricate fixed appointments.
- Do NOT create a "Routine" section.

- Never repeat a Today's Focus item verbatim down in the detail lists.
- NO INFORMATION LOSS: when a schedule is provided, every task/subtask appears in the
  Schedule section (and the important ones also in Today's Focus).
- For the Schedule, prefix each item with its time (e.g. "11 AM - ...").
- NESTING: tab-indented input (or indented "\u21B3" items) are SUBTASKS of the line
  above - preserve the hierarchy (indent subtasks under their parent).
- Don't fabricate facts, appointments, or numbers not implied by the input.
- Omit any section with no real input. Keep the warm close to one line.

- Always include "motivation": one fresh, gritty, motivational line that sits at the
  very top - make it land. Vary it day to day; tie it to the day's actual grind when
  you can.

Return the digest JSON now."""


def _headers(key: str, style: str) -> dict:
    h = {"anthropic-version": ANTHROPIC_VERSION, "content-type": "application/json"}
    if style == "bearer":
        h["Authorization"] = f"Bearer {key}"
    elif style in ("apim", "subscription", "ocp"):
        h["Ocp-Apim-Subscription-Key"] = key
    else:
        h["x-api-key"] = key
    return h


def _extract_text(payload: dict) -> str:
    blocks = payload.get("content") or []
    parts = [b.get("text", "") for b in blocks if isinstance(b, dict) and b.get("type") == "text"]
    text = "".join(parts).strip()
    if not text:
        raise DigestLLMError("LLM returned no text content.")
    return text


def _parse_json(text: str) -> dict:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.split("\n", 1)[-1]
        if cleaned.rstrip().endswith("```"):
            cleaned = cleaned.rstrip()[:-3]
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        start, end = cleaned.find("{"), cleaned.rfind("}")
        if start != -1 and end > start:
            try:
                return json.loads(cleaned[start:end + 1])
            except json.JSONDecodeError as exc:
                raise DigestLLMError(f"Could not parse JSON from model output: {exc}") from exc
        raise DigestLLMError("Model output did not contain a JSON object.")


def post_json(
    system: str,
    user: str,
    *,
    model: str | None = None,
    temperature: float = 0.3,
    max_tokens: int = 2048,
    timeout: int = 120,
    provider: str | None = None,
) -> dict:
    """Generic 'return a JSON object' chat call. Routes to the active provider
    (Anthropic AMD gateway by default, or OpenAI fallback)."""
    prov = provider or _ACTIVE.get("provider", "anthropic")
    if prov == "openai":
        import openai_compat
        om = _ACTIVE.get("model") or "gpt-5.4-mini"
        try:
            return openai_compat.post_json(system, user, model=om, temperature=temperature,
                                           max_tokens=max_tokens, timeout=timeout)
        except openai_compat.OpenAIError as exc:
            raise DigestLLMError(str(exc)) from exc
    key = os.environ.get(API_KEY_ENV)
    if not key:
        raise DigestLLMError(
            f"{API_KEY_ENV} is not set. Configure it in .env, or use Offline mode."
        )
    base = (os.environ.get(BASE_URL_ENV) or DEFAULT_BASE_URL).rstrip("/")
    style = (os.environ.get(AUTH_STYLE_ENV) or "x-api-key").lower()
    body = {
        "model": resolve_model(model),
        "max_tokens": max_tokens,
        "temperature": temperature,
        "system": system,
        "messages": [{"role": "user", "content": user}],
    }
    req = urllib.request.Request(
        base + "/v1/messages",
        data=json.dumps(body).encode("utf-8"),
        method="POST",
        headers=_headers(key, style),
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise DigestLLMError(f"LLM HTTP {exc.code}: {detail}") from exc
    except urllib.error.URLError as exc:
        raise DigestLLMError(f"Network error calling LLM: {exc.reason}") from exc
    return _parse_json(_extract_text(payload))


def post_text(
    system: str,
    user: str,
    *,
    model: str | None = None,
    temperature: float = 0.3,
    max_tokens: int = 2048,
    timeout: int = 120,
    provider: str | None = None,
) -> str:
    """Like ``post_json`` but returns the model's raw TEXT (no JSON parsing).

    Used for free-form outputs such as a generated planner-format schedule."""
    prov = provider or _ACTIVE.get("provider", "anthropic")
    if prov == "openai":
        import openai_compat
        om = _ACTIVE.get("model") or "gpt-5.4-mini"
        try:
            if hasattr(openai_compat, "post_text"):
                return openai_compat.post_text(system, user, model=om,
                                               temperature=temperature,
                                               max_tokens=max_tokens, timeout=timeout)
        except openai_compat.OpenAIError as exc:  # noqa
            raise DigestLLMError(str(exc)) from exc
        raise DigestLLMError("Text generation not available on the OpenAI provider.")
    key = os.environ.get(API_KEY_ENV)
    if not key:
        raise DigestLLMError(f"{API_KEY_ENV} is not set. Configure it in .env, or use Offline mode.")
    base = (os.environ.get(BASE_URL_ENV) or DEFAULT_BASE_URL).rstrip("/")
    style = (os.environ.get(AUTH_STYLE_ENV) or "x-api-key").lower()
    body = {
        "model": resolve_model(model),
        "max_tokens": max_tokens,
        "temperature": temperature,
        "system": system,
        "messages": [{"role": "user", "content": user}],
    }
    req = urllib.request.Request(
        base + "/v1/messages", data=json.dumps(body).encode("utf-8"),
        method="POST", headers=_headers(key, style))
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise DigestLLMError(f"LLM HTTP {exc.code}: {detail}") from exc
    except urllib.error.URLError as exc:
        raise DigestLLMError(f"Network error calling LLM: {exc.reason}") from exc
    return _extract_text(payload)


def compose_digest(
    *,
    about: str,
    weekly_goals: str = "",
    longterm_goals: str = "",
    tasks: str,
    updates: list,
    when_human: str,
    tone: str = "friendly and concise",
    memory_text: str = "",
    profile_base: str = "",
    schedule_text: str = "",
    calendar_text: str = "",
    tracker_findings: list | None = None,
    korean_summary: str = "",
    language_title: str = "Korean Practice",
    reminders_text: str = "",
    weekly_tasks_text: str = "",
    focus_load_text: str = "",
    headlines_text: str = "",
    interests: list | None = None,
    reflection_text: str = "",
    schedule_note: str = "",
    report_lang: str = "en",
    model: str | None = None,
    timeout: int = 150,
    max_tokens: int = 4096,
) -> dict:
    """Ask the model for a structured digest. Returns the parsed JSON object."""
    update_lines = "\n".join(f"- {u.get('text','').strip()}" for u in updates if u.get("text"))
    finding_lines = []
    for f in (tracker_findings or []):
        finding_lines.append(f"[{f.get('source','tracker')}] {f.get('text','')}")
    parts = [
        f"DATE: {when_human}",
        f"TONE: {tone}",
    ]
    if (report_lang or "en").lower().startswith("ko"):
        parts.append(
            "OUTPUT LANGUAGE: Write the ENTIRE digest in natural, fluent Korean - the "
            "motivation, greeting, headline, every section title and summary, and all "
            "items. Keep proper nouns, code identifiers, and established English tech "
            "terms as-is where a Korean reader would expect them. Section titles should "
            "be their natural Korean equivalents (e.g. '\uc624\ub298\uc758 \uc9d1\uc911', "
            "'\ub9ac\ub9c8\uc778\ub354', '\ud5e4\ub4dc\ub77c\uc778', '\uc77c\uc815')."
        )
    parts += [
        f"ABOUT ME:\n{about.strip() or '(not provided)'}",
        f"MY LONG-TERM GOALS (may include target dates):\n{longterm_goals.strip() or '(not provided)'}",
    ]
    if weekly_tasks_text.strip():
        parts.append(
            "MY WEEKLY TASK LIST. Each open task shows <importance, due, est> and "
            "reasons; items tagged [FOCUS] are the triaged important/imminent ones. "
            "TRIAGE FOR PRESENTATION:\n"
            "- Put the [FOCUS] tasks (and any overdue/due-today items) in 'Today's "
            "Focus', ordered by urgency then importance; keep their due/est annotations.\n"
            "- List the remaining open tasks briefly under 'This Week's Tasks' (one line "
            "each) - do NOT expand or over-explain them; keep the email uncluttered.\n"
            "- Acknowledge completed work in a single short line.\n"
            "- Do not invent tasks beyond this list and the schedule.\n"
            + weekly_tasks_text.strip()
        )
    else:
        parts.append(f"MY GOALS THIS WEEK:\n{weekly_goals.strip() or '(not provided)'}")
    if focus_load_text.strip():
        parts.append("FOCUS LOAD vs CAPACITY (for headspace; mention briefly, and if "
                     "over capacity gently suggest deferring lower items):\n" + focus_load_text.strip())
    if profile_base.strip():
        parts.append(
            "MY PROFILE (stable base context - who I am, always relevant; use to ground "
            "everything, don't restate verbatim):\n" + profile_base.strip()
        )
    if memory_text.strip():
        parts.append(
            "LONG-TERM MEMORY (evolving notes, most important first; recent work matters "
            "most; use where relevant, don't list verbatim):\n" + memory_text.strip()
        )
    if reflection_text.strip():
        parts.append(
            "MY END-OF-DAY REFLECTION FROM YESTERDAY (accomplishments, blockers, mood, "
            "progress). Use this to make the TOP 'motivation' and 'greeting' honest and "
            "specific - do NOT create a separate section for it:\n"
            "- If I was blocked or low on motivation, name it briefly and push me forward "
            "while keeping it REAL (no corny hype).\n"
            "- If my progress was poor/thin, tell me straight - like it is, no coddling - "
            "then point me at the single most important fix today.\n"
            "- If I did well, acknowledge it crisply and build momentum.\n"
            + reflection_text.strip()
        )
    if schedule_text.strip():
        parts.append(
            "TODAY'S PLANNED SCHEDULE (FOR CONTEXT ONLY - the Schedule section is "
            "generated automatically, so do NOT reproduce it; instead surface the "
            "important scheduled items in 'Today's Focus'):\n" + schedule_text.strip()
        )
    elif schedule_note.strip():
        parts.append(
            "SCHEDULE STATUS: " + schedule_note.strip()
            + " If you add a suggested schedule, clearly label it '(auto-suggested)'."
        )
    if calendar_text.strip():
        parts.append("EVENTS FROM MY GOOGLE CALENDAR:\n" + calendar_text.strip())
    if reminders_text.strip():
        parts.append(
            "ACTIVE REMINDERS / DEADLINES (surface ALL of these near the TOP in a "
            "'Reminders' section; mark overdue and due-soon items high priority; keep "
            "the dates):\n" + reminders_text.strip()
        )
    parts.append(f"NEW UPDATES SINCE LAST DIGEST:\n{update_lines or '(none)'}")
    if finding_lines:
        parts.append("NEW DEVELOPMENTS FROM MY TRACKERS:\n" + "\n".join(finding_lines))
    if korean_summary.strip():
        parts.append(
            f"TODAY'S LANGUAGE LESSON (include verbatim as its own section titled "
            f"'{language_title}'; keep every item):\n" + korean_summary.strip()
        )
    if headlines_text.strip():
        ints = ", ".join(interests or []) or "(none specified)"
        parts.append(
            "CANDIDATE HEADLINES from my news sources, each prefixed with an index [N]. "
            "In a 'Headlines' section (near the top, after Today's Focus / Deadlines), "
            "pick the 3-5 MOST relevant to my interests; for each item set 'text' to a "
            "crisp one-line take. CRITICAL: do NOT write a URL - instead set 'url' to the "
            "story's index in the form 'ref:N' (e.g. 'ref:3'). Never invent links. "
            "Lead with the most relevant; skip the rest. MY INTERESTS: " + ints + "\n"
            + headlines_text.strip()
        )
    return post_json(SYSTEM_PROMPT, "\n\n".join(parts), model=model,
                     timeout=timeout, max_tokens=max_tokens)
