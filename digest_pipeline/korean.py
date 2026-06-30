"""Daily Korean lesson generator - structured on a TOPIK II curriculum.

WHAT is taught is decided here (ordered grammar syllabus + ordered vocab deck +
spaced-repetition reviews of past items). The LLM is used to TEACH the selected
items (romanization, natural examples, nuance) and to phrase review prompts. An
offline fallback still produces the correct items (from the embedded curriculum)
without examples.

State (persisted by store.load_korean / store.save_korean):
  progress: {grammar_index, vocab_index}   -> position in each ordered list
  srs:      {key: {type,item,reps,interval,next_due,introduced}}  -> review schedule
  placement:{done, level}
  seen_vocab / seen_grammar / history       -> de-dup + record
"""

from datetime import datetime, timedelta

from . import korean_curriculum as cur
from . import llm

N_NEW_VOCAB = 5
N_NEW_GRAMMAR = 1
MAX_REVIEWS = 6
SRS_INTERVALS = [1, 3, 7, 16, 35, 75, 150]  # days; index by reps


SYSTEM_PROMPT = """\
You are a Korean tutor teaching a specific, pre-selected TOPIK II lesson. You are
given the EXACT new grammar point(s) and vocabulary words to teach today, plus
items to REVIEW. Do not substitute different items. Respond with ONLY a valid JSON
object in this schema:

{
  "vocab": [
    {"korean": "...", "romanization": "...", "english": "...", "pos": "...",
     "example_ko": "...", "example_en": "...", "topik_level": "TOPIK 3"}
  ],
  "grammar": [
    {"point": "...", "english": "...", "example_ko": "...", "example_en": "...",
     "topik_level": "TOPIK 3"}
  ],
  "review": [
    {"type": "vocab|grammar", "item": "...", "prompt": "a short recall cue",
     "answer": "the meaning / usage", "example_ko": "..."}
  ],
  "tip": "one short study tip or nuance note"
}

RULES:
- Teach EXACTLY the provided new vocab and grammar (same Korean items). Add accurate
  romanization (Revised Romanization), natural example sentences, and correct English.
- For REVIEW items, write a brief recall prompt and the answer so the learner can
  self-test, plus a fresh example sentence.
- If asked to supply EXTRA vocab, add that many useful TOPIK II words NOT in the
  do-not-repeat list.
- Keep everything correct and natural; do not invent fake words."""


def _today():
    return datetime.now().strftime("%Y-%m-%d")


def _take_unseen(items, start, n, seen, keyfn):
    """Take up to n items from `items[start:]`, skipping any already in `seen`.

    Returns (chosen, new_index) where new_index points past everything consumed,
    so bonus items the LLM may have introduced earlier are never re-taught.
    """
    chosen, i = [], start
    while i < len(items) and len(chosen) < n:
        if keyfn(items[i]) not in seen:
            chosen.append(items[i])
        i += 1
    return chosen, i


def select_items(state: dict, level: str, today: str | None = None) -> dict:
    """Pick today's new grammar, new vocab, and due reviews from the curriculum."""
    today = today or _today()
    prog = state.get("progress", {"grammar_index": 0, "vocab_index": 0})
    g_idx = prog.get("grammar_index", 0)
    v_idx = prog.get("vocab_index", 0)
    seen_g = set(state.get("seen_grammar", []))
    seen_v = set(state.get("seen_vocab", []))

    new_grammar, new_g_idx = _take_unseen(cur.GRAMMAR_SYLLABUS, g_idx, N_NEW_GRAMMAR,
                                          seen_g, lambda x: x["point"])
    new_vocab, new_v_idx = _take_unseen(cur.VOCAB_SEED, v_idx, N_NEW_VOCAB,
                                        seen_v, lambda x: x["korean"])
    need_extra_vocab = max(0, N_NEW_VOCAB - len(new_vocab))  # deck exhausted -> LLM fills

    # Reviews due today (next_due <= today), oldest first.
    due = []
    for key, rec in state.get("srs", {}).items():
        if rec.get("next_due", "9999") <= today:
            due.append((key, rec))
    due.sort(key=lambda kr: kr[1].get("next_due", ""))
    due = due[:MAX_REVIEWS]

    return {
        "new_grammar": new_grammar,
        "new_vocab": new_vocab,
        "need_extra_vocab": need_extra_vocab,
        "reviews": [r for _, r in due],
        "review_keys": [k for k, _ in due],
        "new_grammar_index": new_g_idx,
        "new_vocab_index": new_v_idx,
    }


def _build_user_message(sel: dict, state: dict, level: str) -> str:
    ng = "\n".join(f"- {g['point']}  ({g['english']}; {g['level']})" for g in sel["new_grammar"]) or "(none)"
    nv = "\n".join(f"- {v['korean']}  ({v['english']}; {v['pos']})" for v in sel["new_vocab"]) or "(none)"
    rv = "\n".join(
        f"- [{r.get('type')}] {r.get('item')}" for r in sel["reviews"]
    ) or "(none)"
    extra = (f"\n\nALSO SUPPLY {sel['need_extra_vocab']} EXTRA TOPIK II vocab words "
             f"(the ordered deck is exhausted)." if sel["need_extra_vocab"] else "")
    dnr_v = ", ".join(state.get("seen_vocab", [])[-300:])
    return (
        f"LEVEL: {level}\n\n"
        f"NEW GRAMMAR TO TEACH:\n{ng}\n\n"
        f"NEW VOCAB TO TEACH:\n{nv}\n\n"
        f"ITEMS TO REVIEW (write recall prompt + answer + example):\n{rv}"
        f"{extra}\n\n"
        f"DO-NOT-REPEAT VOCAB (for any extra words):\n{dnr_v}"
    )


def _offline_lesson(sel: dict) -> dict:
    """Build the lesson directly from curriculum data (no examples)."""
    vocab = [{
        "korean": v["korean"], "romanization": "", "english": v["english"],
        "pos": v["pos"], "example_ko": "", "example_en": "", "topik_level": "TOPIK II",
    } for v in sel["new_vocab"]]
    grammar = [{
        "point": g["point"], "english": g["english"], "example_ko": "",
        "example_en": "", "topik_level": g["level"],
    } for g in sel["new_grammar"]]
    review = [{
        "type": r.get("type"), "item": (r.get("item") or {}).get("korean")
        if isinstance(r.get("item"), dict) else r.get("item"),
        "prompt": "Recall the meaning/usage.",
        "answer": (r.get("item") or {}).get("english", "") if isinstance(r.get("item"), dict) else "",
        "example_ko": "",
    } for r in sel["reviews"]]
    return {"vocab": vocab, "grammar": grammar, "review": review,
            "tip": "Offline mode: items selected from your TOPIK II track (examples added when online)."}


def _advance_state(state: dict, sel: dict, lesson: dict, today: str) -> dict:
    """Advance SRS schedule + curriculum pointers after a lesson is built."""
    srs = state.setdefault("srs", {})
    seen_v = state.setdefault("seen_vocab", [])
    seen_g = state.setdefault("seen_grammar", [])

    def schedule(reps):
        i = min(reps, len(SRS_INTERVALS) - 1)
        days = SRS_INTERVALS[i]
        return days, (datetime.strptime(today, "%Y-%m-%d") + timedelta(days=days)).strftime("%Y-%m-%d")

    # Introduce new vocab (from the lesson, so LLM-supplied extras are included too).
    deck_vocab = {v["korean"] for v in sel["new_vocab"]}
    for v in lesson.get("vocab", []):
        ko = v.get("korean")
        if not ko:
            continue
        key = f"v:{ko}"
        if key not in srs:
            days, due = schedule(0)
            srs[key] = {"type": "vocab", "item": {"korean": ko, "english": v.get("english", "")},
                        "reps": 0, "interval": days, "next_due": due, "introduced": today}
        if ko not in seen_v:
            seen_v.append(ko)

    for g in lesson.get("grammar", []):
        pt = g.get("point")
        if not pt:
            continue
        key = f"g:{pt}"
        if key not in srs:
            days, due = schedule(0)
            srs[key] = {"type": "grammar", "item": {"korean": pt, "english": g.get("english", "")},
                        "reps": 0, "interval": days, "next_due": due, "introduced": today}
        if pt not in seen_g:
            seen_g.append(pt)

    # Advance reviewed items to their next interval.
    for key in sel["review_keys"]:
        rec = srs.get(key)
        if not rec:
            continue
        rec["reps"] = rec.get("reps", 0) + 1
        days, due = schedule(rec["reps"])
        rec["interval"], rec["next_due"] = days, due

    # Advance the ordered-deck pointers past everything consumed (incl. skipped).
    prog = state.setdefault("progress", {"grammar_index": 0, "vocab_index": 0})
    prog["grammar_index"] = max(prog.get("grammar_index", 0), sel["new_grammar_index"])
    prog["vocab_index"] = max(prog.get("vocab_index", 0), sel["new_vocab_index"])

    state.setdefault("history", []).append({"date": today, "lesson": lesson})
    return state


def build_lesson(state: dict, *, level: str = "intermediate", today: str | None = None,
                 model: str | None = None, offline: bool = False):
    """Return (lesson, new_state). Selects per curriculum, teaches via LLM (or offline)."""
    today = today or _today()
    sel = select_items(state, level, today)

    if offline:
        lesson = _offline_lesson(sel)
    else:
        data = llm.post_json(SYSTEM_PROMPT, _build_user_message(sel, state, level),
                             model=model, temperature=0.6, max_tokens=2600, timeout=120)
        lesson = _normalize(data)
        # Safety net: if the model dropped the required new items, fall back for those.
        if not lesson.get("vocab") and not lesson.get("grammar"):
            lesson = _offline_lesson(sel)

    new_state = _advance_state(state, sel, lesson, today)
    return lesson, new_state


def _normalize(data: dict) -> dict:
    vocab, grammar, review = [], [], []
    for v in (data.get("vocab") or []):
        if not isinstance(v, dict) or not v.get("korean"):
            continue
        vocab.append({k: str(v.get(k, "")).strip() for k in
                      ("korean", "romanization", "english", "pos", "example_ko",
                       "example_en", "topik_level")})
    for g in (data.get("grammar") or []):
        if not isinstance(g, dict) or not g.get("point"):
            continue
        grammar.append({k: str(g.get(k, "")).strip() for k in
                        ("point", "english", "example_ko", "example_en", "topik_level")})
    for r in (data.get("review") or []):
        if not isinstance(r, dict):
            continue
        review.append({
            "type": str(r.get("type", "")).strip(),
            "item": str(r.get("item", "")).strip(),
            "prompt": str(r.get("prompt", "")).strip(),
            "answer": str(r.get("answer", "")).strip(),
            "example_ko": str(r.get("example_ko", "")).strip(),
        })
    return {"vocab": vocab, "grammar": grammar, "review": review,
            "tip": str(data.get("tip", "")).strip()}


def render_summary(lesson: dict) -> str:
    """Compact text passed to the digest composer (and used in the text email)."""
    lines = []
    if lesson.get("vocab"):
        lines.append("Vocabulary:")
        for v in lesson["vocab"]:
            rom = f" ({v['romanization']})" if v.get("romanization") else ""
            lines.append(f"  {v['korean']}{rom} - {v['english']}"
                         + (f" [{v['pos']}]" if v.get("pos") else ""))
            if v.get("example_ko"):
                lines.append(f"      {v['example_ko']} = {v['example_en']}")
    if lesson.get("grammar"):
        lines.append("Grammar:")
        for g in lesson["grammar"]:
            lines.append(f"  {g['point']} - {g['english']}")
            if g.get("example_ko"):
                lines.append(f"      {g['example_ko']} = {g['example_en']}")
    if lesson.get("review"):
        lines.append("Review:")
        for r in lesson["review"]:
            lines.append(f"  {r.get('item','')} - {r.get('answer','')}")
    if lesson.get("tip"):
        lines.append(f"Tip: {lesson['tip']}")
    return "\n".join(lines)


def progress_summary(state: dict) -> dict:
    prog = state.get("progress", {})
    srs = state.get("srs", {})
    today = _today()
    due = sum(1 for r in srs.values() if r.get("next_due", "9999") <= today)
    return {
        "grammar_done": prog.get("grammar_index", 0),
        "grammar_total": cur.grammar_total(),
        "vocab_done": prog.get("vocab_index", 0),
        "vocab_total": cur.vocab_total(),
        "tracked_items": len(srs),
        "reviews_due": due,
        "placement_done": state.get("placement", {}).get("done", False),
    }
