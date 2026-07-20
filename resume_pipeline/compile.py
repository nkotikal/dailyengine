"""pdflatex compilation, page counting, and the ATS-safe one-page shrink loop."""

import re
import shutil
import subprocess
from pathlib import Path

from .template import Density, build_document


class CompileError(RuntimeError):
    pass


def have_pdflatex() -> bool:
    return shutil.which("pdflatex") is not None


def have_pdfinfo() -> bool:
    return shutil.which("pdfinfo") is not None


def compile_tex(tex_str: str, workdir: Path, jobname: str = "resume"):
    workdir = Path(workdir)
    workdir.mkdir(parents=True, exist_ok=True)
    tex_path = workdir / f"{jobname}.tex"
    tex_path.write_text(tex_str, encoding="utf-8")
    cmd = [
        "pdflatex",
        "-interaction=nonstopmode",
        "-halt-on-error",
        f"-jobname={jobname}",
        str(tex_path),
    ]
    res = subprocess.run(cmd, cwd=str(workdir), capture_output=True, text=True)
    pdf = workdir / f"{jobname}.pdf"
    if not pdf.exists():
        log_path = workdir / f"{jobname}.log"
        log_tail = ""
        if log_path.exists():
            log_tail = "\n".join(
                log_path.read_text(encoding="utf-8", errors="replace").splitlines()[-60:]
            )
        if not log_tail:
            log_tail = "\n".join((res.stdout + res.stderr).splitlines()[-40:])
        raise CompileError(
            "pdflatex did not produce a PDF.\n--- log tail ---\n" + log_tail
        )
    return pdf


def page_count(pdf: Path):
    if have_pdfinfo():
        out = subprocess.run(["pdfinfo", str(pdf)], capture_output=True, text=True)
        m = re.search(r"^Pages:\s+(\d+)", out.stdout, re.M)
        if m:
            return int(m.group(1))
    # Fallback: count /Type /Page objects in the raw PDF.
    data = Path(pdf).read_bytes()
    pages = len(re.findall(rb"/Type\s*/Page[^s]", data))
    return pages or None


def density_ladder(profile: dict):
    """Escalating, ATS-safe layout configs (least to most aggressive).

    Floors that protect ATS/readability are never crossed: font stays >= 10pt,
    the most-recent role keeps >= 2 bullets, older roles/projects keep >= 1.
    """
    n_exp = len(profile.get("experience", []) or [])
    n_proj = len(profile.get("projects", []) or [])
    # From step 1 on, the optional summary is dropped FIRST (before trimming any real
    # bullets), so an opt-in summary never pushes actual experience off the page.
    ladder = [
        # 0: baseline template, untouched (summary kept if present).
        Density(),
        # 1: a little extra vertical room; drop the optional summary.
        Density(textheight_extra=1.3, keep_summary=False),
        # 2: more vertical room + slightly tighter list spacing.
        Density(textheight_extra=1.4, keep_summary=False,
                listend_vspace=-6, sub_trail_vspace=-8),
        # 3: trim weakest bullets on older roles / projects.
        Density(textheight_extra=1.4, keep_summary=False, keep_older=3, keep_project=3,
                listend_vspace=-6, sub_trail_vspace=-8),
        # 4: wider lines (fewer wraps) + tighter spacing.
        Density(textheight_extra=1.5, textwidth_extra=1.2, keep_summary=False,
                keep_older=3, keep_project=3,
                listend_vspace=-6, sub_trail_vspace=-8, item_vspace=-3),
        # 5: trim recent role too.
        Density(textheight_extra=1.5, textwidth_extra=1.2, keep_summary=False,
                keep_recent=4, keep_older=2,
                keep_project=2, listend_vspace=-6, sub_trail_vspace=-8, item_vspace=-3),
        # 6: drop to 10pt (last typographic resort, still ATS-readable).
        Density(font_pt=10, textheight_extra=1.5, textwidth_extra=1.2, keep_summary=False,
                keep_recent=4, keep_older=2, keep_project=2, listend_vspace=-6,
                sub_trail_vspace=-8, item_vspace=-3),
        # 7: 10pt + hard floors.
        Density(font_pt=10, textheight_extra=1.5, textwidth_extra=1.2, keep_summary=False,
                keep_recent=3, keep_older=2, keep_project=1, listend_vspace=-6,
                sub_trail_vspace=-8, item_vspace=-3),
    ]
    # If there is little content, the later aggressive steps are irrelevant but
    # harmless; keep the full ladder for determinism regardless of n_exp/n_proj.
    _ = (n_exp, n_proj)
    return ladder


def fit_one_page(profile: dict, weights: dict, workdir: Path, on_attempt=None):
    """Compile escalating configs until the PDF is exactly one page.

    Returns (tex_str, pdf_path, density, pages, hit_floor). ``hit_floor`` is True
    when the ladder was exhausted without reaching one page (smallest ATS-safe
    config is returned).

    ``on_attempt(done, total)`` (optional) is called before each compile and once
    at the end, giving an accurate progress signal for the fit loop.
    """
    ladder = density_ladder(profile)
    total = len(ladder)
    last = None
    for i, density in enumerate(ladder):
        if on_attempt:
            on_attempt(i, total)
        tex = build_document(profile, weights, density)
        pdf = compile_tex(tex, workdir)
        pages = page_count(pdf)
        last = (tex, pdf, density, pages)
        if pages == 1:
            if on_attempt:
                on_attempt(total, total)
            return (*last, False)
    if on_attempt:
        on_attempt(total, total)
    return (*last, True)
