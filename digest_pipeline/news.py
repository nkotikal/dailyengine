"""Headlines for the digest - pluggable news sources (start: Hacker News).

Each source is {id, type, name, url, enabled}. Add/remove sources from the UI.
The fetched headlines are passed to the digest composer, which picks the few most
relevant to the user's stated interests for a 'Headlines' section.
"""

import json
import urllib.error
import urllib.request

_UA = "DailyDigest/1.0 (+local)"
HN_FRONT = "https://hn.algolia.com/api/v1/search?tags=front_page&hitsPerPage=30"


def _get_json(url: str, timeout: int = 20):
    req = urllib.request.Request(url, headers={"User-Agent": _UA})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def fetch_hackernews(source: dict, limit: int = 30) -> list:
    data = _get_json(HN_FRONT)
    out = []
    for h in data.get("hits", []):
        title = (h.get("title") or "").strip()
        if not title:
            continue
        url = h.get("url") or f"https://news.ycombinator.com/item?id={h.get('objectID')}"
        out.append({
            "title": title,
            "url": url,
            "points": int(h.get("points") or 0),
            "comments": int(h.get("num_comments") or 0),
            "source": source.get("name", "Hacker News"),
        })
    out.sort(key=lambda x: -x["points"])
    return out[:limit]


# Map a source "type" to its fetcher. Add new types here to support more sites.
FETCHERS = {
    "hackernews": fetch_hackernews,
}

SOURCE_TYPES = {
    "hackernews": {"label": "Hacker News (front page)",
                   "default_url": "https://news.ycombinator.com/"},
}


def fetch_all(sources: list, per_source: int = 30) -> list:
    items = []
    for s in sources or []:
        if not s.get("enabled", True):
            continue
        fn = FETCHERS.get(s.get("type"))
        if not fn:
            continue
        try:
            items.extend(fn(s, per_source))
        except (urllib.error.URLError, urllib.error.HTTPError, ValueError, TimeoutError) as exc:
            items.append({"title": f"(couldn't fetch {s.get('name', s.get('type'))}: {exc})",
                          "url": "", "points": 0, "comments": 0, "source": s.get("name", "")})
    return items


def render_for_llm(items: list, limit: int = 30) -> str:
    """Numbered list so the composer can reference a story by index (ref:N) instead
    of copying URLs (which it mis-copies, sending links to the wrong story)."""
    lines = []
    for i, h in enumerate(items[:limit], start=1):
        meta = f" ({h['points']} pts)" if h.get("points") else ""
        lines.append(f"[{i}] {h['title']}{meta}")
    return "\n".join(lines)
