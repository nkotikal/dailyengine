"""Pluggable trackers that surface "new developments" for the digest.

Built-in types (add your own by extending POLLERS):
  github  - new issues/PRs in a repo (GitHub REST API; optional GITHUB_TOKEN).
  web     - watch a page for keywords (e.g. a careers page for "intern") or any change.
  inbox   - recent/unread emails via IMAP (uses IMAP_* env vars).

Each tracker: {id, type, name, enabled, config}. Per-tracker state (last check,
seen ids, content hash) is persisted via ``store`` so only NEW things are reported.
A failing tracker reports the error as a finding instead of breaking the digest.
"""

import email as _email
import hashlib
import imaplib
import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from email.header import decode_header

from . import jobs as _jobs
from . import store

_UA = "DailyDigest/1.0 (+local)"


def poll_all(only_enabled: bool = True, persist: bool = True) -> list:
    """Poll every (enabled) tracker; return a flat list of finding dicts.

    When ``persist`` is False (e.g. a preview), tracker state is NOT advanced, so
    a later real send still reports the same new items.
    """
    findings = []
    for t in store.list_trackers():
        if only_enabled and not t.get("enabled", True):
            continue
        poller = POLLERS.get(t.get("type"))
        if not poller:
            continue
        st = store.get_tracker_state(t["id"])
        try:
            new_findings, new_state = poller(t, st)
        except Exception as exc:  # noqa: BLE001 - never let one tracker break the digest
            new_findings = [{
                "source": t.get("name", t.get("type", "tracker")),
                "text": f"(tracker error: {type(exc).__name__}: {exc})",
                "error": True,
            }]
            new_state = st
        if persist:
            store.set_tracker_state(t["id"], new_state)
        findings.extend(new_findings)
    return findings


def test_one(tracker: dict) -> list:
    """Run a single tracker once WITHOUT persisting state (for the UI 'Test' button)."""
    poller = POLLERS.get(tracker.get("type"))
    if not poller:
        raise ValueError(f"Unknown tracker type: {tracker.get('type')}")
    findings, _ = poller(tracker, store.get_tracker_state(tracker.get("id", "")))
    return findings


# --- github ----------------------------------------------------------------

def _poll_github(t: dict, st: dict):
    cfg = t.get("config", {})
    repo = (cfg.get("repo") or "").strip().strip("/")
    if "/" not in repo:
        raise ValueError("GitHub tracker needs config.repo as 'owner/name'.")
    want_prs = (cfg.get("which") or "issues").lower() == "prs"
    labels = (cfg.get("labels") or "").strip()

    url = f"https://api.github.com/repos/{repo}/issues?state=open&sort=created&direction=desc&per_page=20"
    if labels:
        url += "&labels=" + urllib.parse.quote(labels)
    headers = {"User-Agent": _UA, "Accept": "application/vnd.github+json"}
    token = os.environ.get("GITHUB_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=30) as resp:
        items = json.loads(resp.read().decode("utf-8"))

    seen = set(st.get("seen_ids", []))
    name = t.get("name") or repo
    findings, ids = [], []
    first_run = not st.get("seen_ids")
    for it in items:
        is_pr = "pull_request" in it
        if want_prs != is_pr:
            continue
        num = it.get("number")
        ids.append(num)
        if num in seen:
            continue
        kind = "PR" if is_pr else "issue"
        findings.append({
            "source": name,
            "text": f"New {kind} #{num}: {it.get('title','').strip()} "
                    f"(by {it.get('user',{}).get('login','?')}) {it.get('html_url','')}",
        })
    if first_run:
        # Don't flood on first run; just establish the baseline.
        findings = [{"source": name, "text": f"Now tracking {repo} ({'PRs' if want_prs else 'issues'})."}]
    new_state = {
        "seen_ids": (ids + list(seen))[:200],
        "last_check": datetime.now(timezone.utc).isoformat(),
    }
    return findings, new_state


# --- web -------------------------------------------------------------------

def _strip_html(html: str) -> str:
    html = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", " ", html)
    text = re.sub(r"(?s)<[^>]+>", " ", html)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def _poll_web(t: dict, st: dict):
    cfg = t.get("config", {})
    url = (cfg.get("url") or "").strip()
    if not url.startswith("http"):
        raise ValueError("Web tracker needs a config.url starting with http(s).")
    keywords = [k.strip().lower() for k in (cfg.get("keywords") or "").split(",") if k.strip()]
    name = t.get("name") or url

    req = urllib.request.Request(url, headers={"User-Agent": _UA})
    with urllib.request.urlopen(req, timeout=30) as resp:
        raw = resp.read().decode("utf-8", errors="replace")
    text = _strip_html(raw)
    low = text.lower()
    findings = []

    if keywords:
        present = [k for k in keywords if k in low]
        prev_present = set(st.get("present_keywords", []))
        newly = [k for k in present if k not in prev_present]
        first_run = "present_keywords" not in st
        if first_run and present:
            findings.append({"source": name,
                             "text": f"Tracking {url}; currently mentions: {', '.join(present)}."})
        elif first_run:
            findings.append({"source": name,
                             "text": f"Tracking {url} for: {', '.join(keywords)} (none present yet)."})
        for k in newly:
            findings.append({"source": name, "text": f"'{k}' now appears on {url}"})
        new_state = {"present_keywords": present,
                     "last_check": datetime.now(timezone.utc).isoformat()}
    else:
        digest_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()
        prev = st.get("hash")
        if prev is None:
            findings.append({"source": name, "text": f"Now watching {url} for changes."})
        elif prev != digest_hash:
            findings.append({"source": name, "text": f"Page changed: {url}"})
        new_state = {"hash": digest_hash, "last_check": datetime.now(timezone.utc).isoformat()}
    return findings, new_state


# --- inbox (IMAP) ----------------------------------------------------------

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


def _poll_inbox(t: dict, st: dict):
    cfg = t.get("config", {})
    host = os.environ.get("IMAP_HOST", "imap.gmail.com")
    port = int(os.environ.get("IMAP_PORT", "993") or "993")
    user = os.environ.get("IMAP_USER") or os.environ.get("SMTP_USER")
    password = os.environ.get("IMAP_PASSWORD") or os.environ.get("SMTP_PASSWORD")
    if not (user and password):
        raise ValueError("Inbox tracker needs IMAP_USER/IMAP_PASSWORD (or SMTP_*) in .env.")
    folder = cfg.get("folder") or "INBOX"
    max_n = int(cfg.get("max", 8))
    name = t.get("name") or f"Inbox ({user})"

    criteria = "UNSEEN" if cfg.get("unseen_only", True) else "ALL"
    from_filter = (cfg.get("from") or "").strip()
    subject_filter = (cfg.get("subject") or "").strip()

    seen = set(st.get("seen_uids", []))
    first_run = "seen_uids" not in st
    findings, new_uids = [], []

    M = imaplib.IMAP4_SSL(host, port)
    try:
        M.login(user, password)
        M.select(folder, readonly=True)
        crit = [criteria]
        if from_filter:
            crit += ["FROM", from_filter]
        if subject_filter:
            crit += ["SUBJECT", subject_filter]
        typ, data = M.search(None, *crit)
        ids = data[0].split() if data and data[0] else []
        ids = ids[-max_n:]
        for i in reversed(ids):
            typ, msg_data = M.fetch(i, "(BODY.PEEK[HEADER.FIELDS (FROM SUBJECT DATE)])")
            uid = i.decode()
            new_uids.append(uid)
            if uid in seen:
                continue
            raw = msg_data[0][1].decode("utf-8", errors="replace") if msg_data and msg_data[0] else ""
            hdr = _email.message_from_string(raw)
            findings.append({
                "source": name,
                "text": f"{_decode(hdr.get('Subject')) or '(no subject)'} "
                        f"- from {_decode(hdr.get('From'))}",
            })
    finally:
        try:
            M.logout()
        except Exception:  # noqa: BLE001
            pass

    if first_run:
        findings = [{"source": name, "text": f"Now monitoring {folder} for {user}."}]
    new_state = {"seen_uids": (new_uids + list(seen))[:300],
                 "last_check": datetime.now(timezone.utc).isoformat()}
    return findings, new_state


POLLERS = {
    "github": _poll_github,
    "web": _poll_web,
    "inbox": _poll_inbox,
    "jobs": _jobs.poll,
}

TRACKER_TYPES = {
    "github": {
        "label": "GitHub issues / PRs",
        "fields": [
            {"key": "repo", "label": "Repository (owner/name)", "placeholder": "NVIDIA/cutlass"},
            {"key": "which", "label": "Track", "type": "select", "options": ["issues", "prs"]},
            {"key": "labels", "label": "Labels filter (optional)", "placeholder": "good first issue"},
        ],
    },
    "web": {
        "label": "Web page / job watch",
        "fields": [
            {"key": "url", "label": "URL", "placeholder": "https://www.nvidia.com/en-us/about-nvidia/careers/"},
            {"key": "keywords", "label": "Keywords (comma-sep; blank = any change)",
             "placeholder": "intern, internship, university"},
        ],
    },
    "inbox": {
        "label": "Email inbox (IMAP)",
        "fields": [
            {"key": "from", "label": "From contains (optional)", "placeholder": "noreply@greenhouse.io"},
            {"key": "subject", "label": "Subject contains (optional)", "placeholder": "interview"},
            {"key": "unseen_only", "label": "Unread only", "type": "bool"},
        ],
    },
    "jobs": {
        "label": "Job postings (NVIDIA / Workday)",
        "fields": [
            {"key": "preset", "label": "Company", "type": "select", "options": ["nvidia", "custom"]},
            {"key": "cxs_url", "label": "Custom Workday CXS URL (only if 'custom')",
             "placeholder": "https://company.wdN.myworkdayjobs.com/wday/cxs/.../jobs"},
            {"key": "query", "label": "Internship search", "placeholder": "intern"},
            {"key": "include_fulltime", "label": "Also full-time roles that fit my profile", "type": "bool"},
            {"key": "fulltime_query", "label": "Full-time search override (blank = auto from About + Memory)",
             "placeholder": "machine learning, compiler"},
            {"key": "locations", "label": "Locations filter (comma, blank = anywhere)", "placeholder": "(any location)"},
            {"key": "profile_keywords", "label": "Profile keywords (blank = from resume + About + Memory)",
             "placeholder": "machine learning, compiler, cuda, gpu"},
        ],
    },
}
