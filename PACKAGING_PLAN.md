# Windows Installer Packaging Plan (`.exe`)

> Status: **FOUNDATION IMPLEMENTED.** The code is now packaging-ready:
> `app_paths.py` (bundle vs writable dirs), a single `app.py` entry point
> (`--send` for the daily task), `DailyDigest.spec` (PyInstaller), `installer.iss`
> (Inno Setup), and `tools/build.ps1` all exist. To produce the installer, run
> `tools\build.ps1` on Windows (needs Python + PyInstaller + Inno Setup — see that
> script's header). The steps below document the design; the checklist reflects
> what's done.

## 0. Why this is feasible

- All app code is **Python standard library only** → runs on native Windows
  Python with zero code changes. WSL was only used by the launcher scripts.
- **No database.** State is JSON/text files under `data/` — trivial to relocate
  to a per-user writable folder and to back up.
- The only external binaries (`pdflatex`, `pdftotext`) are used **only by the
  resume tool**, are discovered via `shutil.which`, and already degrade
  gracefully when absent. The Daily Digest needs neither.

## 1. Architecture for a frozen app

PyInstaller changes how paths resolve, so we must split two concerns:

| Kind | Frozen location | Dev location | Notes |
| --- | --- | --- | --- |
| **Read-only bundled assets** (`web/`, `samples/`, `RESUME_MANIFESTO.md`, `.env.example`) | `sys._MEIPASS` (onedir extract dir) | repo root | served by `server.py`, read by the pipelines |
| **Writable state** (`data/users/<id>/...`, `data/users.json`, `.env`, logs) | `%APPDATA%\DailyDigest\` | repo root | per-user trees; survives reinstalls/updates |

### Code change required (the only substantive one)
Add a small shared module `app_paths.py`:

```python
import sys, os
from pathlib import Path

FROZEN = getattr(sys, "frozen", False)

def bundle_dir() -> Path:
    # Read-only assets shipped inside the build.
    return Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))

def data_dir() -> Path:
    # Writable per-user state.
    if FROZEN:
        d = Path(os.environ["APPDATA"]) / "DailyDigest"
    else:
        d = Path(__file__).resolve().parent / "data"
    d.mkdir(parents=True, exist_ok=True)
    return d

def env_path() -> Path:
    return (data_dir() / ".env") if FROZEN else (Path(__file__).resolve().parent / ".env")
```

Then refactor the hard-coded `ROOT`/`DIR` constants to use it:
- `digest_pipeline/store.py` → `DIR = app_paths.data_dir() / "digest"`.
- `resume_pipeline/store.py` → use `app_paths.data_dir()`.
- `.env` loading in `server.py`, `generate_resume.py`, `tools/send_digest.py`
  → `load_dotenv(app_paths.env_path())`.
- `server.py` static-asset serving (web/) → `app_paths.bundle_dir() / "web"`.
- `RESUME_MANIFESTO.md` + `samples/` reads → `bundle_dir()`.
- `output/` (generated resume) → put under `data_dir()/output` when frozen.

This is ~1 focused refactor pass; behavior in dev mode is unchanged.

### Single exe, two roles
Build **one** executable that branches on an arg, to avoid maintaining two binaries:
- `DailyDigest.exe` → starts the web UI + in-app scheduler (current `server.py`).
- `DailyDigest.exe --send [--force]` → headless "send today's digest" (current
  `tools/send_digest.py` logic).

Add a tiny `__main__`/entrypoint (`app.py`) that dispatches on `--send`.

## 2. Freeze with PyInstaller

- Mode: **`--onedir`** (faster start, easy to include data files) — produces a
  `DailyDigest\` folder with `DailyDigest.exe` + dependencies.
- Windowed (`--noconsole`) so no console flashes when launched by Task Scheduler
  or a shortcut.
- Bundle assets via a `.spec` file:
  - `datas = [("web","web"), ("samples","samples"), ("RESUME_MANIFESTO.md","."), (".env.example",".")]`
- Icon: `--icon assets\app.ico` (need to add an icon).
- Output: `dist\DailyDigest\`.

Deliverable from this step: a self-contained folder that runs without Python.

## 3. Wrap with Inno Setup (`installer.iss`)

Inno Setup compiles `dist\DailyDigest\` into `DailyDigest-Setup-x.y.z.exe`.

- **Install dir:** `{autopf}\DailyDigest` (Program Files). Per-user install
  (`{localappdata}\Programs\DailyDigest`) avoids needing admin — preferred so
  non-admin users can install and so scheduled tasks run as the user.
- **First-run configuration page** (Inno `[Code]` Pascal wizard page) collects:
  - OpenAI API key → `OPENAI_API_KEY`
  - Gmail address + App Password → `SMTP_USER`/`SMTP_PASSWORD`/`SMTP_FROM`,
    and the same for `IMAP_USER`/`IMAP_PASSWORD` (enables reply-by-email).
  - Recipient address + send time (default 07:00).
  - Writes `%APPDATA%\DailyDigest\.env` from these (only if not already present,
    so reinstalls don't clobber edited creds).
  - *(Alternative, more maintainable: ship a `.env` skeleton and open an
    in-app **Setup** page in the web UI on first launch that writes `.env` via a
    new `/api/setup` endpoint. Decide at implementation time; the Inno page is
    fewer moving parts for the user.)*
- **Scheduled tasks** (created in `[Run]`/`[Code]` via `schtasks`, as the
  installing user — native, no WSL/VBS):
  - `DailyDigestServer` — `SC ONLOGON` → `"{app}\DailyDigest.exe"`.
  - `DailyDigestEmail` — `SC DAILY /ST <chosen time>` →
    `"{app}\DailyDigest.exe" --send`.
- **Shortcuts:** Start Menu (and optional Desktop) "Daily Digest" → a small
  launcher that ensures the server is running and opens
  `http://127.0.0.1:8765` in the default browser.
- **Optional component "Resume tools (LaTeX)":** if checked, run
  `winget install MiKTeX.MiKTeX` (and `oschwartz10612.Poppler` or document
  manually) so the resume tab can compile PDFs. Off by default (large).
- **Uninstaller:**
  - `schtasks /Delete /TN DailyDigestServer /F` and `DailyDigestEmail`.
  - Stop any running `DailyDigest.exe`.
  - Prompt: keep or remove `%APPDATA%\DailyDigest` (data + creds). Default keep.

## 4. Build pipeline (`build.ps1`)

One-time tooling on the build machine:
- `winget install Python.Python.3.12`
- `pip install pyinstaller`
- `winget install JRSoftware.InnoSetup`

`build.ps1` steps:
1. `pyinstaller DailyDigest.spec` → `dist\DailyDigest\`.
2. `& "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe" installer.iss` →
   `Output\DailyDigest-Setup-x.y.z.exe`.
3. (Optional) checksum + zip.

The single output `DailyDigest-Setup-x.y.z.exe` is what people download.

## 5. Known limitations / things to call out to users

- **Personal secrets aren't automatic.** Each person enters their own OpenAI key
  and Gmail App Password once (installer wizard or in-app Setup). Everything else
  is automatic.
- **SmartScreen / antivirus:** an unsigned exe shows a "Windows protected your
  PC" prompt (Run anyway → More info). Optional fix: an Authenticode
  **code-signing certificate** (~$100–400/yr) — defer unless distribution grows.
- **Updates:** re-running a newer `Setup.exe` upgrades in place; `%APPDATA%` data
  persists. (No auto-updater in v1.)
- **LLM going forward:** with no AMD gateway configured, the app uses OpenAI
  immediately — already implemented. Installer only needs the OpenAI key.

## 6. Implementation checklist

- [x] Add `app_paths.py`; refactor `user_context.py` (`DATA_ROOT` →
      `app_paths.data_dir()`), the `.env` loaders (`server.py`, `app.py`,
      `tools/send_digest.py`), web/manifesto serving (`bundle_dir()`), and the
      resume `output/` location. (The per-user `store.py` files resolve through
      `user_context`, which now points at `app_paths.data_dir()`.)
- [x] Add `app.py` entrypoint dispatching `--send` vs server (tees output to
      `app.log` when frozen; auto-opens the browser).
- [x] Write `DailyDigest.spec` (datas + noconsole + optional icon).
- [x] Write `installer.iss` (per-user install, seeds `.env`, schtasks for the
      logon server + 07:00 email, shortcuts, uninstall cleanup).
- [x] Write `tools/build.ps1`.
- [ ] Add `assets/app.ico` (optional; the spec auto-detects it).
- [ ] (Optional) in-app `/api/setup` page instead of editing `.env` in Notepad.
- [ ] (Optional) MiKTeX component for the resume tab's PDF compile.
- [ ] Test on a clean Windows VM: build → install → fill `.env` → UI loads →
      Send now → task fires → reply-by-email applies → uninstall removes tasks.

## 6b. Building it now

```powershell
# one-time
winget install Python.Python.3.12
winget install JRSoftware.InnoSetup
py -m pip install --upgrade pyinstaller
# build the installer
powershell -ExecutionPolicy Bypass -File tools\build.ps1
# -> Output\DailyDigest-Setup-1.0.0.exe  (send this to someone)
```

The recipient runs the installer, fills in `%APPDATA%\DailyDigest\.env` (OpenAI key
+ Gmail app password + recipient), and gets the full app with morning email — no
Python, no WSL. Writable data lives per-user under `%APPDATA%\DailyDigest\`.

## 7. Rough effort estimate

- Path refactor + entrypoint: ~0.5 day.
- PyInstaller spec + getting a clean frozen run: ~0.5 day.
- Inno Setup script (wizard, tasks, shortcuts, uninstall): ~0.5–1 day.
- Clean-VM testing + polish: ~0.5 day.

**~2–2.5 days** total once core features are frozen.
