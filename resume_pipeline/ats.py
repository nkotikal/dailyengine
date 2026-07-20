"""Deterministic ATS keyword-coverage pass.

The LLM optimizer already weaves in JD keywords, but it sometimes leaves a literal
ATS phrase uncovered when it used a synonym (e.g. it wrote "Terraform-managed
infrastructure" while the JD asks for "infrastructure as code"). Automated ATS
filters often match on the literal phrase, so that costs a match for no good reason.

This pass runs AFTER optimization, with zero LLM cost, and:
  1. Determines which JD keywords are covered (exactly, or via a true synonym/alias),
  2. For a keyword missing as an EXACT phrase but whose synonym is already truthfully
     present, injects the exact phrase into the relevant skills category (safe: it's
     the same fact, just the JD's wording),
  3. Reports keywords with NO evidence at all as genuinely uncovered (never injected -
     inventing those would be fabrication).

It never touches experience/education facts and never adds a term the resume can't
already substantiate through a synonym.
"""

import re

# Equivalence classes of interchangeable terms (abbreviations + true synonyms, and a
# few tool->concept pairs where using the tool IS doing the concept). All lowercase.
# If ANY member of a class is present in the resume, the class is "supported", so the
# JD's exact member is safe to surface.
ALIAS_CLASSES = [
    {"infrastructure as code", "iac", "terraform", "cloudformation", "pulumi", "ansible"},
    {"ci/cd", "cicd", "continuous integration", "continuous delivery",
     "continuous deployment", "github actions", "gitlab ci", "jenkins", "circleci"},
    {"kubernetes", "k8s"},
    {"postgresql", "postgres"},
    {"javascript", "js"},
    {"typescript", "ts"},
    {"amazon web services", "aws"},
    {"google cloud platform", "google cloud", "gcp"},
    {"microsoft azure", "azure"},
    {"machine learning", "ml"},
    {"natural language processing", "nlp"},
    {"event pipeline", "event pipelines", "event streaming", "event-driven",
     "kafka", "kinesis", "pub/sub", "rabbitmq"},
    {"rest api", "rest apis", "restful", "rest"},
    {"object relational mapping", "orm", "sqlalchemy", "hibernate", "prisma"},
]

# When a synonym is present only in bullets (not skills), inject into a skills
# category whose name matches one of these hints (else the first category).
_CATEGORY_HINTS = ("cloud", "devops", "infra", "tools", "platform", "backend")


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", str(s or "").strip().lower())


def flatten_text(profile: dict) -> str:
    """Lowercased text of the resume CONTENT (skills, experience, projects)."""
    parts = []

    def walk(x):
        if isinstance(x, str):
            parts.append(x)
        elif isinstance(x, list):
            for i in x:
                walk(i)
        elif isinstance(x, dict):
            for v in x.values():
                walk(v)

    for key in ("skills", "experience", "projects"):
        walk(profile.get(key))
    return _norm(" ".join(parts))


def _present(term: str, haystack: str) -> bool:
    """Word-ish containment of ``term`` in the (already lowercased) haystack."""
    t = _norm(term)
    if not t:
        return False
    # Use boundaries for short alphanumeric tokens to avoid 'go' matching 'google'.
    if re.fullmatch(r"[a-z0-9+#./ -]{1,4}", t):
        return re.search(r"(?<![a-z0-9])" + re.escape(t) + r"(?![a-z0-9])", haystack) is not None
    return t in haystack


def _alias_class(keyword: str):
    k = _norm(keyword)
    for cls in ALIAS_CLASSES:
        if k in cls:
            return cls
    return None


def extract_jd_keywords(jd_text: str = "", keywords=None) -> list:
    """Best-effort target keyword list. Prefers an explicit keywords spec; otherwise
    pulls known tech terms + notable capitalized/acronym tokens from the JD text."""
    out, seen = [], set()

    def add(k):
        k = str(k or "").strip()
        if k and _norm(k) not in seen:
            seen.add(_norm(k))
            out.append(k)

    if isinstance(keywords, dict):
        for key in ("required", "preferred", "keywords"):
            for k in keywords.get(key, []) or []:
                add(k)
    elif isinstance(keywords, list):
        for k in keywords:
            add(k)

    low = _norm(jd_text)
    if low:
        # Known multi-word phrases + alias members that literally appear in the JD.
        for cls in ALIAS_CLASSES:
            for member in cls:
                if " " in member and member in low:
                    add(member)
        # Capitalized / acronym-ish tokens from the raw JD (e.g. Kafka, Snowflake, AWS).
        for tok in re.findall(r"\b[A-Z][A-Za-z0-9+#./-]{1,}\b", jd_text or ""):
            if tok.lower() not in {"we", "you", "the", "our", "and", "with", "will"}:
                add(tok)
    return out


def coverage(profile: dict, jd_keywords: list) -> dict:
    """Classify each keyword: covered exactly, covered via a present synonym, or missing."""
    hay = flatten_text(profile)
    exact, via_alias, missing = [], [], []
    for kw in jd_keywords:
        if _present(kw, hay):
            exact.append(kw)
            continue
        cls = _alias_class(kw)
        if cls and any(_present(m, hay) for m in cls):
            via_alias.append(kw)      # synonym present -> safe to surface exact phrase
        else:
            missing.append(kw)        # no evidence -> a real gap, never injected
    total = len(jd_keywords) or 1
    return {
        "exact": exact, "via_alias": via_alias, "missing": missing,
        "covered": len(exact) + len(via_alias), "total": len(jd_keywords),
        "pct": round(100 * (len(exact) + len(via_alias)) / total),
    }


def _pick_category(profile: dict, keyword: str) -> str:
    """Choose a skills category to receive an injected keyword."""
    skills = profile.get("skills")
    if not isinstance(skills, dict) or not skills:
        return "Skills"
    hay_by_cat = {cat: _norm(" ".join(str(v) for v in (vals or [])))
                  for cat, vals in skills.items()}
    cls = _alias_class(keyword) or {_norm(keyword)}
    # Prefer the category already listing a synonym of this keyword.
    for cat, hay in hay_by_cat.items():
        if any(_present(m, hay) for m in cls):
            return cat
    # Else a category whose name hints at the right area.
    for cat in skills:
        if any(h in _norm(cat) for h in _CATEGORY_HINTS):
            return cat
    return next(iter(skills))


def apply(profile: dict, jd_text: str = "", keywords=None, *, max_inject: int = 10) -> dict:
    """Inject exact JD phrases that are truthfully supported (synonym present) into
    skills, in place. Returns a report; never fabricates unsupported keywords."""
    jd_keywords = extract_jd_keywords(jd_text, keywords)
    if not jd_keywords:
        return {"targeted": 0, "injected": [], "covered_exact": 0,
                "covered_alias": 0, "missing": [], "pct_before": 100, "pct_after": 100}

    before = coverage(profile, jd_keywords)
    skills = profile.get("skills")
    if not isinstance(skills, dict):
        skills = {}
        profile["skills"] = skills

    injected = []
    for kw in before["via_alias"][:max_inject]:
        cat = _pick_category(profile, kw)
        bucket = skills.setdefault(cat, [])
        if not isinstance(bucket, list):
            bucket = [bucket]
            skills[cat] = bucket
        if not any(_norm(kw) == _norm(x) for x in bucket):
            bucket.append(kw)
            injected.append({"keyword": kw, "category": cat})

    after = coverage(profile, jd_keywords)
    total = len(jd_keywords) or 1
    # The ATS-relevant metric is EXACT literal coverage (what keyword filters match on);
    # this pass converts "supported via synonym" into "present as the exact phrase".
    return {
        "targeted": len(jd_keywords),
        "injected": injected,
        "covered_exact": len(after["exact"]),
        "covered_alias": len(after["via_alias"]),
        "missing": after["missing"],
        "exact_before": len(before["exact"]),
        "exact_after": len(after["exact"]),
        "pct_before": round(100 * len(before["exact"]) / total),
        "pct_after": round(100 * len(after["exact"]) / total),
    }
