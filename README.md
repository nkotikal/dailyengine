# Resume LaTeX Pipeline + Daily Digest

Two independent tools served from one local app (switch with the tabs at the top):

1. **ResumeForge** — maps a JSON user profile and a target job description into a
   clean, compilation-ready LaTeX resume using the Jake Gutierrez (`sb2nov`-derived)
   template. By default, **Claude (Anthropic) is the optimizer** and the result is
   rendered deterministically and auto-fit to a single page.
2. **Daily Digest** — feed it info about yourself, your goals, and your daily tasks,
   log updates as they happen, and it emails you a compartmentalized morning digest
   of what's new and what to do today. See [Daily Digest](#daily-digest) below.

The Daily Digest is fully isolated in `digest_pipeline/` and `web/digest.{css,js}`;
it shares only the `.env` (LLM gateway) and the local server process.

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
python3 server.py            # then open http://127.0.0.1:8765
```

It reads the same `.env` (key, gateway, model), auto-detects whether a profile is
stored, runs the LLM optimization (or offline mode via the toggle), compiles to a
single page, and previews the PDF inline. Stdlib-only (no web framework). Use the
tabs at the top to switch between **Resume** and **Daily Digest**.

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

## Daily Digest

A separate engine (open the **Daily Digest** tab) that emails you a
compartmentalized morning digest of what's new and what to do today.

**What you give it** (saved and reused every morning):
- **About you** — role, context, working style.
- **Goals** — longer-term objectives.
- **Recurring / standing tasks** — what you do daily/weekly.
- **Updates** — short notes you log as things happen. Each digest summarizes these
  into a "What's New" section and then clears them, so tomorrow only shows new ones.

**What it produces:** a clean, sectioned digest (Today's Focus, Tasks, What's New,
Goal Progress, Reminders) rendered as an HTML email, composed by the LLM (or a plain
deterministic layout in **Offline mode** / when no key is set).

**Delivery:** set a recipient and send time in the UI, flip on **Morning auto-send**,
and a background scheduler emails it each morning *while the server is running* (it
catches up if the machine was asleep at the exact time, as long as the server is up
later that morning). Use **Preview digest** to see it, or **Send now** to test.

**Email setup** (one time, in `.env` — secrets stay out of the UI):

```bash
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USER=you@gmail.com
SMTP_PASSWORD=your-app-password     # Gmail: an App Password, not your login
SMTP_FROM=you@gmail.com
SMTP_SECURITY=starttls              # starttls (default) | ssl | none
```

### Modules

- **Schedule → Calendar.** Paste your planner (numbers = hours, e.g. `11` = 11 AM;
  tabbed lines = tasks/subtasks; a leading `'` marks important). It's parsed into a
  time-blocked day (no information loss — every task/subtask is preserved in the
  digest) and can be **pushed to Google Calendar**. The calendar account is set via
  `GOOGLE_*` env vars and is switchable any time.
- **Trackers** (add as many as you like, any time):
  - `github` — new issues/PRs in a repo (optional `GITHUB_TOKEN`).
  - `web` — watch a page/careers site for keywords (e.g. NVIDIA + `intern`) or any change.
  - `inbox` — recent/unread emails via IMAP (`IMAP_*`).
  New findings appear in the digest's "What's New" and only NEW items are reported.
- **Korean practice.** A daily TOPIK lesson (vocab + grammar) at your level; past
  entries are saved so content never repeats.

### Memory (the "Memory" tab)

A persistent, editable store of long-term context about you that personalizes every
digest. It grows over time and is fully under your control:

- **Upload a resume** (PDF or text) — durable facts (role, education, skills,
  projects, achievements) are distilled into individual memories.
- **Natural language** — "I switched teams to X", "remember I prefer morning
  deep-work", "forget the bit about Y". An LLM turns it into precise add/update/remove
  operations on your memory list.
- **Direct editing** — double-click a memory to edit, click its category to change
  it, or delete it. Filter by category.

Memories are stored in `data/digest/memory.json` and fed to the digest composer as
long-term context.

### Google Calendar (optional, account-switchable)

Add OAuth creds to `.env` (works with any Google account; change these to switch
accounts — no code change):

```bash
GOOGLE_CLIENT_ID=...
GOOGLE_CLIENT_SECRET=...
GOOGLE_REFRESH_TOKEN=...           # one-time consent (e.g. OAuth Playground)
GOOGLE_CALENDAR_ID=primary
GOOGLE_TIMEZONE=America/New_York
```

### Choosing the model

Both the resume tab and the digest use the Anthropic Messages API via the gateway
in `.env` (`ANTHROPIC_BASE_URL`), defaulting to `claude-opus-4-8`. Override globally
with `ANTHROPIC_MODEL`, or per run via the Model dropdown in each tab. (Non-Anthropic
models like GPT require an OpenAI-compatible endpoint — see notes.)

Data is stored under `data/digest/` (config, updates, schedule, korean history,
trackers, run state), fully separate from the resume pipeline's files.

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
