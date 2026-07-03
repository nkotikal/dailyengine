# Daily Digest

**A local app that sends you a morning email with your schedule, tasks, deadlines, and updates — and lets you manage it all by replying.**

Daily Digest pulls together your goals, schedule, tasks, project trackers, and optional language practice into one email each morning. Reply to that email in plain English to log progress, add tasks, note blockers, or update your plan — and the next brief reflects those changes.

It also includes **ResumeForge**, a tool that takes your background and a job posting and produces a one-page, ATS-ready resume.

Runs locally on your machine. No accounts, no cloud, no database — just your keys in a `.env` file and your data stored as plain files.

---

## What it does

- **One morning email.** Today's focus, a time-blocked schedule, upcoming deadlines, tracker updates, and news filtered to your interests — in a single, easy-to-scan message.
- **Reply to update.** No need to open the dashboard for routine changes. Write things like *"done: shipped the API docs," "add task: budget review, due Friday," "blocked on the vendor call"* and tomorrow's brief picks them up.
- **Persistent memory.** Stores your role, projects, and preferences over time so briefs stay relevant; older detail is compressed as it ages out.
- **Per-user isolation.** Multiple people can each have a fully separate setup on the same machine.

## Get started (~5 minutes)

```bash
git clone <your-repo-url> daily-digest && cd daily-digest
# The resume tool also needs LaTeX (skip if you only want the digest):
sudo apt-get install -y texlive-latex-base texlive-latex-recommended \
  texlive-latex-extra texlive-fonts-recommended texlive-fonts-extra poppler-utils
cp .env.example .env      # add your keys (below)
python3 server.py         # open http://127.0.0.1:8765
```

In `.env`, set three things:

- **`OPENAI_API_KEY`** — powers the brief and resume optimization.
- **Email delivery** (Gmail example, using a Google **App Password**): `SMTP_HOST=smtp.gmail.com`, `SMTP_PORT=587`, `SMTP_USER`, `SMTP_PASSWORD`, `SMTP_FROM`, `SMTP_SECURITY=starttls`.
- **`IMAP_*`** *(optional, same App Password)* — enables inbox-based updates via reply.

Then open the app, fill in **About you / Goals / Schedule / Tasks**, set your **recipient and send time**, hit **Preview**, and send yourself the first one.

*(Requires Python 3 — standard library only, nothing to `pip install`. Works on Windows + WSL, Linux, or macOS.)*

## Wake up to it every morning

On Windows, register the scheduled tasks once:

```powershell
powershell -ExecutionPolicy Bypass -File .\tools\install_email_task.ps1     # 07:00 daily email
powershell -ExecutionPolicy Bypass -File .\tools\install_startup_task.ps1   # keep the app running (optional)
```

`uninstall_*.ps1` reverses it. Prefer a desktop app? Run `powershell -File tools\build.ps1` to produce a Windows installer (`Setup.exe`); see [`PACKAGING_PLAN.md`](PACKAGING_PLAN.md).

## What's inside the brief

- **Today's Focus & Schedule** — priorities up top and a time-blocked plan. Mark items important with a leading `'` (or `'''` for critical); tasks carry due dates, time estimates, and automatic triage.
- **Deadlines & reminders** that resurface and grow more prominent as the date approaches.
- **Trackers** that report only what's *new*: GitHub issues/PRs, any web page or careers site, your inbox, and job postings from **Workday** and **Eightfold** career sites (auto-flagged to fit your profile).
- **Headlines** from your sources, narrowed to the topics you care about.
- **Language practice** — a daily Korean (TOPIK) or English-vocabulary lesson that doesn't repeat; reply with a sentence to have it graded.
- **Memory** — an editable store of what matters about you, seedable from your resume.

Customize from the header: color **themes**, geometric **backgrounds**, and a **Korean mode** that renders both the dashboard and your brief in Korean.

## ResumeForge

Give it your background (PDF, text, or JSON) and a job description; get back an optimized, single-page LaTeX resume built on an ATS-friendly template. It flags requirements it couldn't substantiate so you can fill gaps on the next pass.

```bash
python3 generate_resume.py --resume me.pdf --jd-text job.txt --compile   # first run
python3 generate_resume.py --jd-text job.txt --compile                   # later runs reuse your profile
```

## Under the hood

- **Local & private.** Your data lives in `data/users/<id>/…` as plain JSON; `.env` holds your keys. Nothing leaves your machine except the AI/email calls you configure.
- **Resilient AI.** Uses OpenAI by default; if you have an Anthropic-compatible gateway it's tried first, then falls back to OpenAI, then to a plain offline brief — so a flaky connection doesn't leave you without a morning email.

## Troubleshooting

- **No email?** Check `data/digest/send.log`, confirm your SMTP App Password, and make sure a recipient is set.
- **Brief looks plain?** The AI was unreachable — set `OPENAI_API_KEY`.
- **Resume won't build?** Install the `texlive-*` packages above.
- **Can't reach it / paste blocked?** It serves at `http://127.0.0.1:8765`; open that in a normal browser.
