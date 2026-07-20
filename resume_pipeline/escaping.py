"""LaTeX escaping for user-supplied content fields.

Only data values are escaped; the macro scaffolding the pipeline emits is never
passed through these helpers.

Content is first normalized to ATS-safe ASCII: "fancy" Unicode that LLMs love to
emit (arrows, multiplication signs, smart quotes, en/em dashes, ellipses, and
exotic spaces) is mapped to plain equivalents. Those glyphs can render as boxes or
extract oddly in older ATS text layers; ASCII always compiles and extracts cleanly.
"""

import unicodedata

_BACKSLASH_PLACEHOLDER = "\x00BSLASH\x00"

# Map risky Unicode -> ATS-safe ASCII. (Accented Latin letters like e-acute/i-diaeresis
# are intentionally left intact -- they are standard and extract fine.)
_UNICODE_MAP = {
    # arrows
    "\u2192": "->", "\u27f6": "->", "\u2794": "->", "\u279c": "->", "\u2b62": "->",
    "\u21d2": "=>", "\u21a6": "->", "\u2190": "<-", "\u27f5": "<-",
    "\u2194": "<->", "\u21d4": "<=>",
    # multiplication / dimension
    "\u00d7": "x", "\u2715": "x", "\u2716": "x", "\u2a2f": "x",
    # dashes -> hyphen (consistent + ASCII)
    "\u2013": "-", "\u2014": "-", "\u2012": "-", "\u2015": "-", "\u2212": "-",
    # smart quotes / primes
    "\u2018": "'", "\u2019": "'", "\u201a": "'", "\u2032": "'",
    "\u201c": '"', "\u201d": '"', "\u201e": '"', "\u2033": '"',
    # ellipsis
    "\u2026": "...",
    # bullets / middots used inline
    "\u2022": "-", "\u2023": "-", "\u25aa": "-", "\u00b7": "-", "\u2027": "-",
    # exotic spaces -> normal space; zero-width -> removed
    "\u00a0": " ", "\u2009": " ", "\u202f": " ", "\u2007": " ", "\u2005": " ",
    "\u200b": "", "\u200c": "", "\u200d": "", "\ufeff": "",
}


def normalize_unicode(text) -> str:
    """Compose combining marks (NFC) then map risky Unicode to ATS-safe ASCII."""
    s = unicodedata.normalize("NFC", str(text))
    for k, v in _UNICODE_MAP.items():
        if k in s:
            s = s.replace(k, v)
    return s

# Order matters: backslash is stashed first so the replacements we introduce
# (which themselves contain backslashes/braces) are not re-escaped.
_REPLACEMENTS = (
    ("{", r"\{"),
    ("}", r"\}"),
    ("%", r"\%"),
    ("&", r"\&"),
    ("_", r"\_"),
    ("$", r"\$"),
    ("#", r"\#"),
    ("~", r"\textasciitilde{}"),
    ("^", r"\textasciicircum{}"),
    ("<", r"\textless{}"),
    (">", r"\textgreater{}"),
)


def escape_latex(text) -> str:
    """Normalize risky Unicode, then escape every LaTeX special character."""
    if text is None:
        return ""
    s = normalize_unicode(text)
    s = s.replace("\\", _BACKSLASH_PLACEHOLDER)
    for needle, repl in _REPLACEMENTS:
        s = s.replace(needle, repl)
    s = s.replace(_BACKSLASH_PLACEHOLDER, r"\textbackslash{}")
    return s


def escape_url(url) -> str:
    """Lightweight escaping for the URL argument of \\href.

    hyperref tolerates most characters in a URL, but '%', '#', and '\\' must be
    escaped to avoid compiler panics. Underscores are left intact (valid in URLs).
    """
    if url is None:
        return ""
    s = str(url).strip()
    s = s.replace("\\", r"\\")
    s = s.replace("%", r"\%")
    s = s.replace("#", r"\#")
    return s
