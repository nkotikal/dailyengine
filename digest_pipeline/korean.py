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

import random
from datetime import datetime, timedelta

from . import korean_curriculum as cur
from . import llm

N_NEW_VOCAB = 3          # vocab words served per day (from the weekly theme)
N_NEW_GRAMMAR = 1
MAX_REVIEWS = 4
SRS_INTERVALS = [1, 3, 7, 16, 35, 75, 150]  # days; index by reps

# --- weekly themed vocab ---------------------------------------------------
WEEKLY_WORDS = 15        # unique words in a week's theme (7 days x 3 = 21 slots -> ~6 repeats)
POOL_CANDIDATES = 40     # unlearned words offered to the theme picker
REVIEW_WEEK_PROB = 0.4   # chance a week sprinkles in a couple of past-theme words
REVIEW_WORDS_WHEN_ON = 2 # how many past words to sprinkle when it does


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
    {"point": "...", "english": "a clear 1-2 sentence explanation of meaning AND when/how to use it",
     "form": "how it attaches (e.g. verb stem + -(으)면)", "example_ko": "...",
     "example_en": "...", "topik_level": "TOPIK 3"}
  ],
  "review": [
    {"type": "vocab|grammar", "item": "...", "prompt": "a short recall cue",
     "answer": "the meaning / usage", "example_ko": "...", "example_en": "..."}
  ],
  "tip": "one short study tip or nuance note",
  "culture": "OPTIONAL - only when asked: 2-3 sentences on Korean culture/history/a current note"
}

RULES:
- Teach EXACTLY the provided new vocab and grammar (same Korean items). These are REAL
  TOPIK grammar points - explain each accurately; never invent fake grammar or words.
- EVERY example sentence (vocab, grammar, AND review) MUST include both the Korean
  (example_ko) and a correct natural English translation (example_en).
- Grammar "english" should genuinely teach: what it means and when to use it (1-2
  sentences), and "form" shows how it attaches. Be clear and beginner-friendly but precise.
- Add accurate Revised-Romanization and natural, correct example sentences.
- If asked to supply EXTRA vocab, add that many useful TOPIK II words NOT in the
  do-not-repeat list.
- If asked for a CULTURE note, fill "culture" with a short, genuinely interesting
  Korean culture/history/current-events tidbit (otherwise omit it)."""


def _today():
    return datetime.now().strftime("%Y-%m-%d")


# ===========================================================================
# Weekly themed vocabulary
#
# Each week (starting Sunday) has a THEME and 15 words drawn from the curriculum
# list (plus, occasionally, a few review words from past weeks). Words are served
# 3/day across 7 days (21 slots), so ~6 are repeated for reinforcement. Repeats are
# mostly random but biased toward words the learner has been shown yet not COMPLETED
# (completion = replying with your own example sentence for the word). All 15
# completed = the week is done.
# ===========================================================================

THEME_SYSTEM = """\
You are a Korean tutor assembling a THEMED weekly vocabulary set for a TOPIK II
learner. You are given a CANDIDATE POOL of Korean words (with meanings) and,
optionally, some MUST-INCLUDE review words. Choose ONE coherent theme and select
EXACTLY the requested number of words that best fit it, chosen ONLY from the pool
(plus all MUST-INCLUDE words). Respond with ONLY a JSON object:

{ "theme": "a short theme name",
  "words": [ {"korean": "...", "english": "...", "pos": "..."} ] }

RULES:
- Use ONLY words from the provided pool (plus every MUST-INCLUDE word). Do not invent.
- Return EXACTLY the requested count. Keep the English meanings accurate.
- Prefer a theme that groups as many pool words as naturally as possible."""


def _week_start(today_str: str) -> str:
    """The Sunday on/before the given date (weeks start Sunday)."""
    d = datetime.strptime(today_str, "%Y-%m-%d").date()
    offset = (d.weekday() + 1) % 7   # Mon=0..Sun=6 -> Sunday=0
    return (d - timedelta(days=offset)).strftime("%Y-%m-%d")


def _pick_review_words(state: dict, week_start: str, unlearned_count: int) -> list:
    """Occasionally choose a few words from PAST themes for cross-week reinforcement.

    Deterministic per week (seeded by week_start). Prefers words that were never
    completed. Also used to backfill if the unlearned pool is short of 15.
    """
    history = state.get("weekly_history", [])
    if not history:
        return []
    rng = random.Random("rev-" + week_start)
    # Flatten past words, preferring never-completed ones; dedup by korean.
    missed, done = [], []
    seen = set()
    for wk in history:
        status = wk.get("status", {})
        for w in wk.get("words", []):
            ko = w.get("korean")
            if not ko or ko in seen:
                continue
            seen.add(ko)
            (missed if not status.get(ko, {}).get("completed") else done).append(w)
    rng.shuffle(missed)
    rng.shuffle(done)
    ordered = missed + done

    want = 0
    if rng.random() < REVIEW_WEEK_PROB:
        want = REVIEW_WORDS_WHEN_ON
    # Backfill if we don't have enough brand-new words to fill the week.
    want = max(want, WEEKLY_WORDS - unlearned_count)
    return ordered[:max(0, min(want, len(ordered)))]


def pick_weekly_theme(state: dict, week_start: str, *, model=None, offline=False) -> dict:
    """Choose this week's theme + 15 words (mostly new, occasionally review words)."""
    seen_v = set(state.get("seen_vocab", []))
    unlearned = [w for w in cur.VOCAB_SEED if w["korean"] not in seen_v]
    review_words = _pick_review_words(state, week_start, len(unlearned))
    review_kos = {w["korean"] for w in review_words}
    n_new = max(0, WEEKLY_WORDS - len(review_words))
    pool = [w for w in unlearned if w["korean"] not in review_kos]

    def _offline():
        words = review_words + pool[:n_new]
        # If still short (curriculum nearly exhausted), reuse from full deck.
        if len(words) < WEEKLY_WORDS:
            extra = [w for w in cur.VOCAB_SEED
                     if w["korean"] not in {x["korean"] for x in words}]
            words += extra[:WEEKLY_WORDS - len(words)]
        return {"theme": "Weekly vocabulary set", "words": words[:WEEKLY_WORDS]}

    if offline or not llm.have_key() or not pool:
        return _offline()

    candidates = pool[:POOL_CANDIDATES]
    pool_txt = "\n".join(f"- {w['korean']} ({w['english']}; {w['pos']})" for w in candidates)
    must_txt = ("\n".join(f"- {w['korean']} ({w['english']})" for w in review_words)
                or "(none)")
    user = (f"Select EXACTLY {WEEKLY_WORDS} words.\n\n"
            f"MUST-INCLUDE review words ({len(review_words)}):\n{must_txt}\n\n"
            f"CANDIDATE POOL:\n{pool_txt}")
    try:
        data = llm.post_json(THEME_SYSTEM, user, model=model, temperature=0.5, max_tokens=1200)
    except llm.DigestLLMError:
        return _offline()

    valid = {w["korean"]: w for w in cur.VOCAB_SEED}
    for w in review_words:
        valid.setdefault(w["korean"], w)
    words, chosen = [], set()
    for w in (data.get("words") or []):
        ko = str((w or {}).get("korean", "")).strip()
        if ko in valid and ko not in chosen:
            words.append(valid[ko]); chosen.add(ko)
    # Ensure review words are present and top up to 15 from the pool if needed.
    for w in review_words:
        if w["korean"] not in chosen:
            words.append(w); chosen.add(w["korean"])
    for w in pool:
        if len(words) >= WEEKLY_WORDS:
            break
        if w["korean"] not in chosen:
            words.append(w); chosen.add(w["korean"])
    if len(words) < WEEKLY_WORDS:
        return _offline()
    theme = str(data.get("theme") or "Weekly vocabulary set").strip() or "Weekly vocabulary set"
    return {"theme": theme, "words": words[:WEEKLY_WORDS]}


def ensure_week(state: dict, today: str, *, model=None, offline=False) -> bool:
    """Roll over to a new weekly theme if we've crossed into a new week. Returns True if rolled."""
    ws = _week_start(today)
    weekly = state.get("weekly") or {}
    if weekly.get("week_start") == ws and weekly.get("words"):
        return False
    # Archive the finished week for cross-week reinforcement + history.
    if weekly.get("words"):
        state.setdefault("weekly_history", []).append(weekly)
        state["weekly_history"] = state["weekly_history"][-52:]  # ~1 year
    chosen = pick_weekly_theme(state, ws, model=model, offline=offline)
    status = {w["korean"]: {"shown_count": 0, "shown_days": [], "completed": False,
                            "completed_date": ""} for w in chosen["words"]}
    # Mark the newly-introduced words as seen so future weeks don't repeat them
    # (except intentional review sprinkles).
    seen_v = state.setdefault("seen_vocab", [])
    for w in chosen["words"]:
        if w["korean"] not in seen_v:
            seen_v.append(w["korean"])
    state["weekly"] = {
        "week_start": ws, "theme": chosen["theme"], "words": chosen["words"],
        "status": status, "day_slots": {},
    }
    return True


def select_day_words(state: dict, today: str) -> list:
    """Pick today's 3 theme words: coverage-first, with missed-weighted repeats sprinkled.

    Idempotent per day (records/returns the same slots if already chosen today).
    """
    weekly = state.get("weekly") or {}
    words = weekly.get("words") or []
    if not words:
        return []
    slots = weekly.setdefault("day_slots", {})
    if today in slots:
        by_ko = {w["korean"]: w for w in words}
        return [by_ko[k] for k in slots[today] if k in by_ko]

    status = weekly.setdefault("status", {})
    for w in words:
        status.setdefault(w["korean"], {"shown_count": 0, "shown_days": [],
                                        "completed": False, "completed_date": ""})
    rng = random.Random(today)
    n = min(N_NEW_VOCAB, len(words))

    unshown = [w for w in words if status[w["korean"]]["shown_count"] == 0]
    # "Missed" = shown on a previous day but still not completed -> bias to repeat.
    missed = [w for w in words
              if status[w["korean"]]["shown_count"] > 0 and not status[w["korean"]]["completed"]]
    completed = [w for w in words if status[w["korean"]]["completed"]]
    rng.shuffle(unshown); rng.shuffle(completed)
    # Order missed by how many times shown-but-missed (more missed -> earlier), then random.
    missed.sort(key=lambda w: (-status[w["korean"]]["shown_count"], rng.random()))

    chosen, used = [], set()

    def take(pool):
        for w in pool:
            if len(chosen) >= n:
                return
            if w["korean"] not in used:
                chosen.append(w); used.add(w["korean"])

    # Sprinkle at most one missed-word repeat while new words remain (so reinforcement
    # is interleaved, not dumped at week's end), then prioritize coverage.
    if unshown and missed and rng.random() < 0.6:
        take(missed[:1])
    take(unshown)                 # coverage: show every word at least once
    take(missed)                  # then repeat missed/incomplete words
    take(completed)               # last resort: repeat completed words
    take(words)                   # absolute fallback

    slots[today] = [w["korean"] for w in chosen]
    for w in chosen:
        st = status[w["korean"]]
        st["shown_count"] += 1
        st["shown_days"].append(today)
    return chosen


def mark_theme_completion(state: dict, korean_words, date: str) -> int:
    """Mark the given theme words completed (learner wrote their own sentence). Returns count newly completed."""
    weekly = state.get("weekly") or {}
    status = weekly.get("status") or {}
    words_by_ko = {w["korean"]: w for w in weekly.get("words", [])}
    n = 0
    for ko in korean_words or []:
        ko = (ko or "").strip()
        st = status.get(ko)
        if st and not st.get("completed"):
            st["completed"] = True
            st["completed_date"] = date
            n += 1
    return n


def weekly_progress(state: dict) -> dict:
    weekly = state.get("weekly") or {}
    words = weekly.get("words") or []
    status = weekly.get("status") or {}
    completed = [w for w in words if status.get(w["korean"], {}).get("completed")]
    remaining = [w for w in words if not status.get(w["korean"], {}).get("completed")]
    return {
        "theme": weekly.get("theme", ""),
        "week_start": weekly.get("week_start", ""),
        "total": len(words),
        "completed": len(completed),
        "remaining": [{"korean": w["korean"], "english": w["english"]} for w in remaining],
        "done": bool(words) and len(completed) == len(words),
    }


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


def _build_user_message(sel: dict, state: dict, level: str, want_culture: bool = False) -> str:
    ng = "\n".join(f"- {g['point']}  ({g['english']}; {g['level']})" for g in sel["new_grammar"]) or "(none)"
    nv = "\n".join(f"- {v['korean']}  ({v['english']}; {v['pos']})" for v in sel["new_vocab"]) or "(none)"
    rv = "\n".join(
        f"- [{r.get('type')}] {r.get('item')}" for r in sel["reviews"]
    ) or "(none)"
    extra = (f"\n\nALSO SUPPLY {sel['need_extra_vocab']} EXTRA TOPIK II vocab words "
             f"(the ordered deck is exhausted)." if sel["need_extra_vocab"] else "")
    culture = ("\n\nIt's SUNDAY: also fill the \"culture\" field with a short, genuinely "
               "interesting Korean culture/history/current-events tidbit." if want_culture else "")
    dnr_v = ", ".join(state.get("seen_vocab", [])[-300:])
    return (
        f"LEVEL: {level}\n\n"
        f"NEW GRAMMAR TO TEACH (real TOPIK points - explain clearly with form + translation):\n{ng}\n\n"
        f"NEW VOCAB TO TEACH:\n{nv}\n\n"
        f"ITEMS TO REVIEW (recall prompt + answer + example with translation):\n{rv}"
        f"{extra}{culture}\n\n"
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

    # Vocab is theme-driven now: record it as seen (so future weeks don't re-pick it)
    # but do NOT put it on the day-interval SRS -- weekly repeats + cross-week review
    # handle vocab reinforcement instead.
    for v in lesson.get("vocab", []):
        ko = v.get("korean")
        if ko and ko not in seen_v:
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

    # Advance the grammar deck pointer (vocab is theme-driven, not deck-indexed).
    prog = state.setdefault("progress", {"grammar_index": 0, "vocab_index": 0})
    prog["grammar_index"] = max(prog.get("grammar_index", 0), sel["new_grammar_index"])

    state.setdefault("history", []).append({"date": today, "lesson": lesson})
    return state


def build_lesson(state: dict, *, level: str = "intermediate", today: str | None = None,
                 model: str | None = None, offline: bool = False):
    """Return (lesson, new_state). Vocab comes from the weekly theme (3/day); grammar
    and reviews come from the curriculum/SRS. Teaches via LLM (or offline)."""
    today = today or _today()
    ensure_week(state, today, model=model, offline=offline)
    day_words = select_day_words(state, today)

    sel = select_items(state, level, today)   # grammar + SRS reviews
    sel["new_vocab"] = day_words              # vocab is theme-driven
    sel["need_extra_vocab"] = 0

    want_culture = datetime.strptime(today, "%Y-%m-%d").weekday() == 6  # Sunday
    if offline:
        lesson = _offline_lesson(sel)
    else:
        data = llm.post_json(SYSTEM_PROMPT, _build_user_message(sel, state, level, want_culture),
                             model=model, temperature=0.6, max_tokens=2800, timeout=120)
        lesson = _normalize(data)
        if not lesson.get("vocab") and not lesson.get("grammar"):
            lesson = _offline_lesson(sel)

    new_state = _advance_state(state, sel, lesson, today)

    # Attach the weekly theme, completion challenge, and progress to the lesson.
    prog = weekly_progress(new_state)
    lesson["theme"] = prog["theme"]
    lesson["weekly_progress"] = prog
    todays = [v.get("korean", "") for v in lesson.get("vocab", []) if v.get("korean")]
    if todays:
        lesson["challenge"] = (
            "Reply to this email with your OWN example sentence for each of today's "
            "words to complete them: " + ", ".join(todays) + ". "
            f"Weekly theme \u201c{prog['theme']}\u201d - {prog['completed']}/{prog['total']} words done."
        )
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
                        ("point", "english", "form", "example_ko", "example_en", "topik_level")})
    for r in (data.get("review") or []):
        if not isinstance(r, dict):
            continue
        review.append({
            "type": str(r.get("type", "")).strip(),
            "item": str(r.get("item", "")).strip(),
            "prompt": str(r.get("prompt", "")).strip(),
            "answer": str(r.get("answer", "")).strip(),
            "example_ko": str(r.get("example_ko", "")).strip(),
            "example_en": str(r.get("example_en", "")).strip(),
        })
    return {"vocab": vocab, "grammar": grammar, "review": review,
            "tip": str(data.get("tip", "")).strip(),
            "culture": str(data.get("culture", "")).strip()}


# A sentence must be correct AND natural to "pass" (count as practicing the word).
PASS_THRESHOLD = 70

GRADE_SYSTEM = """\
You are an honest but supportive Korean tutor grading a learner's practice sentences
for this week's THEME VOCABULARY (given below). For EACH sentence: find which theme
word it practices (its EXACT Korean form from the list, or "" if none) and score it
0-100. Respond with ONLY a JSON object:

{ "results": [ {"sentence": "what they wrote", "word": "the theme word it uses (Korean) or ''",
                "score": 0-100,
                "corrected": "a corrected, natural version (same as theirs if already good)",
                "feedback": "1-2 sentences IN ENGLISH: what's right, what to fix and WHY; note any dropped particle or casual register"} ] }

LANGUAGE OF OUTPUT:
- "feedback" MUST be written in ENGLISH (the learner reads explanations in English).
  You may quote Korean words/particles inside the English feedback (e.g., "you dropped
  the object particle 을"), but the explanation itself is English, never written in Korean.
- "corrected" stays in Korean (it is the corrected Korean sentence).

SCORING RUBRIC (grade honestly - do not inflate):
- 85-100  : correct AND natural; a native speaker would actually say it this way.
- 70-84   : correct and clearly understandable, only minor awkwardness. (PASS)
- 50-69   : has a real grammar error, OR the target word is used unnaturally / non-
            idiomatically even though the meaning is guessable. (FAIL)
- 0-49    : broken grammar, wrong word meaning, or the target word is misused. (FAIL)

A sentence PASSES and counts as practicing the word ONLY at score >= 70.

JUDGE STRICTLY ON:
- Grammar correctness -> any genuine grammatical mistake keeps it BELOW 70.
- Correct, NATURAL use of the target word -> unnatural or wrong usage keeps it BELOW
  70, even if it could technically be understood. Naturalness counts.

ALLOW LEEWAY (do NOT drop below 70 for these alone, but DO mention them in feedback):
- Casual / colloquial register (반말, contractions) when otherwise correct.
- Subject/topic/object particles (은/는/이/가/을/를, and 에/에서 in casual speech) that
  native speakers naturally OMIT in conversation. Note the omission and where the
  particle would go, but don't fail the sentence solely for a naturally dropped particle."""


def grade_practice(sentences: list, *, vocab_context: str = "", theme_words: list | None = None,
                   model: str | None = None) -> list:
    """Grade learner practice sentences and match each to a theme word.

    Returns result dicts: {sentence, word, score, corrected, feedback}. ``word`` is the
    matched theme word (Korean) only when the sentence correctly and naturally
    practices it (score >= PASS_THRESHOLD).
    """
    sents = [s for s in (sentences or []) if str(s).strip()]
    if not sents:
        return []
    theme_txt = ", ".join(theme_words) if theme_words else (vocab_context or "(n/a)")
    user = ("THIS WEEK'S THEME WORDS:\n" + theme_txt + "\n\n"
            "MY PRACTICE SENTENCES:\n" + "\n".join(f"- {s}" for s in sents))
    data = llm.post_json(GRADE_SYSTEM, user, model=model, temperature=0.3, max_tokens=1800)
    valid = set(theme_words or [])
    out = []
    for r in (data.get("results") or []):
        if isinstance(r, dict) and r.get("sentence"):
            try:
                score = int(round(float(r.get("score", 0))))
            except (TypeError, ValueError):
                score = 0
            score = max(0, min(100, score))
            word = str(r.get("word", "")).strip()
            if valid and word not in valid:
                word = ""  # only trust exact theme-word matches
            out.append({"sentence": str(r["sentence"]).strip(),
                        "word": word if score >= PASS_THRESHOLD else "",
                        "score": score,
                        "corrected": str(r.get("corrected", "")).strip(),
                        "feedback": str(r.get("feedback", "")).strip()})
    return out


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


def practice_stats(state: dict) -> dict:
    """Aggregate scorekeeping over every graded practice sentence.

    Returns lifetime + this-week tallies, a pass streak, and the most recent graded
    sentences (newest first) for display in the dashboard.
    """
    prac = state.get("practice", {}) or {}
    flat = []  # (date, result)
    for date_str in sorted(prac.keys()):
        for r in (prac[date_str] or []):
            if isinstance(r, dict) and str(r.get("sentence", "")).strip():
                flat.append((date_str, r))

    def _score(r):
        try:
            return max(0, min(100, int(round(float(r.get("score", 0))))))
        except (TypeError, ValueError):
            return 0

    total = len(flat)
    scores = [_score(r) for _, r in flat]
    passed = sum(1 for s in scores if s >= PASS_THRESHOLD)
    avg = round(sum(scores) / total) if total else 0

    today = _today()
    ws = _week_start(today)
    wk = [s for (d, r), s in zip(flat, scores) if d >= ws]
    wk_passed = sum(1 for s in wk if s >= PASS_THRESHOLD)
    wk_avg = round(sum(wk) / len(wk)) if wk else 0

    # Streak: consecutive days up to today with at least one passing sentence.
    pass_days = {d for (d, r), s in zip(flat, scores) if s >= PASS_THRESHOLD}
    streak, cur_day = 0, datetime.strptime(today, "%Y-%m-%d").date()
    while cur_day.strftime("%Y-%m-%d") in pass_days:
        streak += 1
        cur_day -= timedelta(days=1)

    recent = [dict(r, date=d, score=s) for (d, r), s in zip(flat, scores)][-8:][::-1]
    return {
        "total": total,
        "passed": passed,
        "avg": avg,
        "pass_rate": round(100 * passed / total) if total else 0,
        "week_total": len(wk),
        "week_passed": wk_passed,
        "week_avg": wk_avg,
        "streak": streak,
        "pass_threshold": PASS_THRESHOLD,
        "recent": recent,
    }
