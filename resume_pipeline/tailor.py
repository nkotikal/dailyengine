"""Deterministic job-description keyword scoring and content selection.

Content is never fabricated: keywords only re-order and (when space is tight)
trim existing profile content. All sorts are stable (score desc, original index
asc) so output is fully reproducible for identical inputs.
"""

import re

REQUIRED_WEIGHT = 2.0
PREFERRED_WEIGHT = 1.0
# A keyword that only appears as a substring (not a whole token) counts for less.
PARTIAL_FACTOR = 0.5


def normalize_keywords(raw) -> dict:
    """Turn the keyword payload into {lowercased_keyword: weight}.

    Accepts either a flat list of strings, or an object with any of the keys
    ``required`` / ``preferred`` / ``keywords``.
    """
    weights: dict[str, float] = {}

    def _add(values, weight):
        for v in values or []:
            k = str(v).strip().lower()
            if not k:
                continue
            weights[k] = max(weights.get(k, 0.0), weight)

    if isinstance(raw, list):
        _add(raw, PREFERRED_WEIGHT)
    elif isinstance(raw, dict):
        _add(raw.get("required"), REQUIRED_WEIGHT)
        _add(raw.get("preferred"), PREFERRED_WEIGHT)
        _add(raw.get("keywords"), PREFERRED_WEIGHT)
    return weights


def _boundary_pattern(keyword: str) -> re.Pattern:
    return re.compile(r"(?<![a-z0-9+#])" + re.escape(keyword) + r"(?![a-z0-9+#])")


def matched_keywords(text: str, weights: dict) -> set:
    if not text:
        return set()
    low = text.lower()
    found = set()
    for kw in weights:
        if _boundary_pattern(kw).search(low) or kw in low:
            found.add(kw)
    return found


def score_text(text: str, weights: dict) -> float:
    if not text or not weights:
        return 0.0
    low = text.lower()
    total = 0.0
    for kw, w in weights.items():
        if _boundary_pattern(kw).search(low):
            total += w
        elif kw in low:
            total += w * PARTIAL_FACTOR
    return total


def rank_items(items, key_fn, weights):
    """Return a list of (item, score) sorted by score desc, original index asc."""
    scored = [(item, score_text(key_fn(item), weights), idx) for idx, item in enumerate(items)]
    scored.sort(key=lambda t: (-t[1], t[2]))
    return [(item, score) for item, score, _ in scored]


def order_skills(skills: dict, weights: dict):
    """Return ordered list of (category, ordered_skills) by keyword relevance.

    Categories are ordered by their best-matching skill; skills within a
    category are ordered by individual match score. Original order breaks ties.
    """
    ordered = []
    for cat_idx, (category, skill_list) in enumerate(skills.items()):
        scored_skills = [
            (skill, score_text(str(skill), weights), s_idx)
            for s_idx, skill in enumerate(skill_list)
        ]
        scored_skills.sort(key=lambda t: (-t[1], t[2]))
        best = scored_skills[0][1] if scored_skills else 0.0
        ordered.append(
            {
                "category": category,
                "skills": [s for s, _, _ in scored_skills],
                "scores": [sc for _, sc, _ in scored_skills],
                "best": best,
                "orig": cat_idx,
            }
        )
    ordered.sort(key=lambda c: (-c["best"], c["orig"]))
    return ordered
