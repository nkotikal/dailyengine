"""Render the resume LaTeX from a profile.

Attribution (kept here in the source; intentionally NOT emitted into the generated
.tex output): the LaTeX preamble/macros are derived from Jake Gutierrez's resume
template (https://github.com/sb2nov/resume), MIT License.

The baseline preamble, custom macros, and section formatting are reproduced
exactly as written. The only values that change are the explicitly-permitted
density knobs (font size, spacing, margins) and how many bullets are kept --
all driven by the :class:`Density` config supplied by the shrink loop.
"""

from dataclasses import dataclass

from .escaping import escape_latex, escape_url
from . import tailor


@dataclass
class Density:
    """Layout knobs for one-page fitting. Defaults reproduce the baseline template."""

    font_pt: int = 11
    textwidth_extra: float = 1.0      # \addtolength{\textwidth}{<x>in}
    textheight_extra: float = 1.0     # \addtolength{\textheight}{<x>in}
    keep_recent: int = 999            # bullets for most-recent experience entry
    keep_older: int = 999             # bullets for older experience entries
    keep_project: int = 999           # bullets per project
    keep_skill_categories: int = 999  # max skill categories rendered
    # Spacing values copied from the baseline macros (pt). More-negative = tighter.
    item_vspace: int = -2
    sub_lead_vspace: int = -2
    sub_trail_vspace: int = -7
    listend_vspace: int = -5
    title_top_vspace: int = -4
    title_rule_vspace: int = -5

    @property
    def side_margin(self) -> float:
        # Keep margins balanced when textwidth grows beyond the baseline 1in.
        return -0.5 - (self.textwidth_extra - 1.0) / 2.0


# --- tolerant field access -------------------------------------------------

def _first(d: dict, *keys, default=""):
    for k in keys:
        if k in d and d[k] not in (None, ""):
            return d[k]
    return default


def _bullets(entry: dict):
    val = _first(entry, "bullets", "points", "highlights", "responsibilities", default=[])
    return list(val) if isinstance(val, (list, tuple)) else [str(val)]


# --- section renderers -----------------------------------------------------

def render_heading(contact: dict) -> str:
    name = escape_latex(_first(contact, "name", "full_name"))
    parts = []
    phone = _first(contact, "phone", "phone_number")
    if phone:
        parts.append(r"\small " + escape_latex(phone))
    email = _first(contact, "email")
    if email:
        parts.append(
            r"\href{mailto:%s}{\underline{%s}}" % (escape_url(email), escape_latex(email))
        )
    linkedin = _first(contact, "linkedin", "linkedin_url")
    if linkedin:
        url = linkedin if linkedin.startswith("http") else "https://" + linkedin
        disp = linkedin.replace("https://", "").replace("http://", "")
        parts.append(r"\href{%s}{\underline{%s}}" % (escape_url(url), escape_latex(disp)))
    github = _first(contact, "github", "github_url")
    if github:
        url = github if github.startswith("http") else "https://" + github
        disp = github.replace("https://", "").replace("http://", "")
        parts.append(r"\href{%s}{\underline{%s}}" % (escape_url(url), escape_latex(disp)))

    # First part already carries \small; join the rest with the template separator.
    contact_line = " $|$\n    ".join(parts)
    return (
        "\\begin{center}\n"
        "    \\textbf{\\Huge \\scshape %s} \\\\ \\vspace{1pt}\n"
        "    %s\n"
        "\\end{center}"
    ) % (name, contact_line)


def _resume_subheading(a, b, c, d) -> str:
    return (
        "    \\resumeSubheading\n"
        "      {%s}{%s}\n"
        "      {%s}{%s}"
    ) % (escape_latex(a), escape_latex(b), escape_latex(c), escape_latex(d))


def _item_list(bullets) -> str:
    lines = ["      \\resumeItemListStart"]
    for b in bullets:
        lines.append("        \\resumeItem{%s}" % escape_latex(b))
    lines.append("      \\resumeItemListEnd")
    return "\n".join(lines)


def render_education(education) -> str:
    blocks = []
    for entry in education:
        inst = _first(entry, "institution", "school", "university", "name")
        loc = _first(entry, "location")
        degree = _first(entry, "degree", "qualification")
        gpa = _first(entry, "gpa", "GPA")
        if gpa:
            degree = (degree + ", " if degree else "") + "GPA: " + str(gpa)
        dates = _first(entry, "dates", "date", "graduation", "graduation_date")
        blocks.append(_resume_subheading(inst, loc, degree, dates))
    return "\n".join(blocks)


def render_experience(experience, density: Density, weights: dict) -> str:
    blocks = []
    for idx, entry in enumerate(experience):
        company = _first(entry, "company", "employer", "organization", "name")
        loc = _first(entry, "location")
        role = _first(entry, "role", "title", "position")
        dates = _first(entry, "dates", "date")
        ranked = tailor.rank_items(_bullets(entry), lambda b: str(b), weights)
        cap = density.keep_recent if idx == 0 else density.keep_older
        kept = [b for b, _ in ranked[:cap]]
        block = _resume_subheading(company, loc, role, dates)
        if kept:
            block += "\n" + _item_list(kept)
        blocks.append(block)
    return "\n".join(blocks)


def render_projects(projects, density: Density, weights: dict) -> str:
    blocks = []
    for entry in projects:
        title = _first(entry, "title", "name", "project")
        tech = _first(entry, "tech", "tech_stack", "technologies", "stack", default=[])
        if isinstance(tech, (list, tuple)):
            tech_str = ", ".join(str(t) for t in tech)
        else:
            tech_str = str(tech)
        dates = _first(entry, "dates", "date")
        heading = "    \\resumeProjectHeading\n        {\\textbf{%s} $|$ \\emph{%s}}{%s}" % (
            escape_latex(title),
            escape_latex(tech_str),
            escape_latex(dates),
        )
        ranked = tailor.rank_items(_bullets(entry), lambda b: str(b), weights)
        kept = [b for b, _ in ranked[: density.keep_project]]
        if kept:
            heading += "\n" + _item_list(kept)
        blocks.append(heading)
    return "\n".join(blocks)


def render_skills(ordered_categories, density: Density) -> str:
    rows = []
    for cat in ordered_categories[: density.keep_skill_categories]:
        category = escape_latex(cat["category"])
        skills = ", ".join(escape_latex(s) for s in cat["skills"])
        rows.append("\\textbf{%s}{: %s}" % (category, skills))
    body = " \\\\\n     ".join(rows)
    return (
        " \\begin{itemize}[leftmargin=0.15in, label={}]\n"
        "    \\small{\\item{\n"
        "     %s\n"
        "    }}\n"
        " \\end{itemize}"
    ) % body


# --- full document ---------------------------------------------------------

_DOC = r"""%-------------------------
% Resume
%-------------------------

\documentclass[letterpaper,@@FONTPT@@pt]{article}

\usepackage{latexsym}
\usepackage[empty]{fullpage}
\usepackage{titlesec}
\usepackage{marvosym}
\usepackage[usenames,dvipsnames]{color}
\usepackage{verbatim}
\usepackage{enumitem}
\usepackage[hidelinks]{hyperref}
\usepackage{fancyhdr}
\usepackage[english]{babel}
\usepackage{tabularx}
\input{glyphtounicode}

\pagestyle{fancy}
\fancyhf{} 
\fancyfoot{}
\renewcommand{\headrulewidth}{0pt}
\renewcommand{\footrulewidth}{0pt}

\addtolength{\oddsidemargin}{@@SIDE@@in}
\addtolength{\evensidemargin}{@@SIDE@@in}
\addtolength{\textwidth}{@@TEXTWIDTH@@in}
\addtolength{\topmargin}{-.5in}
\addtolength{\textheight}{@@TEXTHEIGHT@@in}

\urlstyle{same}

\raggedbottom
\raggedright
\setlength{\tabcolsep}{0in}

\titleformat{\section}{
  \vspace{@@TITLETOP@@pt}\scshape\raggedright\large
}{}{0em}{}[\color{black}\titlerule \vspace{@@TITLERULE@@pt}]

\pdfgentounicode=1

\newcommand{\resumeItem}[1]{
  \item\small{{#1 \vspace{@@ITEMVSPACE@@pt}}}
}

\newcommand{\resumeSubheading}[4]{
  \vspace{@@SUBLEAD@@pt}\item
    \begin{tabular*}{0.97\textwidth}[t]{l@{\extracolsep{\fill}}r}
      \textbf{#1} & #2 \\
      \textit{\small#3} & \textit{\small #4} \\
    \end{tabular*}\vspace{@@SUBTRAIL@@pt}
}

\newcommand{\resumeSubSubheading}[2]{
    \item
    \begin{tabular*}{0.97\textwidth}{l@{\extracolsep{\fill}}r}
      \textit{\small#1} & \textit{\small #2} \\
    \end{tabular*}\vspace{-7pt}
}

\newcommand{\resumeProjectHeading}[2]{
    \item
    \begin{tabular*}{0.97\textwidth}{l@{\extracolsep{\fill}}r}
      \small#1 & #2 \\
    \end{tabular*}\vspace{-7pt}
}

\newcommand{\resumeSubItem}[1]{\resumeItem{#1}\vspace{-4pt}}

\renewcommand\labelitemii{$\vcenter{\hbox{\tiny$\bullet$}}$}

\newcommand{\resumeSubHeadingListStart}{\begin{itemize}[leftmargin=0.15in, label={}]}
\newcommand{\resumeSubHeadingListEnd}{\end{itemize}}
\newcommand{\resumeItemListStart}{\begin{itemize}}
\newcommand{\resumeItemListEnd}{\end{itemize}\vspace{@@LISTEND@@pt}}

\begin{document}

%--- HEADING ---
@@HEADING@@

%--- EDUCATION ---
\section{Education}
  \resumeSubHeadingListStart
@@EDUCATION@@
  \resumeSubHeadingListEnd

%--- EXPERIENCE ---
\section{Experience}
  \resumeSubHeadingListStart
@@EXPERIENCE@@
  \resumeSubHeadingListEnd
@@PROJECTS_SECTION@@
%--- TECHNICAL SKILLS ---
\section{Technical Skills}
@@SKILLS@@

\end{document}
"""


def build_document(profile: dict, weights: dict, density: Density) -> str:
    contact = profile.get("contact", {})
    education = profile.get("education", []) or []
    experience = profile.get("experience", []) or []
    projects = profile.get("projects", []) or []
    skills = profile.get("skills", {}) or {}

    ordered_skills = tailor.order_skills(skills, weights)

    projects_section = ""
    if projects:
        projects_section = (
            "\n%--- PROJECTS ---\n"
            "\\section{Projects}\n"
            "    \\resumeSubHeadingListStart\n"
            + render_projects(projects, density, weights)
            + "\n    \\resumeSubHeadingListEnd\n"
        )

    tokens = {
        "@@FONTPT@@": str(density.font_pt),
        "@@SIDE@@": _fmt(density.side_margin),
        "@@TEXTWIDTH@@": _fmt(density.textwidth_extra),
        "@@TEXTHEIGHT@@": _fmt(density.textheight_extra),
        "@@ITEMVSPACE@@": str(density.item_vspace),
        "@@SUBLEAD@@": str(density.sub_lead_vspace),
        "@@SUBTRAIL@@": str(density.sub_trail_vspace),
        "@@LISTEND@@": str(density.listend_vspace),
        "@@TITLETOP@@": str(density.title_top_vspace),
        "@@TITLERULE@@": str(density.title_rule_vspace),
        "@@HEADING@@": render_heading(contact),
        "@@EDUCATION@@": render_education(education),
        "@@EXPERIENCE@@": render_experience(experience, density, weights),
        "@@PROJECTS_SECTION@@": projects_section,
        "@@SKILLS@@": render_skills(ordered_skills, density),
    }
    doc = _DOC
    for token, value in tokens.items():
        doc = doc.replace(token, value)
    return doc


def _fmt(num: float) -> str:
    """Format a length so 1.0 -> '1', -0.5 -> '-0.5' (compact, valid LaTeX)."""
    if float(num).is_integer():
        return str(int(num))
    return ("%.2f" % num).rstrip("0").rstrip(".")
