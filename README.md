# Daily Digest + Resume LaTeX Pipeline

Two independent tools served from one small, dependency-free local app (switch
with the tabs at the top of the UI):

1. **Daily Digest** — you tell it about yourself, your goals, your schedule, and
   your tasks; every morning it emails you a clean, sectioned briefing of what's
   new and what to do today. You can run the whole thing *by replying to the
   email* — no need to keep the UI open.
2. **ResumeForge** — maps a profile (JSON, plain text, or an uploaded PDF) and a
   target job description into a compilation-ready, ATS-friendly LaTeX resume,
   auto-fit to a single page.

Everything is Python **standard library only** — no `pip install` step. The only
moving parts are a `.env` file (your keys) and a local server process.

---

## Quick start (clone → running in ~10 min)

This is built to run on **Windows + WSL (Ubuntu)**. (It also runs on plain
Linux/macOS — only the Windows auto-start scripts in `tools/` are Windows-specific.)

### 1. Clone the repo (inside WSL)

```bash
git clone <your-repo-url> bldr
cd bldr
```

### 2. Install system packages (one time)

```bash
sudo apt-get update
# Python is usually already present; this makes sure:
sudo apt-get install -y python3
# Only needed for the RESUME tool (LaTeX compile + PDF text extraction):
sudo apt-get install -y \
  texlive-latex-base texlive-latex-recommended texlive-latex-extra \
  texlive-fonts-recommended texlive-fonts-extra poppler-utils
```

If you only want the Daily Digest, you can skip the `texlive-*` / `poppler-utils`
line.

### 3. Configure `.env`

```bash
cp .env.example .env
```

Then edit `.env` and set, at minimum:

- An **LLM key** so the digest/resume can be written by AI (see
  [LLM providers](#llm-providers) below). The simplest durable choice:

  ```
  OPENAI_API_KEY=sk-...
  ```

- **Email sending** (so the morning digest can actually be delivered). Gmail
  example — use an **App Password**, not your normal password:

  ```
  SMTP_HOST=smtp.gmail.com
  SMTP_PORT=587
  SMTP_USER=you@gmail.com
  SMTP_PASSWORD=your-16-char-app-password
  SMTP_FROM=you@gmail.com
  SMTP_SECURITY=starttls
  ```

  > Gmail App Password: enable 2-Step Verification, then create one at
  > Google Account → Security → App passwords. The same password also works for
  > the optional IMAP "inbox" tracker and for reading your email replies.

`.env` is gitignored — your keys never get committed.

### 4. Run the app

```bash
python3 server.py
```

Open **http://127.0.0.1:8765**. The landing tab is **Daily Digest**.

### 5. Set yourself up in the UI

In the **Daily Digest** tab: fill in *About you*, *Goals*, your *Schedule* and
*Tasks*, set the **recipient email** and **send time**, then click **Preview
digest** to see it and **Send now** to email a test.

That's the whole loop. To make it run **every morning by itself**, see
[Run it every morning automatically](#run-it-every-morning-automatically).

---

## LLM providers

The app writes your digest (and optimizes resumes) with an LLM. It supports two
backends plus an offline fallback, chosen automatically:

| Provider | When it's used | `.env` keys |
| --- | --- | --- |
| **OpenAI** (or any OpenAI-compatible endpoint) | The durable default. Used immediately if no Anthropic/AMD gateway is configured. | `OPENAI_API_KEY` (and optional `OPENAI_BASE_URL`) |
| **Anthropic / internal gateway** | Used first *if configured and reachable* (e.g. a corporate AMD gateway on VPN). | `ANTHROPIC_API_KEY`, optional `ANTHROPIC_BASE_URL`, `ANTHROPIC_AUTH_STYLE` |
| **Offline** | No key, or all gateways unreachable. Produces a plain deterministic layout. | none |

**Going forward, OpenAI is all you need.** If you don't set any
`ANTHROPIC_*` values, the app skips the gateway entirely and uses OpenAI right
away (no waiting). Pick a `gpt-*` model in the **Model** dropdown in either tab.

If you *do* have a reachable Anthropic-compatible gateway, it's tried first; if
it's down, the scheduled morning send waits up to 1h for it to come back, then
falls back to OpenAI, then to offline after 2h — so a flaky VPN never produces a
gutted digest.

```
# .env — minimal, OpenAI-only
OPENAI_API_KEY=sk-...
# optional: a non-OpenAI compatible endpoint
# OPENAI_BASE_URL=https://api.openai.com/v1
```

---

## Run it every morning automatically

Two tiny PowerShell installers register Windows Scheduled Tasks. They are
**self-locating** — run them from wherever you cloned the repo and they wire up
the correct paths automatically. Run them in **PowerShell** from the repo's
`tools` folder:

```powershell
# 1) Email the digest every day at 07:00 (this is the actual "cron").
powershell -ExecutionPolicy Bypass -File .\tools\install_email_task.ps1

# 2) (Optional) Keep the web UI running at logon, so you can open the dashboard
#    any time and so an in-app scheduler can catch up if a send was missed.
powershell -ExecutionPolicy Bypass -File .\tools\install_startup_task.ps1
```

Both run hidden via WSL (no console window). To change the send time, edit
`$time` in `install_email_task.ps1` and re-run it. To remove them:

```powershell
powershell -ExecutionPolicy Bypass -File .\tools\uninstall_email_task.ps1
powershell -ExecutionPolicy Bypass -File .\tools\uninstall_startup_task.ps1
```

Test a send immediately (bypasses the once-per-day guard):

```bash
python3 tools/send_digest.py --force
```

Logs land in `data/digest/send.log` and `data/digest/server.log`.

---

## Manage it by replying to the email

You don't have to open the UI day-to-day. Reply to the morning digest in plain
English and the next run applies it (this uses the IMAP creds in `.env`, e.g. the
same Gmail App Password):

- "Done: ship the API docs" → marks that task complete.
- "Add task: review Q3 budget, high priority, due Friday" → adds it.
- "I switched teams to Platform Infra" → updates your long-term memory.
- "More interested in GPU/CUDA news, less in crypto" → tunes news/interests.
- Reply with a Korean sentence → it gets graded in the next lesson.

Enable IMAP reading in `.env`:

```
IMAP_HOST=imap.gmail.com
IMAP_PORT=993
IMAP_USER=you@gmail.com
IMAP_PASSWORD=your-app-password
```

---

## Multiple users (compartmentalization)

The app supports multiple, fully isolated users on one machine — no profiles,
memories, tasks, schedules, reminders, trackers, Korean history, or settings ever
overlap. Use the **user picker in the top-right header** to switch, add, rename,
or delete a user. Each user's data lives in its own tree:

```
data/users/<id>/digest/...     daily-digest data
data/users/<id>/profile.json   resume profile (+ optimized.json, context.txt, profiles/)
data/users.json                registry (user list + active user)
```

- **Switching** changes whose data every tab shows; the page reloads to repopulate.
- **Email is per-user:** each user has their own recipient + send time, and the
  morning scheduler emails every auto-send-enabled user their own digest. Replies
  are matched per user, so everyone can manage their own digest by email.
- **Migration:** the first run on a pre-multi-user install automatically moves your
  existing data into a `default` user — nothing is lost.
- There's no database; it's plain JSON files, so backing up or moving a user is
  just copying their folder.

## Daily Digest features

**What you give it** (saved and reused every morning): *About you*, *Goals*,
*Schedule*, and *Tasks*. You also log short **Updates** as things happen; each
digest summarizes them into "What's New" and clears them.

**What it produces:** a sectioned HTML email — a daily motivational hook, Today's
Focus, Schedule, Weekly/Daily tasks (with nested subtasks, priorities, due dates,
time estimates, and triage), What's New, Reminders (deadline warnings), news
headlines filtered to your interests, Goal Progress (counts leaf tasks), and a
Korean lesson.

- **Priorities.** A leading `'` on a task = High; `'''` = **Critical** (weighted
  higher in triage and styled distinctly).
- **Schedule.** Paste a planner (numbers = hours, e.g. `11` = 11 AM; tabbed lines
  = subtasks). Optionally push to **Google Calendar** (see `.env` `GOOGLE_*`).
- **Trackers** (add any number, any time):
  - `github` — new issues/PRs in a repo (optional `GITHUB_TOKEN`).
  - `web` — watch a page for keywords or any change.
  - `inbox` — recent/unread email via IMAP.
  Only *new* findings are reported.
- **Korean practice.** A daily TOPIK-aligned lesson (vocab + grammar with example
  sentences/translations) at your level, with a weekly culture tidbit; reply with
  a sentence to get it graded. History is saved so content never repeats.
- **Memory** (the **Memory** tab). A persistent, editable store of long-term
  facts about you that personalizes every digest. Upload a resume to seed it,
  add/update/remove via natural language, or edit entries directly. It evolves and
  tail-compresses over time. Stored in `data/digest/memory.json`.

All digest data lives under `data/digest/`, fully separate from the resume tool.

---

## ResumeForge (the Resume tab)

Maps a profile + a job description into a single-page, ATS-friendly LaTeX resume
using the Jake Gutierrez (`sb2nov`-derived) template.

- **Input:** a **PDF resume** (uploaded), **plain resume text**, free-form
  **notes**, or a **profile JSON**. Free text/PDFs are parsed by the LLM into a
  structured profile (truthfully — no invented employers, titles, dates, or
  metrics). The parsed profile + raw text are stored, so later runs need only a
  job description.
- **Optimization:** the LLM rewrites/reorders/selects content for the target role
  at `temperature=0`, guided by [`RESUME_MANIFESTO.md`](RESUME_MANIFESTO.md)
  (auto-injected into the system prompt — edit it to tune the philosophy).
- **Coverage gaps:** each run returns ranked job requirements it couldn't
  *truthfully* fit, with importance scores and suggestions. Add the real details
  (per-gap inputs or `--notes`) and regenerate; gaps shrink each pass.
- **Rendering:** deterministic template fill + full LaTeX escaping, compiled with
  `pdflatex` and auto-fit to exactly one page (ATS-safe ladder; never below 10pt).
- **Manual edits:** click **Edit LaTeX** → **Recompile PDF**, or
  `python3 generate_resume.py --compile-tex output/resume.tex`.

### CLI examples

```bash
# First run: seed profile, optimize against a job, compile
python3 generate_resume.py --resume path/to/my_resume.pdf --jd-text job.txt --compile

# Later runs: reuse stored profile, supply only the job description
python3 generate_resume.py --jd-text job.txt --compile

# Close a coverage gap (notes are appended to stored context and reused)
python3 generate_resume.py --jd-text job.txt --notes "Built a Kubernetes operator with custom CRDs." --compile

# Fully offline (no LLM/key): keyword scoring + ordering
python3 generate_resume.py --jd-text job.txt --deterministic --compile
```

Outputs land in `output/resume.tex` and `output/resume.pdf`.

---

## Project layout

```
server.py                   local web server for the UI (stdlib)
generate_resume.py          resume CLI entry point
web/                        UI assets
  index.html, styles.css, app.js          shared shell + resume tab
  digest.css, digest.js                   daily digest + memory tabs
digest_pipeline/            Daily Digest engine (isolated)
  digest.py                 build/render the digest; provider tiering
  tasks.py                  weekly/daily nested tasks, triage, due dates
  memory.py                 evolving, tail-compressing long-term memory
  korean.py                 TOPIK lessons + graded practice
  news.py                   headline fetch + interest filtering
  inbox_commands.py         parse email replies into updates
  email_send.py             SMTP delivery
  gcal.py                   optional Google Calendar
  openai_compat.py          stdlib OpenAI chat client
  llm.py, store.py, scheduler.py
resume_pipeline/            Resume engine (isolated)
  core.py, llm.py, tailor.py, template.py, compile.py, escaping.py, store.py
tools/                      Windows auto-start + headless sender (self-locating)
  send_digest.py            headless "send today's digest" (used by Task Scheduler)
  install_email_task.ps1    register the 07:00 daily email task
  install_startup_task.ps1  register the at-logon UI server task
  uninstall_*.ps1           remove the tasks
  *.vbs, start_digest_server.sh   hidden WSL launchers
RESUME_MANIFESTO.md         resume optimization principles (injected into prompt)
samples/                    example profile, keywords, job posting
data/                       your stored data (gitignored): profile, digest/*
output/                     generated resume.tex / resume.pdf
.env.example                copy to .env and fill in keys
```

---

## Troubleshooting

- **No email arrives.** Check `data/digest/send.log`. Confirm `SMTP_*` in `.env`
  and that the recipient is set in the UI. With Gmail you must use an App Password.
- **Digest looks "gutted" / plain.** The LLM was unreachable and it fell back to
  offline mode. Set `OPENAI_API_KEY` and pick a `gpt-*` model.
- **Port already in use.** Another `server.py` is running. It binds `127.0.0.1:8765`.
- **Resume won't compile.** Install the `texlive-*` packages above; compile errors
  include a log tail to help locate the LaTeX issue.
- **Paste blocked in the editor's webview.** Open the UI in a real browser at
  http://127.0.0.1:8765.
