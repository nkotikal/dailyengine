"""Job-posting tracker for Eightfold-backed career sites (e.g. NVIDIA).

Eightfold tenants expose a public JSON jobs API:
    GET https://<host>/api/apply/v2/jobs?domain=<domain>&start=0&num=10&query=<q>&sort_by=timestamp
    -> { "count": N, "positions": [ {id, name, location, locations, department, ...} ] }

Mirrors ``jobs`` (the Workday tracker): finds internships (primary) and, optionally,
full-time roles that fit your profile, flags profile matches, and reports only NEW
postings. Reuses the profile-keyword logic from ``jobs`` so the two behave the same.
"""

import json
import urllib.parse
import urllib.request

from . import jobs

_UA = "Mozilla/5.0 (DailyDigest job tracker)"


def _resolve(cfg: dict):
    """Return (host, domain) from config. Accepts a bare host or a full careers URL;
    derives the domain from the subdomain if not given (nvidia.eightfold.ai -> nvidia.com)."""
    host = (cfg.get("host") or cfg.get("url") or "").strip()
    domain = (cfg.get("domain") or "").strip()
    if "://" in host or "/" in host:
        pu = urllib.parse.urlparse(host if "://" in host else "https://" + host)
        if pu.hostname:
            host = pu.hostname
        q = urllib.parse.parse_qs(pu.query or "")
        if not domain and q.get("domain"):
            domain = q["domain"][0]
    host = host.strip().rstrip("/")
    if not host:
        raise ValueError("Eightfold tracker needs a host, e.g. 'company.eightfold.ai'.")
    if not domain:
        label = host.split(".")[0]
        domain = f"{label}.com" if label else ""
    return host, domain


def _query(host: str, domain: str, search: str, want: int = 40) -> list:
    """Page through the Eightfold jobs API (num caps per page)."""
    out = []
    offset, page = 0, 25
    while len(out) < want:
        params = urllib.parse.urlencode({
            "domain": domain, "start": offset, "num": page,
            "sort_by": "timestamp", "query": search or "",
        })
        url = f"https://{host}/api/apply/v2/jobs?{params}"
        req = urllib.request.Request(url, headers={
            "User-Agent": _UA, "Accept": "application/json",
            "Referer": f"https://{host}/careers",
        })
        with urllib.request.urlopen(req, timeout=30) as r:
            data = json.loads(r.read().decode("utf-8"))
        positions = data.get("positions") or []
        if not positions:
            break
        for p in positions:
            loc = (p.get("location") or "").strip()
            if not loc and p.get("locations"):
                loc = ", ".join([str(x) for x in p["locations"][:1]])
            out.append({
                "id": str(p.get("id") or p.get("display_job_id") or ""),
                "title": (p.get("name") or p.get("display_job_title") or "").strip(),
                "location": loc,
                "bullets": " ".join(filter(None, [
                    str(p.get("department") or ""),
                    " ".join(str(x) for x in (p.get("locations") or [])),
                ])),
                "url": (p.get("canonicalPositionUrl") or "").strip(),
            })
        count = data.get("count", len(out))
        offset += page
        if offset >= count:
            break
    return out


def _job_url(host: str, domain: str, p: dict) -> str:
    if p.get("url"):
        return p["url"]
    q = urllib.parse.urlencode({"domain": domain, "pid": p["id"], "sort_by": "timestamp"})
    return f"https://{host}/careers?{q}"


def poll(tracker: dict, state: dict):
    cfg = tracker.get("config", {})
    host, domain = _resolve(cfg)
    name = tracker.get("name") or "Jobs (Eightfold)"
    kws = jobs.profile_keywords(cfg)
    loc_filter = [s.strip().lower() for s in (cfg.get("locations") or "").split(",") if s.strip()]

    queries = [("intern", (cfg.get("query") or "intern").strip() or "intern")]
    if cfg.get("include_fulltime"):
        for term in jobs.profile_search_terms(cfg, kws):
            queries.append(("fulltime", term))

    seen = set(state.get("seen_ids", []))
    first_run = "seen_ids" not in state
    collected = {}

    for kind, search in queries:
        try:
            posts = _query(host, domain, search, want=int(cfg.get("limit", 40)))
        except Exception as exc:  # noqa: BLE001
            collected[f"err-{kind}"] = {"source": name,
                                        "text": f"(query '{search}' failed: {exc})", "error": True}
            continue
        for p in posts:
            if not p["id"] or not p["title"]:
                continue
            title_low = p["title"].lower()
            is_intern = "intern" in title_low
            if kind == "fulltime" and is_intern:
                continue
            if loc_filter and not any(l in p["location"].lower() for l in loc_filter):
                continue
            fits = jobs._fit(p["title"] + " " + p["bullets"], kws)
            title_fits = jobs._fit(p["title"], kws)
            if kind == "fulltime" and not fits:
                continue
            tag = "intern" if is_intern else "full-time"
            star = "\u2605 " if title_fits else ("\u2606 " if fits else "")
            fit_str = f" \u00b7 fits: {', '.join(sorted(set(fits))[:4])}" if fits else ""
            url = _job_url(host, domain, p)
            collected[p["id"]] = {
                "source": name,
                "text": f"{star}[{tag}] {p['title']} \u2014 {p['location'] or 'location N/A'}{fit_str} \u2014 {url}",
                "fit": bool(fits),
                "intern": is_intern,
            }

    real = {k: v for k, v in collected.items() if not v.get("error")}
    errs = [v for v in collected.values() if v.get("error")]
    all_ids = list(real.keys())
    new_items = [v for k, v in real.items() if k not in seen]
    new_items.sort(key=lambda f: (not f.get("fit"), not f.get("intern")))

    if first_run:
        findings = [{"source": name,
                     "text": f"Now tracking {name}: {len(all_ids)} postings matched your "
                             f"queries; {sum(1 for f in real.values() if f.get('fit'))} fit your profile."}]
        findings += [f for f in new_items if f.get("fit")][:6]
    else:
        findings = new_items[:15]
    findings += errs  # surface any query errors so failures aren't silent

    new_state = {"seen_ids": (all_ids + list(seen))[:600]}
    return findings, new_state
