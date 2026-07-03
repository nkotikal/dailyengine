# Daily Digest + ResumeForge

One small local web app (Python **standard library only** — no `pip`) with two tools you switch between via tabs:

- **Daily Digest** — tell it your goals, schedule, and tasks; every morning it emails you a clean, sectioned briefing. You can run it entirely **by replying to the email**.
- **ResumeForge** — turns your profile + a job description into a one-page, ATS-friendly LaTeX resume.

Runs on **Windows + WSL (Ubuntu)** or plain Linux/macOS. All data is plain JSON under `data/` (no database).

## Setup (~5 min)

```bash
git clone <your-repo-url> bldr && cd bldr
# Deps: python3 is enough for the digest. The RESUME tool also needs LaTeX:
sudo apt-get install -y texlive-latex-base texlive-latex-recommended \
  texlive-latex-extra texlive-fonts-recommended texlive-fonts-extra poppler-utils
cp .env.example .env        # then edit it (below)
python3 server.py           # open http://127.0.0.1:8765
```

Edit `.env` and set:
- `OPENAI_API_KEY=sk-...` — the AI that writes your digest/resume.
- **Gmail send** (use a Google **App Password**, not your login): `SMTP_HOST=smtp.gmail.com`, `SMTP_PORT=587`, `SMTP_USER`, `SMTP_PASSWORD`, `SMTP_FROM`, `SMTP_SECURITY=starttls`.
- *(optional)* `IMAP_*` (same App Password) to manage the digest by replying to it.

Then in the UI: fill **About / Goals / Schedule / Tasks**, set the **recipient + send time**, click **Preview digest**, then **Send now**. `.env` is gitignored.

## Daily use — just reply to the email

Reply in plain English; the next digest applies it:
- `done: ship the API docs` · `add task: review Q3 budget, high, due Friday`
- new deadlines (`mid-internship presentation next Friday`) → tracked & escalated
- end-of-day reflections (what you did, what's blocking you, how you want to block the next days) → shape tomorrow's plan and opening
- `more GPU news, less crypto` · `switched teams to Platform Infra` · a Korean sentence → graded

## Run every morning automatically (Windows)

From the repo's `tools/` folder in PowerShell:
```powershell
powershell -ExecutionPolicy Bypass -File .\tools\install_email_task.ps1     # emails at 07:00 daily
powershell -ExecutionPolicy Bypass -File .\tools\install_startup_task.ps1   # (optional) UI at logon
```
`uninstall_*.ps1` removes them. Test a send now: `python3 tools/send_digest.py --force`. Logs: `data/digest/*.log`.

## Daily Digest — what it does

- **Email sections:** a gritty motivation line, Today's Focus, a time-chunked **Schedule**, weekly/daily **nested tasks** (priority: leading `'` = high, `'''` = critical; due dates, time estimates, auto-triage), What's New, **Reminders** (escalate as due dates near), interest-filtered **headlines**, progress, and a **language lesson**.
- **Trackers** (only *new* items reported): `github`, `web` page/keyword watch, `inbox` (IMAP), **Workday** jobs, **Eightfold** jobs.
- **Language practice:** Korean (TOPIK) or English vocabulary — per user.
- **Korean mode:** header language toggle puts the **whole dashboard and the report in Korean**.
- **Memory tab:** long-term facts that personalize every digest (seed from a resume, edit, or natural language).
- **Multiple users:** header user picker — fully isolated data; each user gets their own recipient/time and can manage via email.
- **Personalize:** color **themes** and geometric **background patterns** in the header (saved per user).

## ResumeForge — what it does

Paste/upload a profile (PDF, text, or JSON) + a job description → an optimized **one-page LaTeX PDF**. It reports "coverage gaps" you can close each pass, and follows [`RESUME_MANIFESTO.md`](RESUME_MANIFESTO.md).

```bash
python3 generate_resume.py --resume me.pdf --jd-text job.txt --compile   # first run
python3 generate_resume.py --jd-text job.txt --compile                   # later (reuses stored profile)
```

## LLM providers

Uses **OpenAI** by default (`OPENAI_API_KEY`). If you set an Anthropic-compatible gateway (`ANTHROPIC_*`) it's tried first and falls back to OpenAI, then to an offline plain digest — so a flaky gateway never blanks your email.

## Ship it as a Windows `.exe`

The code is packaging-ready (`app.py`, `app_paths.py`, `DailyDigest.spec`, `installer.iss`). Build a send-to-a-friend installer on Windows: `powershell -File tools\build.ps1` (needs Python + PyInstaller + Inno Setup). Details in [`PACKAGING_PLAN.md`](PACKAGING_PLAN.md).

## Layout & troubleshooting

- Per-user data: `data/users/<id>/…` (digest JSON + resume profile). `.env` holds keys. Nothing else to migrate.
- **No email?** Check `data/digest/send.log`, your SMTP App Password, and that a recipient is set.
- **Digest looks plain/"gutted"?** The LLM was unreachable — set `OPENAI_API_KEY`.
- **Resume won't compile?** Install the `texlive-*` packages above.
- **Port busy / paste blocked?** It binds `127.0.0.1:8765`; open that in a real browser.
