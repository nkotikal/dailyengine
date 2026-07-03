"""Job-posting tracker for Workday-backed career sites.

Queries the careers JSON API for internships (primary) and, optionally, full-time
roles that fit your profile. Flags postings matching your profile keywords (pulled
from your stored resume profile when available) and reports only NEW postings.

Most large tech firms use Workday; you only need the company's CXS "jobs" URL,
which you paste into the tracker. Optional named PRESETS can be added below.
"""

import json
import re
import urllib.request
from pathlib import Path

from . import store

ROOT = Path(__file__).resolve().parent.parent
RESUME_PROFILE = ROOT / "data" / "profile.json"

# Optional Workday "CXS" job-search presets keyed by a short name. Empty by
# default - paste a company's CXS jobs URL into the tracker's config instead.
PRESETS = {}

DEFAULT_PROFILE_KEYWORDS = [
    "machine learning", "ml", "deep learning", "ai", "compiler", "cuda", "gpu",
    "kernel", "systems", "infrastructure", "distributed", "python", "c++",
    "pytorch", "research", "performance", "hpc", "llvm", "inference", "training",
]

# Generic words that should never count as a "profile fit".
_STOPWORDS = {
    "intern", "internship", "engineer", "engineering", "software", "student",
    "summer", "fall", "winter", "spring", "work", "team", "new", "and", "the",
    "for", "with", "year", "university", "phd", "bs", "ms", "developer", "program",
    "co-op", "coop", "language", "general", "technical", "scientist",
    # common English / free-text noise (about/memory fields)
    "this", "that", "have", "has", "had", "are", "was", "were", "will", "would",
    "from", "into", "about", "over", "under", "they", "them", "you", "your", "our",
    "but", "not", "all", "any", "can", "out", "who", "what", "when", "where", "how",
    "working", "work", "focus", "focused", "currently", "looking", "want", "like",
    "role", "roles", "job", "jobs", "company", "experience", "skills", "build",
    "building", "built", "using", "use", "used", "project", "projects", "side",
    "deep", "machine", "learning",  # handled as the multi-word phrases below
}

# Multi-word phrases we still want to detect even though their parts are stopwords.
_PHRASES = ["machine learning", "deep learning", "reinforcement learning",
            "computer vision", "natural language", "computer architecture",
            "high performance", "operating systems", "distributed systems"]


def _tokens(text: str) -> list:
    return re.findall(r"[a-z0-9+#/.]{2,}", (text or "").lower())


def profile_keywords(cfg: dict) -> list:
    """Keywords used to flag 'fits my profile'.

    Config override wins; otherwise we combine the resume profile's skills, your
    'About you' text, and your Memory entries, plus sensible defaults. Generic
    words are dropped so fits stay meaningful.
    """
    raw = (cfg.get("profile_keywords") or "").strip()
    if raw:
        return [k.strip().lower() for k in raw.split(",") if k.strip()]

    # 1. Curated, trusted keywords: resume skills + defaults (any length kept).
    curated = list(DEFAULT_PROFILE_KEYWORDS)
    try:
        prof = json.loads(RESUME_PROFILE.read_text(encoding="utf-8"))
        for vals in (prof.get("skills") or {}).values():
            for v in (vals or []):
                curated.append(str(v).lower().strip())
    except (OSError, ValueError):
        pass

    # 2. "About you" + Memory (free text): only multi-word tech phrases and longer,
    #    non-numeric, non-stopword tokens, to avoid noise like "2026" or "in".
    free_text = ""
    try:
        free_text += " " + (store.load_config().get("about") or "")
    except Exception:  # noqa: BLE001
        pass
    try:
        free_text += " " + " ".join(m.get("text", "") for m in store.list_memories())
    except Exception:  # noqa: BLE001
        pass
    low = free_text.lower()
    free_kws = [ph for ph in _PHRASES if ph in low]
    for tok in _tokens(free_text):
        if len(tok) >= 4 and not tok.isdigit() and not re.fullmatch(r"[0-9]{4}", tok):
            free_kws.append(tok)

    out, seen = [], set()
    for k in curated + free_kws:
        k = k.strip()
        if len(k) >= 2 and not k.isdigit() and k not in seen and k not in _STOPWORDS:
            seen.add(k)
            out.append(k)
    return out[:120]


def profile_search_terms(cfg: dict, kws: list) -> list:
    """Search strings used to FIND full-time roles that fit the profile.

    Prefers strong multi-word phrases and distinctive skills (so Workday returns
    relevant roles rather than everything)."""
    explicit = (cfg.get("fulltime_query") or "").strip()
    if explicit:
        return [t.strip() for t in explicit.split(",") if t.strip()]
    terms = [k for k in kws if " " in k][:2]          # multi-word phrases first
    terms += [k for k in kws if " " not in k and len(k) >= 4][:2]
    # de-dupe, keep order
    out, seen = [], set()
    for t in terms:
        if t not in seen:
            seen.add(t)
            out.append(t)
    return out[:3] or ["machine learning"]


_UA = "Mozilla/5.0 (DailyDigest job tracker)"


def _query_workday(cxs_url: str, search_text: str, want: int = 60) -> list:
    """Page through the Workday CXS endpoint (it caps each page at 20)."""
    out = []
    offset = 0
    page = 20
    while len(out) < want:
        body = json.dumps({"appliedFacets": {}, "limit": page, "offset": offset,
                           "searchText": search_text}).encode()
        req = urllib.request.Request(cxs_url, data=body, method="POST", headers={
            "Content-Type": "application/json", "Accept": "application/json", "User-Agent": _UA,
        })
        with urllib.request.urlopen(req, timeout=30) as r:
            data = json.loads(r.read().decode("utf-8"))
        postings = data.get("jobPostings", [])
        if not postings:
            break
        for p in postings:
            out.append({
                "title": (p.get("title") or "").strip(),
                "location": (p.get("locationsText") or "").strip(),
                "posted": (p.get("postedOn") or "").strip(),
                "path": p.get("externalPath") or "",
                "bullets": " ".join(p.get("bulletFields") or []),
            })
        total = data.get("total", 0)
        offset += page
        if offset >= total:
            break
    return out


def _fit(text: str, keywords: list) -> list:
    """Match keywords against text. Multi-word/long keywords use substring; short
    tokens must match a whole word (so 'ai' doesn't match 'domain', 'go' not 'going')."""
    low = text.lower()
    words = set(re.findall(r"[a-z0-9+#/.]+", low))
    hits = []
    for k in keywords:
        if " " in k or len(k) > 4:
            if k in low:
                hits.append(k)
        elif k in words:
            hits.append(k)
    return hits


def _resolve(cfg: dict):
    preset = (cfg.get("preset") or "").strip().lower()
    if preset and preset in PRESETS:
        p = PRESETS[preset]
        return p["cxs"], p["site_url"]
    cxs = (cfg.get("cxs_url") or "").strip()
    if not cxs:
        raise ValueError("Jobs tracker needs config.cxs_url (a Workday CXS jobs URL).")
    site = (cfg.get("site_url") or cxs.split("/wday/")[0]).rstrip("/")
    return cxs, site


def _url_for(site_url: str, path: str) -> str:
    if not path:
        return site_url
    return site_url.rstrip("/") + path


def poll(tracker: dict, state: dict):
    cfg = tracker.get("config", {})
    cxs, site = _resolve(cfg)
    name = tracker.get("name") or "Jobs"
    kws = profile_keywords(cfg)
    loc_filter = [s.strip().lower() for s in (cfg.get("locations") or "").split(",") if s.strip()]

    queries = [("intern", (cfg.get("query") or "intern").strip() or "intern")]
    if cfg.get("include_fulltime"):
        for term in profile_search_terms(cfg, kws):
            queries.append(("fulltime", term))

    seen = set(state.get("seen_ids", []))
    first_run = "seen_ids" not in state
    collected = {}  # id -> finding dict

    for kind, search in queries:
        try:
            posts = _query_workday(cxs, search, want=int(cfg.get("limit", 40)))
        except Exception as exc:  # noqa: BLE001
            collected[f"err-{kind}"] = {"source": name, "text": f"(query '{search}' failed: {exc})", "error": True}
            continue
        for p in posts:
            title_low = p["title"].lower()
            is_intern = "intern" in title_low
            if kind == "fulltime" and is_intern:
                continue  # already covered by the intern query
            if loc_filter and not any(l in p["location"].lower() for l in loc_filter):
                continue
            jid = p["path"] or f"{p['title']}|{p['location']}"
            fits = _fit(p["title"] + " " + p["bullets"], kws)
            title_fits = _fit(p["title"], kws)
            if kind == "fulltime" and not fits:
                continue  # only surface full-time roles that match the profile
            tag = "intern" if is_intern else "full-time"
            star = "\u2605 " if title_fits else ("\u2606 " if fits else "")
            fit_str = f" \u00b7 fits: {', '.join(sorted(set(fits))[:4])}" if fits else ""
            url = _url_for(site, p["path"])
            collected[jid] = {
                "source": name,
                "text": f"{star}[{tag}] {p['title']} \u2014 {p['location'] or 'location N/A'}{fit_str} \u2014 {url}",
                "fit": bool(fits),
                "intern": is_intern,
            }

    all_ids = list(collected.keys())
    new_items = [v for k, v in collected.items() if k not in seen]
    # Sort: profile-fitting first, then internships, then the rest.
    new_items.sort(key=lambda f: (not f.get("fit"), not f.get("intern")))

    if first_run:
        fits_now = [f for f in new_items if f.get("fit")][:6]
        findings = [{"source": name,
                     "text": f"Now tracking {name}: {len(all_ids)} postings matched your "
                             f"queries; {sum(1 for f in collected.values() if f.get('fit'))} fit your profile."}]
        findings += fits_now
    else:
        findings = new_items[:15]

    new_state = {"seen_ids": (all_ids + list(seen))[:600]}
    return findings, new_state
