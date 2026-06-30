#!/usr/bin/env python3
"""Resume LaTeX pipeline CLI.

By default Claude (Anthropic) acts as the optimizer: it rewrites/reorders/selects
the stored profile against the job description (truthfully), then the result is
rendered deterministically and auto-fit to one page. Requires ANTHROPIC_API_KEY
(or a gateway via ANTHROPIC_BASE_URL / --base-url).

Examples
--------
First run (saves the profile for reuse, LLM-optimizes, compiles, auto-fits):

    export ANTHROPIC_API_KEY=sk-ant-...
    python3 generate_resume.py --profile profile.json --jd-text job_posting.txt --compile

Future runs (reuse the stored profile, supply only the job description):

    python3 generate_resume.py --jd-text job_posting.txt --compile
    python3 generate_resume.py --keywords kw.json --compile

Deterministic mode (no LLM / no API key needed):

    python3 generate_resume.py --jd-text job_posting.txt --deterministic --compile

Emit only the .tex (no compilation):

    python3 generate_resume.py --jd-text job_posting.txt --deterministic --no-compile
"""

import argparse
import json
import os
import sys
from pathlib import Path

from resume_pipeline import core, llm, store
from resume_pipeline.compile import CompileError


def _load_json(path: str):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _print_gaps(gaps):
    """Print the ranked job-description requirements not covered by the resume."""
    if not gaps:
        if gaps is not None:
            print("[gaps] none - the resume covers the job description well.")
        return
    print(f"\n[gaps] {len(gaps)} job requirement(s) not fully covered, "
          "ranked by importance:")
    for g in gaps:
        bar_len = round(g["importance"] / 10)
        bar = "#" * bar_len + "-" * (10 - bar_len)
        print(f"  {g['importance']:3d}% [{bar}] {g['requirement']}")
        if g.get("reason"):
            print(f"        why: {g['reason']}")
        if g.get("suggestion"):
            print(f"        add: {g['suggestion']}")
    print("  -> Add any of these (truthfully) with --notes \"...\" and re-run to close them.")


def _print_summary(summary):
    if not summary:
        return
    print("\n[summary]")
    for line in summary.splitlines():
        print(f"  {line.strip()}")


def main(argv=None) -> int:
    core.load_dotenv()
    p = argparse.ArgumentParser(description="Generate a tailored one-page LaTeX resume.")
    p.add_argument("--profile", help="Path to a structured profile JSON. If omitted, the stored profile is reused.")
    p.add_argument("--resume", help="Path to a resume to ingest: .pdf, .txt, or .json (parsed into a profile by the LLM).")
    p.add_argument("--notes", help="Incremental truthful context to add (inline string, or @path to a file). "
                                   "Appended to stored context to close coverage gaps; does not rebuild the profile.")
    p.add_argument("--keywords", help="Path to job-description keyword JSON (list or {required,preferred}).")
    p.add_argument("--jd-text", dest="jd_text", help="Path to raw job-description text.")
    p.add_argument("--out", default=str(core.DEFAULT_OUT), help="Output .tex path (default: output/resume.tex).")
    p.add_argument("--compile-tex", dest="compile_tex",
                   help="Compile an existing .tex file to PDF (no LLM). Path to the .tex source.")
    p.add_argument("--store", dest="store_path", default=str(store.DEFAULT_STORE), help="Profile store location.")
    p.add_argument("--model", default=os.environ.get("ANTHROPIC_MODEL", llm.DEFAULT_MODEL),
                   help=f"Anthropic model id (default: $ANTHROPIC_MODEL or {llm.DEFAULT_MODEL}).")
    p.add_argument("--api-key", dest="api_key", help=f"API key (else read from ${llm.API_KEY_ENV}).")
    p.add_argument("--base-url", dest="base_url", default=os.environ.get(llm.BASE_URL_ENV),
                   help=f"Anthropic-compatible base URL for a gateway (else ${llm.BASE_URL_ENV}; "
                        f"default {llm.DEFAULT_BASE_URL}).")
    p.add_argument("--auth-style", dest="auth_style", choices=["x-api-key", "bearer", "apim"],
                   default=os.environ.get(llm.AUTH_STYLE_ENV),
                   help=f"Auth header style (else ${llm.AUTH_STYLE_ENV}; default x-api-key; "
                        f"apim = Azure 'Ocp-Apim-Subscription-Key').")
    p.add_argument("--deterministic", action="store_true", help="Skip the LLM; use deterministic keyword tailoring only.")
    compile_grp = p.add_mutually_exclusive_group()
    compile_grp.add_argument("--compile", dest="do_compile", action="store_true", help="Compile to PDF and auto-fit to one page.")
    compile_grp.add_argument("--no-compile", dest="do_compile", action="store_false", help="Emit .tex only.")
    p.set_defaults(do_compile=False)
    args = p.parse_args(argv)

    if args.compile_tex:
        try:
            tex = Path(args.compile_tex).read_text(encoding="utf-8")
            result = core.compile_from_tex(tex, out_path=Path(args.out))
        except CompileError as exc:
            print(f"[error] {exc}", file=sys.stderr)
            return 3
        except core.PipelineError as exc:
            print(f"[error] {exc}", file=sys.stderr)
            return 2
        print(f"[compile] pages={result.pages}")
        for w in result.warnings:
            print(f"[warn] {w}", file=sys.stderr)
        print(f"[done] wrote {args.out} and {result.pdf_path}")
        return 0

    profile = _load_json(args.profile) if args.profile else None
    keywords = _load_json(args.keywords) if args.keywords else None
    jd_text = Path(args.jd_text).read_text(encoding="utf-8") if args.jd_text else ""

    # --resume: .pdf -> bytes; .txt/.json/other -> source_text (core auto-detects JSON).
    resume_pdf_bytes = None
    source_text = ""
    if args.resume:
        rp = Path(args.resume)
        if rp.suffix.lower() == ".pdf":
            resume_pdf_bytes = rp.read_bytes()
        else:
            source_text = rp.read_text(encoding="utf-8")
    notes = ""
    if args.notes:
        notes = args.notes
        if notes.startswith("@"):
            notes = Path(notes[1:]).read_text(encoding="utf-8")

    if profile is not None:
        print(f"[profile] loaded from {args.profile}")
    if not args.deterministic:
        target = args.base_url or os.environ.get(llm.BASE_URL_ENV) or llm.DEFAULT_BASE_URL
        print(f"[llm] optimizing with {args.model} via {target} ...")

    try:
        result = core.generate(
            jd_text=jd_text,
            keywords=keywords,
            profile=profile,
            source_text=source_text,
            resume_pdf_bytes=resume_pdf_bytes,
            notes=notes,
            deterministic=args.deterministic,
            model=args.model,
            api_key=args.api_key,
            base_url=args.base_url,
            auth_style=args.auth_style,
            do_compile=args.do_compile,
            out_path=Path(args.out),
            store_path=Path(args.store_path),
        )
    except CompileError as exc:
        print(f"[error] {exc}", file=sys.stderr)
        return 3
    except core.PipelineError as exc:
        print(f"[error] {exc}", file=sys.stderr)
        return 2
    except llm.LLMError as exc:
        print(f"[error] {exc}", file=sys.stderr)
        return 4

    print(f"[profile] using {result.profile_source} profile"
          + (" (parsed from resume)" if result.profile_source == "parsed" else ""))
    if result.used_llm:
        print("[llm] received optimized profile"
              + (" (with full resume context)" if result.context_used else ""))
    elif result.deterministic:
        print(f"[deterministic] {result.keyword_count} keyword(s)")

    if result.notes_saved:
        print("[notes] saved to context for future runs")
    if result.profile_source == "optimized":
        print("[draft] continuing from your last optimized resume")
    _print_summary(result.summary)
    _print_gaps(result.gaps)

    if not args.do_compile:
        print(f"[done] wrote {args.out} (not compiled)")
        return 0

    knobs = (f"font={result.font_pt}pt, textheight+={result.textheight_extra}in, "
             f"textwidth+={result.textwidth_extra}in")
    print(f"[fit] pages={result.pages} ({knobs})")
    for w in result.warnings:
        print(f"[warn] {w}", file=sys.stderr)
    print(f"[done] wrote {args.out} and {result.pdf_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
