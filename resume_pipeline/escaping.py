"""LaTeX escaping for user-supplied content fields.

Only data values are escaped; the macro scaffolding the pipeline emits is never
passed through these helpers.
"""

_BACKSLASH_PLACEHOLDER = "\x00BSLASH\x00"

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
    """Escape every LaTeX special character in arbitrary input text."""
    if text is None:
        return ""
    s = str(text)
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
