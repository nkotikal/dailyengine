# Project State — ResumeForge + Daily Digest (context distillation)

A local, stdlib-only Python app with a liquid-glass web UI. Two isolated features
share one server and one `.env`. Runs in **WSL (Ubuntu)**; Windows shell is PowerShell.
Workspace: `C:\Users\nkotikal\Desktop\bldr` (WSL: `/mnt/c/Users/nkotikal/Desktop/bldr`).

## How to run / automation
- Server: `python3 server.py` → **http://127.0.0.1:8765** (default port moved from 8000
  because the user's `client-perf-hub` project serves on 8000; server also auto-falls
  back to the next free port).
- Auto-start (Windows Task Scheduler, set up via `tools/`):
  - **DailyDigestServer** (at logon) → runs `tools/start_digest_hidden.vbs` → WSL →
    `tools/start_digest_server.sh` (self-restart loop, single-instance via pgrep).
  - **DailyDigestEmail** (daily 07:00, StartWhenAvailable catch-up) → `tools/send_digest_hidden.vbs`
    → WSL → `tools/send_digest.py` (headless one-shot send).
  - Installers: `tools/install_email_task.ps1`, `tools/install_startup_task.ps1` (+ uninstallers).
    The logon-trigger cmdlet needs elevation; scripts fall back to `schtasks`.
- Restart after Python changes: `wsl bash -lc "pkill -f '[s]erver.py'"` (loop relaunches),
  or it auto-restarts. Web (html/js/css) is served fresh — just hard-refresh.
- IMPORTANT shell gotcha: complex inline `python3 -c "..."` and quotes get mangled
  through PowerShell→WSL. Write a temp `.py`/`.sh` file and run it instead. `pkill -f server.py`
  can match its own shell — use the `[s]erver.py` bracket trick.

## LLM
- Anthropic Messages API via the **AMD internal gateway**: `.env` has
  `ANTHROPIC_API_KEY`, `ANTHROPIC_BASE_URL=https://llm-api.amd.com/Anthropic`,
  `ANTHROPIC_AUTH_STYLE=apim`. Default model **claude-opus-4-8**.
- GPT-5.4-mini: NOT reachable via this Anthropic-format gateway; would need an
  OpenAI-compatible client/endpoint (offered to add a `LLM_PROVIDER` switch; not built yet).

## Email
- Gmail SMTP in `.env`: `SMTP_HOST=smtp.gmail.com`, `SMTP_USER=dailyengine.updates@gmail.com`,
  app password set; `SMTP_FROM`, `SMTP_SECURITY=starttls`. Recipient: **nkotikalapudi@outlook.com**.
- IMAP (`IMAP_*`, same Gmail + app password) for reply parsing + inbox tracker.
- `Reply-To` set to the Gmail so replies route back. Deliverability to Outlook was
  flaky (junk) earlier but the user confirmed it now lands.

## Resume pipeline (`resume_pipeline/`, tab: Resume) — unchanged core
- LLM-optimizes a profile against a job description → renders Jake Gutierrez LaTeX →
  one-page auto-fit via pdflatex. Coverage-gaps loop, manual `.tex` edit/recompile,
  continues from last optimized draft. Files: core.py, llm.py, template.py, compile.py,
  tailor.py, escaping.py, store.py. Needs TeX Live + poppler in WSL.

## Daily Digest (`digest_pipeline/`, tabs: Daily Digest + Memory)
Data under `data/digest/` (JSON; separate from resume's `data/`).

### Modules
- **store.py** — config + all persistence. Cross-process `claim_send_slot(date)` (O_EXCL
  lock file) prevents the Windows task AND in-server scheduler from double-sending.
  `clear_category()` for per-category resets. Weekly tasks are a recursive tree
  (nodes: id, text, done, priority, due, est_minutes, subtasks[]; node-by-id add/update/delete).
  Memory items have importance + timestamps; `profile_base` stored in `profile_base.txt`
  (exempt from compression). Korean state holds curriculum progress/SRS/history/practice.
- **digest.py** — builds the report. Order (inverted pyramid):
  Today's Focus → **Reminders** → Headlines → (What's New) → Progress →
  This Week's Tasks → Korean Practice → **Schedule (dead last)**. `_finalize_sections`
  injects a complete Korean card above Schedule, attaches headline URLs, drops empty
  cards. `render_html` = colorful card email (per-section color themes, icon badges,
  gradient header, 16px+ fonts, "open ↗" headline links, reply-to footer). Detail
  sections are compact/tinted below a divider. **Routine section removed** per user.
- **llm.py** — `compose_digest` (creative-secretary voice, ~250-450 words, report not
  list-dump, emphasize '-prefixed priority tasks) + `post_json` shared JSON chat.
- **tasks.py** — weekly tasks: outline parse (tabs→nested subtasks, any depth), LLM
  derive from "Goals this week", triage (importance + earliest due across subtree +
  estimate), capacity/"focus load" vs `daily_capacity_hours`. Progress treats
  top-level entries as CATEGORIES; counts leaf tasks done.
- **schedule.py** — parse planner text (numbers=hours 11=11AM rolling to 12=midnight;
  tabbed subtasks; leading '=important) → events; pushes to Google Calendar.
- **gcal.py** — Google Calendar via OAuth refresh token (GOOGLE_* env). INACTIVE until
  the user provides the separate calendar account's creds (account-switchable).
- **trackers.py** — github / web-keyword / inbox(IMAP) trackers → "new developments".
- **news.py** — Hacker News front page (Algolia API); pluggable source types; digest
  picks 3-5 most relevant to `interests`.
- **korean.py** — TOPIK II curriculum (`korean_curriculum.py`) + SRS; teaches via LLM
  with translations (example_en) + grammar form/explanation; Sunday culture tidbit;
  `grade_practice()` scores user-submitted sentences.
- **memory.py** — evolving memory: daily `evolve()` decays idle importance, reinforces
  items overlapping active tasks, and LLM-compresses the old low-importance "tail" into
  background lines (tail-compression). Profile base is exempt. `render_for_digest`
  = most-important-first.
- **inbox_commands.py** — reads email REPLIES (IMAP), LLM-parses into actions: complete/
  add tasks, add/remove interests, set prefs, and Korean practice grading. Runs before
  each real send; processed message-ids remembered.
- **scheduler.py** — in-server daily scheduler (also armed via config `enabled`); send is
  guarded by the atomic claim so it can't double with the Windows task.

### UI (`web/`: index.html, styles.css, app.js [resume], digest.css, digest.js [digest+memory])
- Tabs: Resume / Daily Digest / Memory (active tab persisted in localStorage).
- Every panel is **collapsible** (click header; state remembered).
- Daily Digest tab panels (order): About you (goals split: weekly / long-term w/ dates),
  Delivery (email, send time, capacity, model, offline, include toggles, preview/send),
  **Schedule → Calendar (moved above Weekly tasks — most important)**, Weekly tasks
  (nested, triaged; per-task importance/due/est; per-subtask due; collapsible compact
  "+ Add task"; subtask add is a small "+ subtask" button that reveals an input),
  Trackers, Korean, Reminders, Headlines & interests (+ "Process replies now"), Clear/reset.
- Memory tab: **Profile (base context, never compressed)** card; Teach-it (resume
  upload + NL command); What-it-remembers list (importance dots, dates, "compressed"
  tags) + "Consolidate memory now".

## Key product decisions
- One-minute, CEO-style, inverted-pyramid brief; warm creative-secretary tone; headspace/
  anti-overload philosophy (capacity nudges, "one thing" focus).
- Headlines link via small "open ↗". Korean card injected deterministically (was blank
  when LLM put content only in prose).

## Open / pending
- **#1 was resolved**: removed Routine, added Reminders.
- Possibly remove the now-unused "Recurring / standing tasks" box from the UI.
- Optional: Reminders auto-include upcoming task due dates (currently explicit reminders).
- Optional: add OpenAI-compatible provider to run on GPT-5.4-mini.
- Google Calendar creds still pending from the user (second account).
- Deliverability hardening (SPF/DKIM) needs a custom domain (not plain Gmail).
