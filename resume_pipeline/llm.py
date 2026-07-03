"""LLM-driven resume optimization via the Anthropic Messages API.

Claude is the optimization brain: given the candidate profile and a target job
description, it returns an optimized profile in the *same JSON schema*, which is
then rendered deterministically by ``template.py`` (so the LaTeX, escaping, and
one-page guarantees still hold).

Targets the public Anthropic API by default, or any Anthropic-compatible gateway
(e.g. an internal corporate LLM Gateway) via ANTHROPIC_BASE_URL / --base-url and
ANTHROPIC_AUTH_STYLE / --auth-style (x-api-key or bearer).

Uses only the Python standard library (``urllib``) -- no pip dependency.
"""

import json
import os
import urllib.error
import urllib.request
from pathlib import Path

DEFAULT_BASE_URL = "https://api.anthropic.com"
BASE_URL_ENV = "ANTHROPIC_BASE_URL"   # set this to an internal gateway, e.g. AMD's
ANTHROPIC_VERSION = "2023-06-01"
DEFAULT_MODEL = "claude-opus-4-8"
API_KEY_ENV = "ANTHROPIC_API_KEY"
AUTH_STYLE_ENV = "ANTHROPIC_AUTH_STYLE"   # "x-api-key" (default) or "bearer"
import app_paths  # noqa: E402
DEFAULT_MANIFESTO = app_paths.bundle_dir() / "RESUME_MANIFESTO.md"

REQUIRED_PROFILE_KEYS = ("contact", "education", "skills", "experience")


class LLMError(RuntimeError):
    pass


SYSTEM_PROMPT = """\
You are an expert technical recruiter, ATS (applicant tracking system) analyst, \
and senior resume writer. You are given a candidate's structured profile as JSON \
and a target job description. Produce an optimized version of the profile that \
maximizes the candidate's chance of being selected for an interview by, in order: \
(1) automated ATS keyword filters, (2) human recruiters doing a 10-second scan, \
and (3) technical hiring managers judging depth and impact.

OUTPUT FORMAT (strict):
- Respond with ONLY a single valid JSON object. No markdown, no code fences, no \
commentary before or after.
- Preserve the EXACT schema and field names of the input profile:
  contact: {name, email, phone, linkedin, github}
  education: [{institution, location, degree, gpa, dates}]
  skills: {"<Category>": ["skill", ...], ...}
  experience: [{company, location, role, dates, bullets: ["...", ...]}]
  projects: [{title, tech: ["..."], dates, bullets: ["...", ...]}]
- You MAY add three extra top-level keys and no others:
  "keywords": ["..."]  - the most important job-description keywords you targeted.
  "gaps": [ {"requirement": "...", "importance": 0-100, "reason": "...", \
"suggestion": "..."} ]  - see GAP ANALYSIS below.
  "summary": "..."  - see CANDIDATE SUMMARY below.

TRUTHFULNESS (critical -- fabrication can get a candidate auto-rejected or fired):
- Do NOT invent or alter employers, job titles, employment dates, schools, \
degrees, GPAs, or certifications.
- Do NOT fabricate quantitative metrics. Keep every real number from the source; \
never add invented numbers or percentages.
- You MAY rephrase bullets, surface skills that are genuinely implied by the work \
already described, reorder content, and shift emphasis. Keep all factual anchors \
intact.

OPTIMIZATION:
- ATS: naturally weave in the job description's exact keywords and phrases wherever \
they truthfully apply (in skills and bullets). Prefer standard terminology; spell \
out acronyms once where it helps matching (e.g., "CI/CD (continuous integration)").
- Recruiter/hiring-manager: lead with the most relevant, highest-impact content. \
Start bullets with strong action verbs. Keep each bullet concise (about one to two \
lines). Order skills and bullets so the most job-relevant appear first. Reorder \
skill categories so the most relevant category comes first.
- ONE PAGE: be ruthless about concision. Aim for about 4-5 bullets on the most \
recent role, 2-3 on older roles, and about 2 per project. Drop the least relevant \
bullets entirely rather than keeping filler. Trim low-value skills.
- Leave the contact block unchanged.

GAP ANALYSIS (the "gaps" key):
- After optimizing truthfully, list every meaningful requirement, skill, \
qualification, or keyword in the JOB DESCRIPTION that you could NOT honestly \
represent in the resume because it is absent from the candidate's materials (or \
only weakly supported).
- Rank the list by importance to THIS job, most important first.
- "importance" is an integer 0-100 (a percentage) reflecting how decisive that \
item is for selection (must-have/required ~80-100; strongly preferred ~50-79; \
nice-to-have ~1-49).
- "requirement": the missing item, in the JD's own terms.
- "reason": one concise sentence on why it matters and why it is currently missing/weak.
- "suggestion": one concise sentence on what the candidate could add (a project, \
metric, skill, or experience) to close it -- phrased as a prompt for the user.
- Do NOT add the gap content into the resume itself. Only report it in "gaps".
- If the resume already covers the JD well, return "gaps": [].

CANDIDATE SUMMARY (the "summary" key):
- Write 2-4 short, plain-text sentences for the candidate (no markdown).
- Confirm what you prioritized for this JD, what you kept vs. changed, and how any \
new notes were applied.
- If notes are ambiguous or you could not apply them truthfully, say so and ask a \
brief clarifying question.
- On regeneration passes, explicitly note what you preserved from the prior draft.

ITERATION (when the input profile is a PRIOR OPTIMIZED DRAFT and/or NEW NOTES are present):
- Treat the input profile JSON as the current working draft the candidate already saw.
- Preserve prior edits unless new notes explicitly override them or the JD demands a \
truthful correction.
- Integrate new notes without reverting unrelated bullets, ordering, or emphasis.
- Do not "start over" from a blank-slate rewrite if a working draft is provided.

Return the optimized profile JSON (with "keywords", "gaps", and "summary") now."""


def load_manifesto(path: Path = DEFAULT_MANIFESTO) -> str:
    """Load the resume manifesto that guides optimization (empty string if absent)."""
    path = Path(path)
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8")


def _system_prompt(manifesto: str) -> str:
    if not manifesto.strip():
        return SYSTEM_PROMPT
    return (
        SYSTEM_PROMPT
        + "\n\nApply the following RESUME MANIFESTO as authoritative guidance for "
        "every content decision (wording, ordering, selection, keyword usage). "
        "Where it adds detail to the rules above, follow it; never let it override "
        "the truthfulness rules or the output-format/schema rules.\n\n"
        "===== RESUME MANIFESTO =====\n" + manifesto.strip() + "\n===== END MANIFESTO ====="
    )


def _build_user_message(
    profile: dict,
    job_description: str,
    *,
    is_iteration: bool = False,
    new_notes: str = "",
) -> str:
    parts = [
        "JOB DESCRIPTION:\n" + job_description.strip(),
    ]
    if is_iteration:
        parts.append(
            "PRIOR OPTIMIZED DRAFT (current working version - build on this; "
            "preserve edits unless new notes override):\n"
            + json.dumps(profile, ensure_ascii=False, indent=2)
        )
    else:
        parts.append(
            "CANDIDATE PROFILE JSON:\n"
            + json.dumps(profile, ensure_ascii=False, indent=2)
        )
    if new_notes and new_notes.strip():
        parts.append(
            "NEW NOTES FROM CANDIDATE (apply truthfully; keep other prior edits):\n"
            + new_notes.strip()
        )
    return "\n\n".join(parts)


def _extract_text(payload: dict) -> str:
    blocks = payload.get("content") or []
    parts = [b.get("text", "") for b in blocks if isinstance(b, dict) and b.get("type") == "text"]
    text = "".join(parts).strip()
    if not text:
        raise LLMError("Anthropic API returned no text content.")
    return text


def _parse_json(text: str) -> dict:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        # Strip a ```json ... ``` fence if the model added one anyway.
        cleaned = cleaned.split("\n", 1)[-1]
        if cleaned.rstrip().endswith("```"):
            cleaned = cleaned.rstrip()[:-3]
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        # Fall back to the outermost {...} span.
        start, end = cleaned.find("{"), cleaned.rfind("}")
        if start != -1 and end > start:
            try:
                return json.loads(cleaned[start : end + 1])
            except json.JSONDecodeError as exc:
                raise LLMError(f"Could not parse JSON from model output: {exc}") from exc
        raise LLMError("Model output did not contain a JSON object.")


def _validate(profile: dict) -> None:
    if not isinstance(profile, dict):
        raise LLMError("Optimized profile is not a JSON object.")
    missing = [k for k in REQUIRED_PROFILE_KEYS if k not in profile]
    if missing:
        raise LLMError(f"Optimized profile is missing required keys: {', '.join(missing)}")


EXTRACT_SYSTEM_PROMPT = """\
You are a precise resume parser. Convert the candidate material below (which may
be raw resume text extracted from a PDF, plain text, and/or free-form notes) into
a single JSON object with EXACTLY this schema and field names:

  contact: {name, email, phone, linkedin, github}
  education: [{institution, location, degree, gpa, dates}]
  skills: {"<Category>": ["skill", ...], ...}
  experience: [{company, location, role, dates, bullets: ["...", ...]}]
  projects: [{title, tech: ["..."], dates, bullets: ["...", ...]}]

Rules:
- Respond with ONLY the JSON object. No markdown, no code fences, no commentary.
- Extract faithfully. Do NOT invent or embellish. If a field is genuinely absent,
  use an empty string or empty list; omit nothing structural.
- Preserve the candidate's real bullet wording (light cleanup of OCR/PDF artifacts
  like broken hyphenation and stray whitespace is fine).
- Group skills into sensible categories (e.g. Languages, Frameworks, Cloud & DevOps,
  Data, Tools). Keep contact details exactly as written.
- Include projects only if present in the material; otherwise use an empty list."""


def _build_headers(key: str, style: str) -> dict:
    headers = {"anthropic-version": ANTHROPIC_VERSION, "content-type": "application/json"}
    if style == "bearer":
        headers["Authorization"] = f"Bearer {key}"
    elif style in ("apim", "subscription", "ocp"):
        # Azure API Management gateway (e.g. AMD's llm-api.amd.com).
        headers["Ocp-Apim-Subscription-Key"] = key
    else:
        headers["x-api-key"] = key
    return headers


def _post_messages(system: str, user: str, *, key: str, model: str, max_tokens: int,
                   timeout: int, base_url: str | None, auth_style: str | None) -> dict:
    """Send one Messages API request and return the parsed JSON object reply."""
    base = (base_url or os.environ.get(BASE_URL_ENV) or DEFAULT_BASE_URL).rstrip("/")
    endpoint = base + "/v1/messages"
    style = (auth_style or os.environ.get(AUTH_STYLE_ENV) or "x-api-key").lower()
    body = {
        "model": model,
        "max_tokens": max_tokens,
        "temperature": 0,
        "system": system,
        "messages": [{"role": "user", "content": user}],
    }
    req = urllib.request.Request(
        endpoint, data=json.dumps(body).encode("utf-8"), method="POST",
        headers=_build_headers(key, style),
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise LLMError(f"Anthropic API HTTP {exc.code}: {detail}") from exc
    except urllib.error.URLError as exc:
        raise LLMError(f"Network error calling Anthropic API: {exc.reason}") from exc
    return _parse_json(_extract_text(payload))


def _is_openai(model: str | None) -> bool:
    m = (model or "").lower()
    return m.startswith(("gpt", "o1", "o3", "o4", "chatgpt"))


def _complete(system: str, user: str, *, key, model, max_tokens, timeout,
              base_url, auth_style) -> dict:
    """Route to OpenAI for gpt* models, else the Anthropic/AMD gateway."""
    if _is_openai(model):
        import openai_compat
        try:
            return openai_compat.post_json(system, user, model=model,
                                           max_tokens=max_tokens, timeout=timeout)
        except openai_compat.OpenAIError as exc:
            raise LLMError(str(exc)) from exc
    return _post_messages(system, user, key=key, model=model, max_tokens=max_tokens,
                          timeout=timeout, base_url=base_url, auth_style=auth_style)


def _require_key(api_key: str | None) -> str:
    key = api_key or os.environ.get(API_KEY_ENV)
    if not key:
        raise LLMError(
            f"{API_KEY_ENV} is not set. Export your API key, e.g.\n"
            f"  export {API_KEY_ENV}=...\n"
            "or pass --api-key. (LLM optimization is required.)"
        )
    return key


def extract_profile(
    source_text: str,
    *,
    api_key: str | None = None,
    model: str = DEFAULT_MODEL,
    max_tokens: int = 8192,
    timeout: int = 180,
    base_url: str | None = None,
    auth_style: str | None = None,
) -> dict:
    """Parse raw resume text / notes into the structured profile JSON schema."""
    key = api_key if _is_openai(model) else _require_key(api_key)
    if not source_text or not source_text.strip():
        raise LLMError("No resume text/notes provided to parse into a profile.")
    user = "CANDIDATE MATERIAL:\n" + source_text.strip()
    profile = _complete(
        EXTRACT_SYSTEM_PROMPT, user, key=key, model=model, max_tokens=max_tokens,
        timeout=timeout, base_url=base_url, auth_style=auth_style,
    )
    _validate(profile)
    profile.pop("keywords", None)
    return profile


def optimize_profile(
    profile: dict,
    job_description: str,
    *,
    api_key: str | None = None,
    model: str = DEFAULT_MODEL,
    max_tokens: int = 8192,
    timeout: int = 180,
    manifesto_path: Path = DEFAULT_MANIFESTO,
    base_url: str | None = None,
    auth_style: str | None = None,
    extra_context: str = "",
    is_iteration: bool = False,
    new_notes: str = "",
) -> tuple:
    """Return an LLM-optimized profile (same schema) for the given job description.

    Works against the public Anthropic API or any Anthropic-compatible gateway
    (e.g. an internal LLM Gateway) by setting ``base_url`` / ``ANTHROPIC_BASE_URL``.
    ``auth_style`` selects the auth header: "x-api-key" (Anthropic default),
    "bearer" (Authorization: Bearer <key>), or "apim" (Ocp-Apim-Subscription-Key).
    ``extra_context`` is the candidate's full original resume text and any notes;
    it is given to the model as additional grounding (truthful source only).
    """
    key = api_key if _is_openai(model) else _require_key(api_key)
    if not job_description or not job_description.strip():
        raise LLMError("A job description is required for LLM optimization.")

    user = _build_user_message(
        profile, job_description, is_iteration=is_iteration, new_notes=new_notes,
    )
    if extra_context and extra_context.strip():
        user += (
            "\n\nADDITIONAL CANDIDATE CONTEXT (full original resume text and/or "
            "prior notes - use as truthful source material; do not contradict the "
            "structured profile's factual anchors):\n" + extra_context.strip()
        )

    optimized = _complete(
        _system_prompt(load_manifesto(manifesto_path)), user, key=key, model=model,
        max_tokens=max_tokens, timeout=timeout, base_url=base_url, auth_style=auth_style,
    )
    _validate(optimized)
    # metadata keys; keep them off the rendered profile.
    optimized.pop("keywords", None)
    gaps = _normalize_gaps(optimized.pop("gaps", []))
    summary = str(optimized.pop("summary") or "").strip()
    return optimized, gaps, summary


def _normalize_gaps(raw) -> list:
    """Coerce model gaps into [{requirement, importance:int 0-100, reason, suggestion}], sorted desc."""
    if not isinstance(raw, list):
        return []
    out = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        req = str(item.get("requirement") or item.get("item") or "").strip()
        if not req:
            continue
        try:
            imp = int(round(float(item.get("importance", 0))))
        except (TypeError, ValueError):
            imp = 0
        imp = max(0, min(100, imp))
        out.append({
            "requirement": req,
            "importance": imp,
            "reason": str(item.get("reason") or "").strip(),
            "suggestion": str(item.get("suggestion") or "").strip(),
        })
    out.sort(key=lambda g: -g["importance"])
    return out
