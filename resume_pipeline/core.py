"""Shared generation core used by both the CLI and the web server.

Encapsulates: profile resolution (explicit dict or stored), job-description
resolution, LLM vs deterministic tailoring, rendering, and the one-page
auto-fit compile. Raises exceptions on error; callers format the output.
"""

import json
import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import app_paths

from . import compile as texc
from .compile import CompileError
from . import llm, store, tailor
from .template import Density, build_document

PROFILE_HINT_KEYS = ("contact", "experience", "education", "skills", "projects")

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OUT = app_paths.data_dir() / "output" / "resume.tex"  # writable when frozen
DEFAULT_ENV = app_paths.env_path()


def load_dotenv(path: Path = DEFAULT_ENV) -> None:
    """Minimal .env loader (stdlib only); does not override the real environment."""
    path = Path(path)
    if path.exists():
        for raw in path.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            if line.lower().startswith("export "):
                line = line[len("export "):]
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            if key and key not in os.environ:
                os.environ[key] = value
    _configure_ca_bundle()


def _configure_ca_bundle() -> None:
    """Trust extra corporate CAs (e.g. AMD Zscaler) for all outbound HTTPS.

    On networks that intercept TLS (Zscaler/Netskope), Python's CA store won't
    trust the proxy's certificates and every HTTPS call fails. If a corporate CA
    bundle is available, we merge it with the system CAs and point SSL_CERT_FILE at
    the result, fixing the LLM gateway, GitHub, careers sites, etc. Harmless off
    the corporate network (the extra CAs simply go unused).
    """
    import ssl

    # An explicit SSL_CERT_FILE always wins.
    if os.environ.get("SSL_CERT_FILE"):
        return
    extra = os.environ.get("EXTRA_CA_CERTS")
    if not extra:
        default_extra = ROOT / "certs" / "amd-zscaler-ca.pem"
        extra = str(default_extra) if default_extra.exists() else ""
    if not extra or not Path(extra).exists():
        return
    try:
        system = None
        for cand in (ssl.get_default_verify_paths().cafile,
                     "/etc/ssl/certs/ca-certificates.crt"):
            if cand and Path(cand).exists():
                system = Path(cand)
                break
        combined = ROOT / "certs" / "combined-ca.pem"
        blob = b""
        if system:
            blob += system.read_bytes() + b"\n"
        blob += Path(extra).read_bytes() + b"\n"
        combined.parent.mkdir(parents=True, exist_ok=True)
        combined.write_bytes(blob)
        os.environ["SSL_CERT_FILE"] = str(combined)
        os.environ.setdefault("REQUESTS_CA_BUNDLE", str(combined))
    except OSError:
        pass


def flatten_skills(profile: dict) -> list:
    skills = profile.get("skills", {}) or {}
    out = []
    for vals in skills.values():
        out.extend(str(v) for v in (vals or []))
    return out


def extract_keywords_from_text(jd_text: str, profile: dict) -> dict:
    """Deterministic, truthful extraction: profile skills present in the JD text."""
    low = jd_text.lower()
    found = [skill for skill in flatten_skills(profile) if skill.lower() in low]
    return {"keywords": sorted(set(found), key=str.lower)}


class PipelineError(RuntimeError):
    """User-facing error (bad input, missing profile, etc.)."""


def have_pdftotext() -> bool:
    return shutil.which("pdftotext") is not None


def extract_pdf_text(pdf_bytes: bytes) -> str:
    """Extract text from a PDF using poppler's pdftotext (-layout preserves order)."""
    if not have_pdftotext():
        raise PipelineError(
            "pdftotext not found (install poppler-utils) - cannot read PDF resumes. "
            "Paste the resume text instead, or install via: sudo apt-get install -y poppler-utils"
        )
    with tempfile.TemporaryDirectory() as td:
        pdf_path = Path(td) / "resume.pdf"
        pdf_path.write_bytes(pdf_bytes)
        res = subprocess.run(
            ["pdftotext", "-layout", str(pdf_path), "-"],
            capture_output=True, text=True,
        )
        if res.returncode != 0:
            raise PipelineError(f"Failed to read PDF: {res.stderr.strip() or 'pdftotext error'}")
        text = res.stdout.strip()
    if not text:
        raise PipelineError("The PDF appears to contain no extractable text (is it a scan/image?).")
    return text


def _try_profile_json(text: str) -> Optional[dict]:
    """Return a parsed profile dict if text is a JSON object that looks like a profile."""
    if not text:
        return None
    s = text.strip()
    if not s.startswith("{"):
        return None
    try:
        obj = json.loads(s)
    except json.JSONDecodeError:
        return None
    if isinstance(obj, dict) and any(k in obj for k in PROFILE_HINT_KEYS):
        return obj
    return None


def profile_to_text(profile: dict) -> str:
    """A stable, human-readable rendering of a profile for diffing (density-agnostic).

    Lists contact, education, skills, experience, and projects with their bullets in
    a fixed order so a unified diff shows exactly which resume content changed.
    """
    if not isinstance(profile, dict):
        return ""
    lines = []
    c = profile.get("contact") or {}
    if isinstance(c, dict) and c.get("name"):
        lines.append(f"# {c.get('name','')}")
    for edu in profile.get("education") or []:
        if isinstance(edu, dict):
            lines.append(f"[Education] {edu.get('institution','')} - {edu.get('degree','')}"
                         f" ({edu.get('dates','')})")
    skills = profile.get("skills") or {}
    if isinstance(skills, dict):
        for cat, vals in skills.items():
            vals = vals if isinstance(vals, (list, tuple)) else [vals]
            lines.append(f"[Skills] {cat}: {', '.join(str(v) for v in vals)}")
    for exp in profile.get("experience") or []:
        if not isinstance(exp, dict):
            continue
        lines.append(f"[Experience] {exp.get('role','')} @ {exp.get('company','')}"
                     f" ({exp.get('dates','')})")
        for b in exp.get("bullets") or []:
            bt = b.get("text", "") if isinstance(b, dict) else b
            pin = " [pinned]" if isinstance(b, dict) and b.get("pinned") else ""
            lines.append(f"  - {bt}{pin}")
    for proj in profile.get("projects") or []:
        if not isinstance(proj, dict):
            continue
        tech = proj.get("tech") or []
        tech = ", ".join(tech) if isinstance(tech, (list, tuple)) else str(tech)
        lines.append(f"[Project] {proj.get('title','')} ({tech})")
        for b in proj.get("bullets") or []:
            bt = b.get("text", "") if isinstance(b, dict) else b
            pin = " [pinned]" if isinstance(b, dict) and b.get("pinned") else ""
            lines.append(f"  - {bt}{pin}")
    return "\n".join(lines)


def _profile_diff(old: Optional[dict], new: dict) -> str:
    """Unified diff of resume content between two profiles (empty if no change)."""
    import difflib
    old_text = profile_to_text(old) if old else ""
    new_text = profile_to_text(new)
    if old_text == new_text:
        return ""
    diff = difflib.unified_diff(
        old_text.splitlines(), new_text.splitlines(),
        fromfile="previous", tofile="current", lineterm="",
    )
    return "\n".join(diff)


@dataclass
class GenerateResult:
    tex: str
    pdf_path: Optional[Path] = None
    pages: Optional[int] = None
    used_llm: bool = False
    deterministic: bool = False
    font_pt: int = 11
    textheight_extra: float = 1.0
    textwidth_extra: float = 1.0
    hit_floor: bool = False
    profile_source: str = "stored"   # "provided" | "parsed" | "stored" | "optimized"
    keyword_count: int = 0
    context_used: bool = False
    gaps: list = field(default_factory=list)
    summary: str = ""
    notes_saved: bool = False
    diff: str = ""            # unified diff of resume content vs the previous draft
    changed: bool = False     # whether this run changed the resume content
    warnings: list = field(default_factory=list)


@dataclass
class CompileResult:
    tex: str
    pdf_path: Optional[Path] = None
    pages: Optional[int] = None
    warnings: list = field(default_factory=list)


@dataclass
class AtsifyResult:
    tex: str
    pdf_path: Optional[Path] = None
    pages: Optional[int] = None
    profile_name: str = ""
    hit_floor: bool = False
    warnings: list = field(default_factory=list)


def atsify(
    *,
    source_text: str = "",
    resume_pdf_bytes: Optional[bytes] = None,
    model: Optional[str] = None,
    api_key: Optional[str] = None,
    base_url: Optional[str] = None,
    auth_style: Optional[str] = None,
    do_compile: bool = True,
    out_path: Path = DEFAULT_OUT,
) -> AtsifyResult:
    """Strip an arbitrary resume down to the ATS-friendly, one-page layout.

    Accepts a PDF (bytes), plain text, LaTeX source, or a profile JSON. The content
    is faithfully extracted into the structured schema (no tailoring, no fabrication),
    then rendered in the ATS-clean template and auto-fit to one page. This is a
    standalone conversion: it does NOT read or modify your saved profile.
    """
    load_dotenv()
    out_path = Path(out_path)
    model = model or os.environ.get("ANTHROPIC_MODEL") or llm.DEFAULT_MODEL

    profile = None
    raw_parts = []
    if resume_pdf_bytes:
        raw_parts.append(extract_pdf_text(resume_pdf_bytes))
    if source_text and source_text.strip():
        as_json = _try_profile_json(source_text)
        if as_json is not None:
            profile = as_json                    # already-structured profile JSON
        else:
            raw_parts.append(source_text.strip())  # plain text or LaTeX source
    raw = "\n\n".join(p for p in raw_parts if p).strip()

    if profile is None:
        if not raw:
            raise PipelineError(
                "No resume content provided. Upload a PDF, or paste resume text or LaTeX."
            )
        # extract_profile is faithful (no embellishment) and ignores LaTeX markup.
        profile = llm.extract_profile(
            raw, api_key=api_key, model=model, base_url=base_url, auth_style=auth_style,
        )
    if not isinstance(profile, dict):
        raise PipelineError("Could not parse a resume structure from the input.")

    contact = profile.get("contact") or {}
    result = AtsifyResult(tex="", profile_name=str(contact.get("name", "")).strip()
                          if isinstance(contact, dict) else "")
    out_path.parent.mkdir(parents=True, exist_ok=True)

    if not do_compile:
        result.tex = build_document(profile, {}, Density())
        out_path.write_text(result.tex, encoding="utf-8")
        return result

    if not texc.have_pdflatex():
        raise PipelineError("pdflatex not found. Install TeX Live in WSL (see README).")
    workdir = out_path.parent / "_build"
    tex, pdf, density, pages, hit_floor = texc.fit_one_page(profile, {}, workdir)
    out_path.write_text(tex, encoding="utf-8")
    final_pdf = out_path.with_suffix(".pdf")
    shutil.copyfile(pdf, final_pdf)
    result.tex, result.pdf_path, result.pages, result.hit_floor = tex, final_pdf, pages, hit_floor
    if hit_floor and pages != 1:
        result.warnings.append(
            f"Could not reach one page without crossing ATS-safety floors; stopped at {pages} pages."
        )
    return result


def compile_from_tex(
    tex: str,
    *,
    out_path: Path = DEFAULT_OUT,
) -> CompileResult:
    """Compile user-supplied LaTeX to PDF (no LLM, no profile rebuild).

    Saves the .tex and .pdf under ``out_path`` (same paths as ``generate()``).
    """
    tex = (tex or "").strip()
    if not tex:
        raise PipelineError("LaTeX source is empty.")
    if r"\documentclass" not in tex or r"\begin{document}" not in tex:
        raise PipelineError(
            "LaTeX must include \\documentclass and \\begin{document} ... \\end{document}."
        )
    if not texc.have_pdflatex():
        raise PipelineError(
            "pdflatex not found. Install TeX Live in WSL (see README)."
        )

    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    workdir = out_path.parent / "_build"
    try:
        pdf = texc.compile_tex(tex, workdir)
    except CompileError:
        raise

    pages = texc.page_count(pdf)
    out_path.write_text(tex, encoding="utf-8")
    final_pdf = out_path.with_suffix(".pdf")
    shutil.copyfile(pdf, final_pdf)

    warnings = []
    if pages is None:
        warnings.append("Could not determine page count.")
    elif pages > 1:
        warnings.append(
            f"PDF is {pages} pages. One page is recommended for ATS; trim content or "
            "tighten spacing in the LaTeX."
        )
    return CompileResult(tex=tex, pdf_path=final_pdf, pages=pages, warnings=warnings)


def generate(
    *,
    jd_text: str = "",
    keywords=None,
    profile: Optional[dict] = None,
    source_text: str = "",
    resume_pdf_bytes: Optional[bytes] = None,
    notes: str = "",
    instructions: str = "",
    fresh_pass: bool = False,
    bold: bool = False,
    bold_spec: str = "",
    save_profile: bool = True,
    deterministic: bool = False,
    model: Optional[str] = None,
    api_key: Optional[str] = None,
    base_url: Optional[str] = None,
    auth_style: Optional[str] = None,
    do_compile: bool = True,
    out_path: Path = DEFAULT_OUT,
    store_path: Path = None,        # resolves to the active user's store (per-user)
    optimized_path: Path = None,
    context_path: Path = None,
) -> GenerateResult:
    """Generate (and optionally compile) a tailored resume. See module docstring.

    Inputs for the profile/context (any combination):
      - ``profile``: a structured profile dict.
      - ``source_text``: pasted resume text or a profile JSON string. This (re)builds
        the structured profile.
      - ``resume_pdf_bytes``: a PDF resume (parsed with pdftotext). This (re)builds
        the structured profile.
      - ``notes``: incremental, truthful info the candidate is adding (e.g. to close
        coverage gaps). Notes do NOT rebuild the profile; they are appended to the
        stored grounding context and fed to the optimizer. This makes the gap-filling
        loop repeatable: add notes -> regenerate -> gaps shrink.
    Free text / PDF is parsed into the structured schema by the LLM, and the full
    raw text is also passed to the optimizer as additional grounding context.
    """
    load_dotenv()
    out_path = Path(out_path)
    result = GenerateResult(tex="")
    model = model or os.environ.get("ANTHROPIC_MODEL") or llm.DEFAULT_MODEL

    # 1. Gather raw source material (PDF text + pasted text/notes).
    raw_parts = []
    if resume_pdf_bytes:
        raw_parts.append(extract_pdf_text(resume_pdf_bytes))
    if source_text and source_text.strip():
        # A pasted structured profile JSON is treated as the profile, not as context.
        as_json = _try_profile_json(source_text)
        if as_json is not None and profile is None:
            profile = as_json
        else:
            raw_parts.append(source_text.strip())
    raw_context = "\n\n".join(p for p in raw_parts if p).strip()

    # 2. Resolve the structured profile.
    if profile is not None:
        if not isinstance(profile, dict):
            raise PipelineError("Profile must be a JSON object.")
        result.profile_source = "provided"
    elif raw_context:
        if deterministic:
            raise PipelineError(
                "Parsing free text or a PDF into a profile requires the LLM. "
                "Turn off Offline mode, or paste a structured profile JSON."
            )
        profile = llm.extract_profile(
            raw_context, api_key=api_key, model=model,
            base_url=base_url, auth_style=auth_style,
        )
        result.profile_source = "parsed"
    else:
        profile = store.load_profile(store_path)
        if profile is None:
            raise PipelineError(
                "No profile provided and none stored. Paste your resume text, upload a "
                "PDF, or paste a profile JSON to seed it."
            )
        result.profile_source = "stored"

    # 3. Persist base profile and context for future runs.
    profile_rebuilt = result.profile_source in ("provided", "parsed")
    if save_profile and profile_rebuilt:
        store.save_profile(profile, store_path)
        store.archive_profile(profile, source=result.profile_source)  # keep history
        store.clear_optimized(optimized_path)  # new resume -> discard prior draft
        if raw_context:
            store.save_context(raw_context, context_path)

    # 3b. Incremental notes augment (and, if saving, persist) the grounding context.
    #     This is the repeatable gap-filling loop: each note is remembered.
    notes = (notes or "").strip()
    if notes and save_profile:
        store.append_context(notes, context_path)
        result.notes_saved = True

    # Effective context for the optimizer.
    if result.notes_saved:
        # Persistence is the source of truth (already includes any just-saved resume
        # text and the appended notes).
        effective_context = store.load_context(context_path)
    else:
        parts = [raw_context or store.load_context(context_path)]
        if notes:
            parts.append(notes)  # used this run but not persisted (save_profile off)
        effective_context = "\n\n".join(p.strip() for p in parts if p and p.strip())

    # 4. Choose optimizer input: last optimized draft (iteration) or base profile.
    #    A "fresh pass" deliberately ignores the converged draft and re-optimizes
    #    from the base profile (+ context), which breaks out of iteration convergence.
    optimizer_input = profile
    is_iteration = False
    if not fresh_pass and not profile_rebuilt and not resume_pdf_bytes and not raw_context:
        prev = store.load_optimized(optimized_path)
        if prev:
            optimizer_input = prev
            is_iteration = True
            result.profile_source = "optimized"

    # 5. Tailoring.
    if deterministic:
        result.deterministic = True
        if keywords is not None:
            weights = tailor.normalize_keywords(keywords)
        elif jd_text.strip():
            weights = tailor.normalize_keywords(extract_keywords_from_text(jd_text, profile))
        else:
            weights = {}
        result.keyword_count = len(weights)
    else:
        job_description = jd_text or ""
        if not job_description.strip() and keywords is not None:
            job_description = "Target keywords / requirements:\n" + json.dumps(keywords, indent=2)
        if not job_description.strip():
            raise PipelineError("A job description is required for LLM optimization.")
        prev_optimized = store.load_optimized(optimized_path)  # for the change diff
        profile, gaps, summary = llm.optimize_profile(
            optimizer_input, job_description, api_key=api_key, model=model,
            base_url=base_url, auth_style=auth_style, extra_context=effective_context,
            is_iteration=is_iteration, new_notes=notes, instructions=(instructions or "").strip(),
            bold=bold, bold_spec=(bold_spec or "").strip(),
        )
        result.used_llm = True
        result.context_used = bool(effective_context.strip())
        result.gaps = gaps
        result.summary = summary
        # Diff this draft against the previous one so the UI can show what changed.
        # Only meaningful on an iteration (there is a prior draft to compare to).
        if prev_optimized:
            result.diff = _profile_diff(prev_optimized, profile)
            result.changed = bool(result.diff)
        if save_profile:
            store.save_optimized(profile, optimized_path)
        weights = {}

    out_path.parent.mkdir(parents=True, exist_ok=True)

    # 6a. .tex only.
    if not do_compile:
        result.tex = build_document(profile, weights, Density())
        out_path.write_text(result.tex, encoding="utf-8")
        return result

    # 6b. Compile + one-page auto-fit.
    if not texc.have_pdflatex():
        raise PipelineError(
            "pdflatex not found. Install TeX Live in WSL (see README) or use the "
            ".tex-only option."
        )
    workdir = out_path.parent / "_build"
    tex, pdf, density, pages, hit_floor = texc.fit_one_page(profile, weights, workdir)
    out_path.write_text(tex, encoding="utf-8")
    final_pdf = out_path.with_suffix(".pdf")
    shutil.copyfile(pdf, final_pdf)

    result.tex = tex
    result.pdf_path = final_pdf
    result.pages = pages
    result.font_pt = density.font_pt
    result.textheight_extra = density.textheight_extra
    result.textwidth_extra = density.textwidth_extra
    result.hit_floor = hit_floor
    if hit_floor and pages != 1:
        result.warnings.append(
            f"Could not reach one page without crossing ATS-safety floors; "
            f"stopped at {pages} pages."
        )
    return result
