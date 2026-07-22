"""English vocabulary practice (a second language-learning track).

Mirrors the shape of korean (build_lesson / render_summary / items /
progress_summary) so the digest can dispatch on the user's chosen language.
Words already seen are remembered so nothing repeats. Works offline via a
built-in word bank; online it asks the LLM for fresh, level-appropriate words.
"""

from . import llm, store

LEVELS = {
    "everyday": "common but useful everyday words a native adult should own",
    "advanced": "advanced, precise vocabulary (SAT/GRE level) for sharp writing",
    "erudite": "erudite, literary words to sound exceptionally well-read",
}

# Offline fallback bank (rotated by day; used when no LLM is available).
_BANK = [
    {"word": "salient", "pos": "adj.", "definition": "most noticeable or important",
     "example": "She summarized the salient points in a single paragraph."},
    {"word": "ostensible", "pos": "adj.", "definition": "stated or appearing to be true, but not necessarily so",
     "example": "The ostensible reason for the trip was work, but he mostly rested."},
    {"word": "pragmatic", "pos": "adj.", "definition": "dealing with things sensibly and realistically",
     "example": "Take a pragmatic approach: ship the simple fix first."},
    {"word": "nuance", "pos": "n.", "definition": "a subtle difference in meaning or tone",
     "example": "The translation lost the nuance of the original phrase."},
    {"word": "cogent", "pos": "adj.", "definition": "clear, logical, and convincing",
     "example": "She made a cogent argument for rewriting the module."},
    {"word": "tenable", "pos": "adj.", "definition": "able to be defended or maintained",
     "example": "That assumption is no longer tenable given the new data."},
    {"word": "laconic", "pos": "adj.", "definition": "using very few words",
     "example": "His laconic reply—'fine'—told them nothing."},
    {"word": "ameliorate", "pos": "v.", "definition": "to make something better",
     "example": "Caching helped ameliorate the latency spikes."},
    {"word": "esoteric", "pos": "adj.", "definition": "understood by only a small, specialized group",
     "example": "The talk was too esoteric for a general audience."},
    {"word": "juxtapose", "pos": "v.", "definition": "to place close together for contrast",
     "example": "The report juxtaposes last year's plan with this year's results."},
    {"word": "perfunctory", "pos": "adj.", "definition": "done with minimal effort or reflection",
     "example": "He gave the draft only a perfunctory glance."},
    {"word": "sanguine", "pos": "adj.", "definition": "optimistic, especially in a difficult situation",
     "example": "Despite the setback she stayed sanguine about the deadline."},
]

_SYSTEM = """\
You are an English vocabulary coach. Produce a short daily lesson of fresh,
level-appropriate words the learner does NOT already know. Respond with ONLY a
JSON object:

{
  "theme": "optional 2-4 word theme or ''",
  "words": [
    {"word": "...", "pos": "n.|v.|adj.|adv.", "definition": "concise definition",
     "example": "a natural example sentence using the word",
     "synonyms": "2-3 comma-separated synonyms or ''"}
  ]
}

RULES:
- 5 words. Match the requested level. Avoid any word in the AVOID list.
- Definitions concise; examples natural and genuinely helpful.
- Return ONLY the JSON object."""


def build_lesson(state: dict, *, level: str = "advanced", today: str,
                 model: str | None = None, offline: bool = False):
    """Return (lesson, new_state). Records the lesson + seen words in state."""
    state = state or {}
    state.setdefault("history", [])
    state.setdefault("seen_words", [])
    seen = {w.lower() for w in state.get("seen_words", [])}

    lesson = None
    if not offline and llm.have_key() or (not offline and llm.openai_configured()):
        try:
            avoid = ", ".join(list(seen)[-120:]) or "(none yet)"
            data = llm.post_json(
                _SYSTEM,
                f"LEVEL: {level} - {LEVELS.get(level, LEVELS['advanced'])}.\n"
                f"AVOID (already learned): {avoid}",
                model=model, temperature=0.5, max_tokens=1200)
            words = [w for w in (data.get("words") or []) if isinstance(w, dict) and w.get("word")]
            if words:
                lesson = {"date": today, "level": level,
                          "theme": str(data.get("theme") or "").strip(), "words": words[:5]}
        except llm.DigestLLMError:
            lesson = None

    if lesson is None:  # offline / fallback: rotate the built-in bank
        start = sum(ord(c) for c in today) % len(_BANK)
        picks, i = [], 0
        while len(picks) < 5 and i < len(_BANK):
            w = _BANK[(start + i) % len(_BANK)]
            if w["word"].lower() not in seen or len(picks) < 5:
                picks.append(w)
            i += 1
        lesson = {"date": today, "level": level, "theme": "", "words": picks[:5]}

    for w in lesson["words"]:
        wl = w["word"].lower()
        if wl not in seen:
            state["seen_words"].append(w["word"])
            seen.add(wl)
    state["history"].append({"date": today, "lesson": lesson})
    return lesson, state


def render_summary(lesson: dict) -> str:
    """Plain-text lesson for the digest composer."""
    if not lesson:
        return ""
    lines = []
    if lesson.get("theme"):
        lines.append(f"Theme: {lesson['theme']}")
    for w in lesson.get("words", []):
        pos = f" [{w['pos']}]" if w.get("pos") else ""
        lines.append(f"{w.get('word','')}{pos} - {w.get('definition','')}")
        if w.get("example"):
            lines.append(f"  e.g. {w['example']}")
    return "\n".join(lines)


def items(lesson: dict) -> list:
    """Flat items for the digest 'English Vocabulary' section."""
    out = []
    for w in (lesson or {}).get("words", []):
        pos = f" [{w['pos']}]" if w.get("pos") else ""
        out.append({"text": f"{w.get('word','')}{pos} \u2014 {w.get('definition','')}",
                    "priority": "low", "url": ""})
        if w.get("example"):
            out.append({"text": "\u21B3 " + w["example"], "priority": "low", "url": ""})
        if w.get("synonyms"):
            out.append({"text": "\u21B3 syn: " + w["synonyms"], "priority": "low", "url": ""})
    return out


def progress_summary(state: dict) -> str:
    n = len((state or {}).get("seen_words", []))
    return f"{n} words learned" if n else "no words yet"