# Resume LaTeX Pipeline

A pipeline that maps a JSON user profile and a target job description into a
clean, compilation-ready LaTeX resume using the Jake Gutierrez (`sb2nov`-derived)
template. By default, **Claude (Anthropic) is the optimizer** -- it tailors the
resume to the job to maximize interview odds -- and the result is rendered
deterministically and auto-fit to a single page. A fully deterministic mode (no
LLM) is also available.

## How it works

```
profile.json + job description
        |
        v
  [LLM optimize]  (Claude, default)   <-- rewrites/reorders/selects, truthfully
        |  (optimized profile JSON, same schema)
        v
  [deterministic render]  escaping + exact template
        |
        v
  [one-page auto-fit]  pdflatex + pdfinfo
        |
        v
   output/resume.tex + output/resume.pdf
```

In `--deterministic` mode the LLM step is replaced by keyword scoring/ordering.

## Highlights

- **LLM optimization (default).** Claude rewrites, reorders, and selects content
  against the job description for ATS, recruiter, and hiring-manager appeal, and
  returns an optimized profile in the same JSON schema. Truthful by instruction:
  it may rephrase boldly and surface genuinely implied skills, but does not
  invent employers, titles, dates, degrees, or metrics. Runs at `temperature=0`.
- **Strict template fidelity.** The baseline preamble, custom macros, and
  `\titleformat`/`\addtolength` definitions are reproduced exactly. No new LaTeX
  packages are introduced.
- **Deterministic rendering.** Whatever profile is rendered (LLM-optimized or
  raw) maps directly to `\resumeSubheading`, `\resumeProjectHeading`, and
  `\resumeItem` macros.
- **Full LaTeX escaping.** `% & _ $ #` (plus `{ } ~ ^ \ < >`) are escaped in
  every field to avoid compiler panics and glyph errors.
- **Deterministic mode.** With `--deterministic`, job-description keywords
  re-order skills and bullets by relevance and trim the weakest content when
  space is tight. No API key needed.
- **Stored profile.** Your profile is saved after the first run, so future runs
  only need the job description.
- **One-page auto-fit.** Compiles with `pdflatex` and escalates an ATS-safe
  ladder (extra vertical room -> mild spacing -> wider lines -> content trim ->
  10pt) until the PDF is exactly one page. It never goes below 10pt or below the
  bullet floors that keep the resume readable and parseable.

## The resume manifesto

[`RESUME_MANIFESTO.md`](RESUME_MANIFESTO.md) is a reference standard for what
makes a resume pass every gate -- ATS parsers, the recruiter 6-second scan, and
deep technical hiring managers. It synthesizes Google's XYZ bullet formula
(Laszlo Bock), NVIDIA recruiting guidance (Workday ATS, domain-depth, measurable
outcomes), and 2026 ATS/recruiter best practices. It is **auto-loaded and
injected into the LLM optimizer's system prompt on every generation**, so Claude
applies these principles when rewriting/ordering/selecting content. Edit the file
to tune the optimization philosophy; no code changes needed.

## LLM configuration

- Provide your key one of three ways (checked in this order of precedence):
  1. `--api-key sk-ant-...` flag
  2. `ANTHROPIC_API_KEY` environment variable
  3. a `.env` file in the project root (auto-loaded)
- `.env` setup: `cp .env.example .env`, then put your key in it. `.env` is
  gitignored. Real environment variables override `.env` values.

```
# .env
ANTHROPIC_API_KEY=sk-ant-...
# optional:
ANTHROPIC_MODEL=claude-sonnet-4-6
```

- Default model: `claude-opus-4-8`. Override with `--model claude-sonnet-4-6`
  (faster/cheaper), the `ANTHROPIC_MODEL` env/.env value, or any current id.
- LLM mode is **required** by default: without a key it errors. Use
  `--deterministic` to run fully offline.
- Uses the Anthropic Messages API via the Python standard library (no pip deps).

### Using an internal / corporate gateway

The client can target any Anthropic-compatible gateway instead of the public API:

- `--base-url` or `ANTHROPIC_BASE_URL` -- gateway base (no `/v1` suffix).
- `--auth-style` or `ANTHROPIC_AUTH_STYLE` -- `x-api-key` (default), `bearer`
  (`Authorization: Bearer <key>`), or `apim` (Azure API Management's
  `Ocp-Apim-Subscription-Key`, used by gateways fronted by Azure APIM).

Example `.env` for an Azure-APIM-fronted Anthropic gateway:

```
ANTHROPIC_API_KEY=<your-subscription-key>
ANTHROPIC_BASE_URL=https://your-llm-gateway.example.com/Anthropic
ANTHROPIC_AUTH_STYLE=apim
```

The request is sent to `<base-url>/v1/messages`.

## Requirements

- Run inside WSL (Ubuntu). Python 3.x (standard library only).
- One-time system install for compilation:

```bash
sudo apt-get update
sudo apt-get install -y \
  texlive-latex-base texlive-latex-recommended texlive-latex-extra \
  texlive-fonts-recommended texlive-fonts-extra poppler-utils
```

`texlive-*` supplies `pdflatex` and every package the template uses;
`poppler-utils` supplies `pdfinfo` for page counting. (Without `pdfinfo`, the
pipeline falls back to parsing the PDF directly.)

## Web UI (liquid glass)

A local web app with an Apple-style liquid-glass interface: an optional
profile/context area (required only on the first run, when no profile is stored)
and a job-description field, with a live one-page PDF preview and downloads.

```bash
python3 server.py            # then open http://127.0.0.1:8000
```

It reads the same `.env` (key, gateway, model), auto-detects whether a profile is
stored, runs the LLM optimization (or offline mode via the toggle), compiles to a
single page, and previews the PDF inline. Stdlib-only (no web framework).

The Context area accepts any of: a **PDF resume** (uploaded), **plain resume
text**, free-form **notes**, or a **profile JSON**. Free text / PDFs are parsed by
the LLM into the structured profile, and your full original resume text is also
passed to the optimizer as grounding context. The parsed profile and context are
saved, so later runs need only a job description.

### Coverage gaps (repeatable loop)

Each AI run also returns a ranked list of **coverage gaps** — job-description
requirements the optimizer could not *truthfully* fit into your resume — each with
an importance score (0–100%), why it matters, and a suggestion. In the UI these
appear in a **Coverage gaps** panel with a per-gap input; on the CLI they print
under `[gaps]`.

If a gap actually applies to you, add the real details (per-gap inputs or
`--notes "..."`). Those notes are **appended to your stored context** (not used to
rebuild the profile), so every regeneration has more truthful material to work with
and the gaps shrink. Repeat until the resume covers the role.

## Usage (CLI)

First run with LLM optimization (seed the stored profile, optimize, compile):

```bash
export ANTHROPIC_API_KEY=sk-ant-...
python3 generate_resume.py --profile samples/profile.sample.json \
  --jd-text samples/job_posting.sample.txt --compile
```

Seed from a PDF or plain-text resume (parsed into a profile by the LLM), with
optional extra notes given to the optimizer as context:

```bash
python3 generate_resume.py --resume path/to/my_resume.pdf --jd-text job.txt --compile
python3 generate_resume.py --resume resume.txt --notes "Targeting GPU/CUDA roles" --jd-text job.txt --compile
```

Future runs (reuse stored profile; supply only the job description):

```bash
python3 generate_resume.py --jd-text path/to/job_posting.txt --compile
python3 generate_resume.py --keywords path/to/keywords.json --compile
```

Regeneration continues from your **last optimized draft** (not the original
profile), so prior fixes are preserved. Each run also returns a short AI
**summary** of what changed.

Close coverage gaps reported by a previous run (notes are appended to your stored
context and reused on every later run, so gaps shrink each pass):

```bash
python3 generate_resume.py --jd-text job.txt --notes "Built a Kubernetes operator with kubebuilder + custom CRDs to automate failover." --compile
```

### Manual LaTeX edits

After generation, you can edit the `.tex` yourself and recompile without re-running the AI:

- **UI:** click **Edit LaTeX**, change the source, then **Recompile PDF**.
- **CLI:** `python3 generate_resume.py --compile-tex output/resume.tex`

The edited `.tex` and PDF are saved under `output/`. Compile errors include a log tail to help you fix syntax issues.

Deterministic mode (no LLM / no API key):

```bash
python3 generate_resume.py --jd-text samples/job_posting.sample.txt --deterministic --compile
```

Emit only the `.tex` (deterministic, no compilation needed):

```bash
python3 generate_resume.py --keywords samples/keywords.sample.json --deterministic --no-compile
```

Outputs land in `output/resume.tex` and `output/resume.pdf`.

## Input schemas

**Profile** (`--profile`):

```json
{
  "contact": { "name": "", "email": "", "phone": "", "linkedin": "", "github": "" },
  "education": [{ "institution": "", "location": "", "degree": "", "gpa": "", "dates": "" }],
  "skills": { "Languages": ["..."], "Frameworks": ["..."] },
  "experience": [{ "company": "", "location": "", "role": "", "dates": "", "bullets": ["..."] }],
  "projects": [{ "title": "", "tech": ["..."], "dates": "", "bullets": ["..."] }]
}
```

Common alternative field names are accepted (e.g. `school`/`university` for
`institution`, `title`/`position` for `role`, `points`/`highlights` for
`bullets`, `tech_stack`/`technologies` for `tech`).

Instead of structured JSON you can provide a **PDF resume** (`--resume file.pdf`,
read via `pdftotext`), **plain text** (`--resume file.txt`), or free-form
**notes** (`--notes "..."` or `--notes @file`). The LLM parses these into the
schema above (truthfully, no fabrication) and the raw text is stored as context
and re-supplied to the optimizer on each run. (Parsing free text/PDF requires the
LLM; it is not available in `--deterministic` mode.)

**Keywords** (`--keywords`): either a flat list or a weighted object.

```json
{ "required": ["Python", "AWS"], "preferred": ["Terraform", "Kafka"] }
```

```json
["Python", "AWS", "Kubernetes"]
```

`required` keywords are weighted higher than `preferred` when ranking content.

## How tailoring works

1. Keywords become weighted terms (`required` = 2.0, `preferred` = 1.0).
2. Each skill and bullet is scored by whole-word keyword matches (partial
   matches count for half).
3. Skill categories and the skills within them are re-ordered most-relevant
   first; bullets are ordered most-relevant first.
4. If the document spills onto a second page, the lowest-scoring bullets are
   trimmed (recent role keeps >= 2, older roles/projects keep >= 1) before any
   font reduction.

## ATS guardrails

Single column, standard section headings, selectable text with
`\pdfgentounicode=1`, no images/icons/multi-column/header-text, font never below
10pt, and contact details in the document body.

## Project layout

```
generate_resume.py          CLI entry point
server.py                   local web server for the liquid-glass UI (stdlib)
web/                        UI assets (index.html, styles.css, app.js)
resume_pipeline/
  core.py                   shared generate() used by CLI and server
  escaping.py               LaTeX special-char escaping
  store.py                  profile + context persistence (data/profile.json, data/context.txt)
  tailor.py                 keyword scoring + ordering/selection
  template.py               exact template + section renderers + density knobs
  llm.py                    Anthropic Messages API optimizer (stdlib urllib)
  compile.py                pdflatex + pdfinfo + one-page shrink ladder
RESUME_MANIFESTO.md         optimization principles injected into the LLM prompt
samples/                    example profile, keywords, raw job posting
output/                     generated resume.tex / resume.pdf
data/profile.json           stored profile (gitignored)
```
