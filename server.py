#!/usr/bin/env python3
"""Local web server for the resume pipeline (stdlib only).

Serves the liquid-glass UI and exposes a small JSON API that drives
``resume_pipeline.core.generate``. Run inside WSL:

    python3 server.py            # then open http://127.0.0.1:8000

The profile/context area is optional once a profile has been stored; the first
time (no stored profile) a profile JSON is required.
"""

import argparse
import base64
import json
import os
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import app_paths
import user_context

from resume_pipeline import compile as texc
from resume_pipeline.compile import CompileError
from resume_pipeline import core, llm, store

# Daily Digest engine (fully isolated feature; see digest_pipeline/).
from digest_pipeline import digest as digest_engine
from digest_pipeline import email_send as digest_email
from digest_pipeline import store as digest_store
from digest_pipeline import schedule as digest_schedule
from digest_pipeline import trackers as digest_trackers
from digest_pipeline import korean as digest_korean
from digest_pipeline import english as digest_english
from digest_pipeline import gcal as digest_gcal
from digest_pipeline import memory as digest_memory
from digest_pipeline import tasks as digest_tasks
from digest_pipeline import news as digest_news
from digest_pipeline import inbox_commands as digest_replies
from digest_pipeline.email_send import EmailError
from digest_pipeline.gcal import GCalError
from digest_pipeline.llm import DigestLLMError
from datetime import datetime

ROOT = Path(__file__).resolve().parent
WEB = app_paths.bundle_dir() / "web"

_CONTENT_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "application/javascript; charset=utf-8",
    ".svg": "image/svg+xml",
    ".json": "application/json; charset=utf-8",
}


class Handler(BaseHTTPRequestHandler):
    server_version = "ResumeForge/1.0"

    def _send(self, code, body, content_type="application/json; charset=utf-8", extra=None):
        if isinstance(body, str):
            body = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def _send_json(self, code, obj):
        self._send(code, json.dumps(obj), "application/json; charset=utf-8")

    def _serve_file(self, rel):
        path = (WEB / rel).resolve()
        if not str(path).startswith(str(WEB.resolve())) or not path.is_file():
            self._send(404, "Not found", "text/plain; charset=utf-8")
            return
        ctype = _CONTENT_TYPES.get(path.suffix, "application/octet-stream")
        self._send(200, path.read_bytes(), ctype)

    # -- routing ------------------------------------------------------------

    def do_GET(self):
        if self.path in ("/", "/index.html"):
            self._serve_file("index.html")
        elif self.path == "/api/status":
            self._status()
        elif self.path == "/api/users":
            self._users_list()
        elif self.path == "/api/profile":
            self._profile_get()
        elif self.path == "/api/profile/versions":
            self._profile_versions()
        elif self.path == "/api/digest/status":
            self._digest_status()
        elif self.path == "/api/memory":
            self._memory_list()
        elif self.path.startswith("/static/"):
            self._serve_file(self.path[len("/static/"):])
        elif self.path in ("/styles.css", "/app.js", "/digest.css", "/digest.js"):
            self._serve_file(self.path.lstrip("/"))
        else:
            self._send(404, "Not found", "text/plain; charset=utf-8")

    def do_POST(self):
        if self.path == "/api/users/create":
            self._users_create()
        elif self.path == "/api/users/switch":
            self._users_switch()
        elif self.path == "/api/users/rename":
            self._users_rename()
        elif self.path == "/api/users/delete":
            self._users_delete()
        elif self.path == "/api/generate":
            self._generate()
        elif self.path == "/api/reset":
            self._reset()
        elif self.path == "/api/compile":
            self._compile_tex()
        elif self.path == "/api/profile/save":
            self._profile_save()
        elif self.path == "/api/profile/version":
            self._profile_version_get()
        elif self.path == "/api/profile/restore":
            self._profile_restore()
        elif self.path == "/api/profile/version/delete":
            self._profile_version_delete()
        elif self.path == "/api/digest/config":
            self._digest_config()
        elif self.path == "/api/digest/update":
            self._digest_add_update()
        elif self.path == "/api/digest/update/delete":
            self._digest_delete_update()
        elif self.path == "/api/digest/preview":
            self._digest_preview()
        elif self.path == "/api/digest/send":
            self._digest_send()
        elif self.path == "/api/digest/schedule":
            self._digest_schedule_save()
        elif self.path == "/api/digest/schedule/push":
            self._digest_schedule_push()
        elif self.path == "/api/digest/tracker/add":
            self._digest_tracker_add()
        elif self.path == "/api/digest/tracker/update":
            self._digest_tracker_update()
        elif self.path == "/api/digest/tracker/delete":
            self._digest_tracker_delete()
        elif self.path == "/api/digest/tracker/test":
            self._digest_tracker_test()
        elif self.path == "/api/digest/korean/preview":
            self._digest_korean_preview()
        elif self.path == "/api/digest/korean/placement":
            self._digest_korean_placement()
        elif self.path == "/api/digest/reminder/add":
            self._digest_reminder_add()
        elif self.path == "/api/digest/reminder/update":
            self._digest_reminder_update()
        elif self.path == "/api/digest/reminder/delete":
            self._digest_reminder_delete()
        elif self.path == "/api/memory/add":
            self._memory_add()
        elif self.path == "/api/memory/update":
            self._memory_update()
        elif self.path == "/api/memory/delete":
            self._memory_delete()
        elif self.path == "/api/memory/command":
            self._memory_command()
        elif self.path == "/api/memory/resume":
            self._memory_resume()
        elif self.path == "/api/memory/profile":
            self._memory_profile()
        elif self.path == "/api/memory/evolve":
            self._memory_evolve()
        elif self.path == "/api/digest/tasks/derive":
            self._tasks_derive()
        elif self.path == "/api/digest/tasks/add":
            self._tasks_add()
        elif self.path == "/api/digest/tasks/update":
            self._tasks_update()
        elif self.path == "/api/digest/tasks/delete":
            self._tasks_delete()
        elif self.path == "/api/digest/tasks/clear-done":
            self._tasks_clear_done()
        elif self.path == "/api/digest/clear":
            self._digest_clear_category()
        elif self.path == "/api/digest/replies/process":
            self._digest_process_replies()
        elif self.path == "/api/digest/tasks/subtask/add":
            self._subtask_add()
        elif self.path == "/api/digest/tasks/subtask/update":
            self._subtask_update()
        elif self.path == "/api/digest/tasks/subtask/delete":
            self._subtask_delete()
        else:
            self._send(404, "Not found", "text/plain; charset=utf-8")

    # -- endpoints ----------------------------------------------------------

    # -- users (per-user compartmentalization) -----------------------------

    def _users_payload(self):
        return {"ok": True, "users": user_context.list_users(),
                "active": user_context.get_active()}

    def _users_list(self):
        self._send_json(200, self._users_payload())

    def _users_create(self):
        try:
            data = self._read_json_body()
        except json.JSONDecodeError:
            self._send_json(400, {"ok": False, "error": "Invalid request body."})
            return
        name = (data.get("name") or "").strip()
        if not name:
            self._send_json(400, {"ok": False, "error": "Provide a name for the new user."})
            return
        user = user_context.create_user(name)
        payload = self._users_payload()
        payload["created"] = user
        self._send_json(200, payload)

    def _users_switch(self):
        try:
            data = self._read_json_body()
        except json.JSONDecodeError:
            self._send_json(400, {"ok": False, "error": "Invalid request body."})
            return
        try:
            user_context.set_active(data.get("id", ""))
        except ValueError as exc:
            self._send_json(400, {"ok": False, "error": str(exc)})
            return
        self._send_json(200, self._users_payload())

    def _users_rename(self):
        try:
            data = self._read_json_body()
        except json.JSONDecodeError:
            self._send_json(400, {"ok": False, "error": "Invalid request body."})
            return
        ok = user_context.rename_user(data.get("id", ""), data.get("name", ""))
        self._send_json(200 if ok else 404,
                        {**self._users_payload(), "ok": ok})

    def _users_delete(self):
        try:
            data = self._read_json_body()
        except json.JSONDecodeError:
            self._send_json(400, {"ok": False, "error": "Invalid request body."})
            return
        try:
            ok = user_context.delete_user(data.get("id", ""))
        except ValueError as exc:
            self._send_json(400, {"ok": False, "error": str(exc)})
            return
        self._send_json(200, {**self._users_payload(), "ok": ok})

    def _status(self):
        self._send_json(200, {
            "profile_stored": store.has_profile(),
            "profile_name": store.profile_name(),
            "has_optimized": store.has_optimized(),
            "has_context": store.has_context(),
            "has_key": bool(os.environ.get(llm.API_KEY_ENV)),
            "gateway": os.environ.get(llm.BASE_URL_ENV) or llm.DEFAULT_BASE_URL,
            "auth_style": os.environ.get(llm.AUTH_STYLE_ENV) or "x-api-key",
            "model": os.environ.get("ANTHROPIC_MODEL") or llm.DEFAULT_MODEL,
            "pdflatex": texc.have_pdflatex(),
        })

    def _reset(self):
        removed = store.clear()
        self._send_json(200, {"ok": True, "removed": removed})

    # -- resume profile: view / edit / history -----------------------------

    def _profile_get(self):
        profile = store.load_profile()
        if profile is not None:
            store.archive_profile(profile, source="current")  # ensure current is in history (dedupes)
        self._send_json(200, {
            "ok": True,
            "profile": profile,
            "name": store.profile_name(),
            "has_profile": profile is not None,
            "has_optimized": store.has_optimized(),
            "versions": store.list_profile_versions(),
        })

    def _profile_versions(self):
        self._send_json(200, {"ok": True, "versions": store.list_profile_versions()})

    def _profile_save(self):
        try:
            data = self._read_json_body()
        except json.JSONDecodeError:
            self._send_json(400, {"ok": False, "error": "Invalid request body."})
            return
        profile = data.get("profile")
        # Allow the editor to send a raw JSON string too.
        if isinstance(profile, str):
            try:
                profile = json.loads(profile)
            except json.JSONDecodeError as exc:
                self._send_json(400, {"ok": False, "error": f"Profile is not valid JSON: {exc}"})
                return
        if not isinstance(profile, dict):
            self._send_json(400, {"ok": False, "error": "Profile must be a JSON object."})
            return
        store.save_profile(profile)
        store.archive_profile(profile, source="edited")
        store.clear_optimized()  # base changed -> prior optimized draft is stale
        self._send_json(200, {
            "ok": True,
            "name": store.profile_name(),
            "versions": store.list_profile_versions(),
        })

    def _profile_version_get(self):
        try:
            data = self._read_json_body()
        except json.JSONDecodeError:
            self._send_json(400, {"ok": False, "error": "Invalid request body."})
            return
        profile = store.load_profile_version(data.get("id", ""))
        if profile is None:
            self._send_json(404, {"ok": False, "error": "Version not found."})
            return
        self._send_json(200, {"ok": True, "profile": profile})

    def _profile_restore(self):
        try:
            data = self._read_json_body()
        except json.JSONDecodeError:
            self._send_json(400, {"ok": False, "error": "Invalid request body."})
            return
        profile = store.load_profile_version(data.get("id", ""))
        if profile is None:
            self._send_json(404, {"ok": False, "error": "Version not found."})
            return
        store.save_profile(profile)
        store.archive_profile(profile, source="restored")
        store.clear_optimized()
        self._send_json(200, {
            "ok": True, "profile": profile, "name": store.profile_name(),
            "versions": store.list_profile_versions(),
        })

    def _profile_version_delete(self):
        try:
            data = self._read_json_body()
        except json.JSONDecodeError:
            self._send_json(400, {"ok": False, "error": "Invalid request body."})
            return
        ok = store.delete_profile_version(data.get("id", ""))
        self._send_json(200, {"ok": ok, "versions": store.list_profile_versions()})

    # -- reminders / deadlines ---------------------------------------------

    def _digest_reminder_add(self):
        try:
            data = self._read_json_body()
        except json.JSONDecodeError:
            self._send_json(400, {"ok": False, "error": "Invalid request body."})
            return
        try:
            item = digest_store.add_reminder(
                data.get("text", ""), due=data.get("due", ""),
                priority=data.get("priority", "medium"),
            )
        except ValueError as exc:
            self._send_json(400, {"ok": False, "error": str(exc)})
            return
        self._send_json(200, {"ok": True, "reminder": item,
                              "reminders": digest_store.list_reminders()})

    def _digest_reminder_update(self):
        try:
            data = self._read_json_body()
        except json.JSONDecodeError:
            self._send_json(400, {"ok": False, "error": "Invalid request body."})
            return
        ok = digest_store.update_reminder(data.get("id", ""), data.get("fields", {}))
        self._send_json(200, {"ok": ok, "reminders": digest_store.list_reminders()})

    def _digest_reminder_delete(self):
        try:
            data = self._read_json_body()
        except json.JSONDecodeError:
            self._send_json(400, {"ok": False, "error": "Invalid request body."})
            return
        ok = digest_store.delete_reminder(data.get("id", ""))
        self._send_json(200, {"ok": ok, "reminders": digest_store.list_reminders()})

    # -- daily digest endpoints --------------------------------------------

    def _digest_status(self):
        cfg = digest_store.load_config()
        state = digest_store.load_state()
        pending = digest_store.pending_updates()
        sched = digest_store.load_schedule()
        self._send_json(200, {
            "ok": True,
            "config": cfg,
            "pending_updates": pending,
            "pending_count": len(pending),
            "email": digest_email.config_summary(),
            "has_key": bool(os.environ.get(llm.API_KEY_ENV)),
            "model": os.environ.get(digest_korean.llm.MODEL_ENV) or digest_korean.llm.DEFAULT_MODEL,
            "schedule": {
                "raw": sched.get("raw", ""),
                "updated_at": sched.get("updated_at", ""),
                "for_date": sched.get("for_date", ""),
                "counts": digest_schedule.summary_counts(sched.get("parsed", {})) if sched.get("parsed") else {},
            },
            "reflection": digest_store.load_reflection(),
            "replies_deferred_at": state.get("replies_deferred_at", ""),
            "trackers": digest_store.list_trackers(),
            "weekly_tasks": digest_store.list_weekly_tasks(),
            "weekly_tasks_summary": digest_tasks.summary(),
            "news": {
                "enabled": cfg.get("news_enabled", True),
                "sources": cfg.get("news_sources", []),
                "source_types": digest_news.SOURCE_TYPES,
                "interests": cfg.get("interests", []),
            },
            "replies": {"configured": digest_replies.is_configured()},
            "tracker_types": digest_trackers.TRACKER_TYPES,
            "reminders": digest_store.list_reminders(),
            "calendar": digest_gcal.status(),
            "korean": {
                "enabled": cfg.get("korean_enabled", False),
                "language": cfg.get("language", "korean"),
                "level": cfg.get("korean_level", "intermediate"),
                "english_level": cfg.get("english_level", "advanced"),
                "history_count": len(digest_store.load_korean().get("history", [])),
                "seen_vocab": len(digest_store.load_korean().get("seen_vocab", [])),
                "progress": (digest_english.progress_summary(digest_store.load_english())
                             if (cfg.get("language") or "korean") == "english"
                             else digest_korean.progress_summary(digest_store.load_korean())),
            },
            "state": {
                "last_sent_date": state.get("last_sent_date", ""),
                "last_sent_at": state.get("last_sent_at", ""),
                "last_subject": state.get("last_subject", ""),
                "last_error": state.get("last_error", ""),
            },
            "next_run": digest_engine.next_run_human(cfg),
        })

    def _digest_schedule_save(self):
        try:
            data = self._read_json_body()
        except json.JSONDecodeError:
            self._send_json(400, {"ok": False, "error": "Invalid request body."})
            return
        raw = data.get("raw", "") if isinstance(data, dict) else ""
        parsed = digest_schedule.parse_schedule(raw)
        digest_store.save_schedule(raw, parsed)
        self._send_json(200, {
            "ok": True,
            "parsed": parsed,
            "counts": digest_schedule.summary_counts(parsed),
            "text": digest_schedule.render_text(parsed),
        })

    def _digest_schedule_push(self):
        sched = digest_store.load_schedule()
        parsed = sched.get("parsed")
        if not parsed or not parsed.get("events"):
            self._send_json(400, {"ok": False, "error": "No parsed schedule to push. Save a schedule first."})
            return
        if not digest_gcal.is_configured():
            self._send_json(400, {"ok": False, "error":
                "Google Calendar is not configured yet. Add GOOGLE_* values to .env "
                "(you can switch to the calendar account at any time)."})
            return
        try:
            result = digest_gcal.create_events_from_schedule(parsed)
        except GCalError as exc:
            self._send_json(400, {"ok": False, "error": str(exc)})
            return
        self._send_json(200, {"ok": True, **result})

    def _digest_tracker_add(self):
        try:
            data = self._read_json_body()
        except json.JSONDecodeError:
            self._send_json(400, {"ok": False, "error": "Invalid request body."})
            return
        ttype = (data.get("type") or "").strip()
        if ttype not in digest_trackers.TRACKER_TYPES:
            self._send_json(400, {"ok": False, "error": f"Unknown tracker type: {ttype}"})
            return
        item = digest_store.add_tracker(ttype, data.get("name", ""), data.get("config", {}))
        self._send_json(200, {"ok": True, "tracker": item, "trackers": digest_store.list_trackers()})

    def _digest_tracker_update(self):
        try:
            data = self._read_json_body()
        except json.JSONDecodeError:
            self._send_json(400, {"ok": False, "error": "Invalid request body."})
            return
        ok = digest_store.update_tracker(data.get("id", ""), data.get("fields", {}))
        self._send_json(200, {"ok": ok, "trackers": digest_store.list_trackers()})

    def _digest_tracker_delete(self):
        try:
            data = self._read_json_body()
        except json.JSONDecodeError:
            self._send_json(400, {"ok": False, "error": "Invalid request body."})
            return
        ok = digest_store.delete_tracker(data.get("id", ""))
        self._send_json(200, {"ok": ok, "trackers": digest_store.list_trackers()})

    def _digest_tracker_test(self):
        try:
            data = self._read_json_body()
        except json.JSONDecodeError:
            self._send_json(400, {"ok": False, "error": "Invalid request body."})
            return
        tracker = data.get("tracker")
        if not tracker:
            tracker = digest_store.get_tracker(data.get("id", ""))
        if not tracker:
            self._send_json(400, {"ok": False, "error": "No tracker provided."})
            return
        try:
            findings = digest_trackers.test_one(tracker)
        except Exception as exc:  # noqa: BLE001
            self._send_json(400, {"ok": False, "error": f"{type(exc).__name__}: {exc}"})
            return
        self._send_json(200, {"ok": True, "findings": findings})

    def _digest_korean_preview(self):
        cfg = digest_store.load_config()
        today = datetime.now().strftime("%Y-%m-%d")
        language = (cfg.get("language") or "korean").strip().lower()
        offline = bool(cfg.get("offline")) or (
            not digest_korean.llm.have_key() and not digest_korean.llm.openai_configured())
        if language == "english":
            lesson = digest_store.english_lesson_for(today)
            if lesson is None:
                try:
                    est = digest_store.load_english()
                    lesson, nst = digest_english.build_lesson(
                        est, level=cfg.get("english_level", "advanced"),
                        today=today, model=(cfg.get("model") or None), offline=offline)
                    digest_store.save_english(nst)
                except DigestLLMError as exc:
                    self._send_json(502, {"ok": False, "error": f"LLM error: {exc}"})
                    return
            self._send_json(200, {
                "ok": True, "language": "english", "lesson": lesson,
                "text": digest_english.render_summary(lesson),
                "progress": digest_english.progress_summary(digest_store.load_english()),
            })
            return
        lesson = digest_store.korean_lesson_for(today)
        if lesson is None:
            try:
                kstate = digest_store.load_korean()
                lesson, new_state = digest_korean.build_lesson(
                    kstate, level=cfg.get("korean_level", "intermediate"),
                    today=today, model=(cfg.get("model") or None), offline=offline,
                )
                digest_store.save_korean(new_state)
            except DigestLLMError as exc:
                self._send_json(502, {"ok": False, "error": f"LLM error: {exc}"})
                return
        self._send_json(200, {
            "ok": True, "language": "korean", "lesson": lesson,
            "text": digest_korean.render_summary(lesson),
            "progress": digest_korean.progress_summary(digest_store.load_korean()),
        })

    def _digest_korean_placement(self):
        try:
            data = self._read_json_body()
        except json.JSONDecodeError:
            self._send_json(400, {"ok": False, "error": "Invalid request body."})
            return
        level = (data.get("level") or "intermediate").strip()
        state = digest_store.load_korean()
        start = digest_korean.cur.LEVEL_START_INDEX.get(level, 0)
        # Optional explicit override of where to start in the grammar syllabus.
        if isinstance(data.get("grammar_start"), int):
            start = max(0, min(data["grammar_start"], digest_korean.cur.grammar_total()))
        state.setdefault("progress", {})["grammar_index"] = start
        state["placement"] = {"done": True, "level": level}
        digest_store.save_korean(state)
        digest_store.save_config({"korean_level": level})
        self._send_json(200, {"ok": True,
                              "progress": digest_korean.progress_summary(state)})

    # -- memory endpoints --------------------------------------------------

    def _memory_payload(self):
        return {
            "ok": True,
            "memories": digest_store.list_memories(),
            "categories": digest_store.MEMORY_CATEGORIES,
            "profile_base": digest_store.load_profile_base(),
        }

    def _memory_list(self):
        self._send_json(200, self._memory_payload())

    def _memory_add(self):
        try:
            data = self._read_json_body()
        except json.JSONDecodeError:
            self._send_json(400, {"ok": False, "error": "Invalid request body."})
            return
        try:
            digest_store.add_memory(data.get("text", ""), data.get("category", "fact"))
        except ValueError as exc:
            self._send_json(400, {"ok": False, "error": str(exc)})
            return
        self._send_json(200, self._memory_payload())

    def _memory_update(self):
        try:
            data = self._read_json_body()
        except json.JSONDecodeError:
            self._send_json(400, {"ok": False, "error": "Invalid request body."})
            return
        digest_store.update_memory(data.get("id", ""), data.get("fields", {}))
        self._send_json(200, self._memory_payload())

    def _memory_delete(self):
        try:
            data = self._read_json_body()
        except json.JSONDecodeError:
            self._send_json(400, {"ok": False, "error": "Invalid request body."})
            return
        digest_store.delete_memory(data.get("id", ""))
        self._send_json(200, self._memory_payload())

    def _memory_command(self):
        try:
            data = self._read_json_body()
        except json.JSONDecodeError:
            self._send_json(400, {"ok": False, "error": "Invalid request body."})
            return
        try:
            result = digest_memory.apply_command(data.get("command", ""))
        except ValueError as exc:
            self._send_json(400, {"ok": False, "error": str(exc)})
            return
        except DigestLLMError as exc:
            self._send_json(502, {"ok": False, "error": f"LLM error: {exc}"})
            return
        self._send_json(200, {"ok": True, **result,
                              "categories": digest_store.MEMORY_CATEGORIES})

    def _memory_resume(self):
        try:
            data = self._read_json_body()
        except json.JSONDecodeError:
            self._send_json(400, {"ok": False, "error": "Invalid request body."})
            return
        # Accept a base64 PDF (parsed with pdftotext) or pasted text.
        text = (data.get("text") or "").strip()
        pdf_b64 = data.get("resume_pdf_base64")
        if pdf_b64:
            try:
                pdf_bytes = base64.b64decode(pdf_b64)
                text = core.extract_pdf_text(pdf_bytes)
            except core.PipelineError as exc:
                self._send_json(400, {"ok": False, "error": str(exc)})
                return
            except (ValueError, TypeError):
                self._send_json(400, {"ok": False, "error": "Could not decode the uploaded PDF."})
                return
        if not text:
            self._send_json(400, {"ok": False, "error": "Provide a resume PDF or paste resume text."})
            return
        try:
            result = digest_memory.ingest_resume(text)
        except DigestLLMError as exc:
            self._send_json(502, {"ok": False, "error": f"LLM error: {exc}"})
            return
        self._send_json(200, {"ok": True, **result,
                              "categories": digest_store.MEMORY_CATEGORIES})

    # -- weekly task list endpoints ----------------------------------------

    def _tasks_payload(self):
        return {"ok": True, "tasks": digest_store.list_weekly_tasks(),
                "summary": digest_tasks.summary()}

    def _tasks_derive(self):
        try:
            data = self._read_json_body()
        except json.JSONDecodeError:
            self._send_json(400, {"ok": False, "error": "Invalid request body."})
            return
        # Use posted weekly text if given (current box), else the saved config value.
        weekly_text = data.get("weekly_text")
        if weekly_text is None:
            weekly_text = digest_store.load_config().get("weekly_goals", "")
        else:
            digest_store.save_config({"weekly_goals": weekly_text})
        cfg = digest_store.load_config()
        use_llm = not bool(cfg.get("offline"))
        try:
            result = digest_tasks.derive_and_merge(
                weekly_text, model=(cfg.get("model") or None), use_llm=use_llm)
        except Exception as exc:  # noqa: BLE001
            self._send_json(500, {"ok": False, "error": f"{type(exc).__name__}: {exc}"})
            return
        self._send_json(200, {"ok": True, "added": result["added"],
                              "tasks": result["tasks"], "summary": digest_tasks.summary()})

    def _tasks_add(self):
        try:
            data = self._read_json_body()
        except json.JSONDecodeError:
            self._send_json(400, {"ok": False, "error": "Invalid request body."})
            return
        try:
            digest_store.add_weekly_task(
                data.get("text", ""), data.get("priority", "medium"),
                due=data.get("due", ""),
                est_minutes=digest_tasks.parse_est(data.get("est", data.get("est_minutes", 0))),
            )
        except ValueError as exc:
            self._send_json(400, {"ok": False, "error": str(exc)})
            return
        self._send_json(200, self._tasks_payload())

    def _tasks_update(self):
        try:
            data = self._read_json_body()
        except json.JSONDecodeError:
            self._send_json(400, {"ok": False, "error": "Invalid request body."})
            return
        fields = dict(data.get("fields", {}) or {})
        if "est" in fields:  # accept a human string like "2h"
            fields["est_minutes"] = digest_tasks.parse_est(fields.pop("est"))
        digest_store.update_weekly_task(data.get("id", ""), fields)
        self._send_json(200, self._tasks_payload())

    def _tasks_delete(self):
        try:
            data = self._read_json_body()
        except json.JSONDecodeError:
            self._send_json(400, {"ok": False, "error": "Invalid request body."})
            return
        digest_store.delete_weekly_task(data.get("id", ""))
        self._send_json(200, self._tasks_payload())

    def _tasks_clear_done(self):
        # Remove completed tasks (keep open ones).
        items = digest_store.list_weekly_tasks()
        for t in items:
            if t.get("done"):
                digest_store.delete_weekly_task(t["id"])
        self._send_json(200, self._tasks_payload())

    def _digest_clear_category(self):
        try:
            data = self._read_json_body()
        except json.JSONDecodeError:
            self._send_json(400, {"ok": False, "error": "Invalid request body."})
            return
        category = (data.get("category") or "").strip()
        ok = digest_store.clear_category(category)
        if not ok:
            self._send_json(400, {"ok": False, "error": f"Unknown category: {category}"})
            return
        self._send_json(200, {"ok": True, "category": category})

    def _digest_process_replies(self):
        cfg = digest_store.load_config()
        try:
            result = digest_replies.process_replies(model=(cfg.get("model") or None))
        except Exception as exc:  # noqa: BLE001
            self._send_json(500, {"ok": False, "error": f"{type(exc).__name__}: {exc}"})
            return
        self._send_json(200, {"ok": True, **result})

    def _subtask_add(self):
        try:
            data = self._read_json_body()
        except json.JSONDecodeError:
            self._send_json(400, {"ok": False, "error": "Invalid request body."})
            return
        try:
            # parent_id may be a top-level task OR any nested subtask (arbitrary depth).
            parent = data.get("parent_id") or data.get("task_id", "")
            digest_store.add_subtask(parent, data.get("text", ""), data.get("due", ""))
        except ValueError as exc:
            self._send_json(400, {"ok": False, "error": str(exc)})
            return
        self._send_json(200, self._tasks_payload())

    def _subtask_update(self):
        try:
            data = self._read_json_body()
        except json.JSONDecodeError:
            self._send_json(400, {"ok": False, "error": "Invalid request body."})
            return
        node_id = data.get("id") or data.get("sub_id", "")
        digest_store.update_subtask(node_id, data.get("fields", {}))
        self._send_json(200, self._tasks_payload())

    def _subtask_delete(self):
        try:
            data = self._read_json_body()
        except json.JSONDecodeError:
            self._send_json(400, {"ok": False, "error": "Invalid request body."})
            return
        node_id = data.get("id") or data.get("sub_id", "")
        digest_store.delete_subtask(node_id)
        self._send_json(200, self._tasks_payload())

    def _memory_profile(self):
        try:
            data = self._read_json_body()
        except json.JSONDecodeError:
            self._send_json(400, {"ok": False, "error": "Invalid request body."})
            return
        digest_store.save_profile_base(data.get("text", "") if isinstance(data, dict) else "")
        self._send_json(200, self._memory_payload())

    def _memory_evolve(self):
        cfg = digest_store.load_config()
        try:
            result = digest_memory.evolve(model=(cfg.get("model") or None))
        except Exception as exc:  # noqa: BLE001
            self._send_json(500, {"ok": False, "error": f"{type(exc).__name__}: {exc}"})
            return
        payload = self._memory_payload()
        payload["evolve"] = result
        self._send_json(200, payload)

    def _digest_config(self):
        try:
            data = self._read_json_body()
        except json.JSONDecodeError:
            self._send_json(400, {"ok": False, "error": "Invalid request body."})
            return
        cfg = digest_store.save_config(data if isinstance(data, dict) else {})
        self._send_json(200, {"ok": True, "config": cfg,
                              "next_run": digest_engine.next_run_human(cfg)})

    def _digest_add_update(self):
        try:
            data = self._read_json_body()
        except json.JSONDecodeError:
            self._send_json(400, {"ok": False, "error": "Invalid request body."})
            return
        try:
            item = digest_store.add_update(data.get("text", ""))
        except ValueError as exc:
            self._send_json(400, {"ok": False, "error": str(exc)})
            return
        self._send_json(200, {"ok": True, "update": item,
                              "pending_count": len(digest_store.pending_updates())})

    def _digest_delete_update(self):
        try:
            data = self._read_json_body()
        except json.JSONDecodeError:
            self._send_json(400, {"ok": False, "error": "Invalid request body."})
            return
        ok = digest_store.delete_update(data.get("id", ""))
        self._send_json(200, {"ok": ok,
                              "pending_count": len(digest_store.pending_updates())})

    def _digest_preview(self):
        try:
            data = self._read_json_body()
        except json.JSONDecodeError:
            self._send_json(400, {"ok": False, "error": "Invalid request body."})
            return
        # Persist any inline-edited config first so the preview reflects it.
        if isinstance(data, dict) and data.get("config"):
            digest_store.save_config(data["config"])
        try:
            built = digest_engine.build_digest()
        except DigestLLMError as exc:
            self._send_json(502, {"ok": False, "error": f"LLM error: {exc}"})
            return
        except Exception as exc:  # noqa: BLE001
            traceback.print_exc()
            self._send_json(500, {"ok": False, "error": f"{type(exc).__name__}: {exc}"})
            return
        self._send_json(200, {
            "ok": True,
            "html": built["html"],
            "text": built["text"],
            "subject": built["subject"],
            "used_llm": built["used_llm"],
            "offline": built["offline"],
            "warning": built["warning"],
            "update_count": built["update_count"],
        })

    def _digest_send(self):
        try:
            data = self._read_json_body()
        except json.JSONDecodeError:
            self._send_json(400, {"ok": False, "error": "Invalid request body."})
            return
        if isinstance(data, dict) and data.get("config"):
            digest_store.save_config(data["config"])
        cfg = digest_store.load_config()
        if not (cfg.get("email_to") or "").strip():
            self._send_json(400, {"ok": False, "error": "Add a recipient email address first."})
            return
        try:
            built = digest_engine.send_now(cfg)
            # Mark today's slot so the scheduled senders don't also send today.
            digest_store.claim_send_slot(datetime.now().strftime("%Y-%m-%d"))
        except EmailError as exc:
            self._send_json(400, {"ok": False, "error": str(exc)})
            return
        except DigestLLMError as exc:
            self._send_json(502, {"ok": False, "error": f"LLM error: {exc}"})
            return
        except Exception as exc:  # noqa: BLE001
            traceback.print_exc()
            self._send_json(500, {"ok": False, "error": f"{type(exc).__name__}: {exc}"})
            return
        self._send_json(200, {
            "ok": True,
            "sent_to": built.get("sent_to", ""),
            "subject": built["subject"],
            "used_llm": built["used_llm"],
            "warning": built["warning"],
            "update_count": built["update_count"],
        })

    def _read_json_body(self):
        length = int(self.headers.get("Content-Length", 0) or 0)
        raw = self.rfile.read(length) if length else b""
        if not raw:
            return {}
        return json.loads(raw.decode("utf-8"))

    def _compile_tex(self):
        try:
            data = self._read_json_body()
        except json.JSONDecodeError:
            self._send_json(400, {"ok": False, "error": "Invalid request body."})
            return

        tex = data.get("tex") or ""
        if not isinstance(tex, str):
            self._send_json(400, {"ok": False, "error": "LaTeX must be a text string."})
            return

        try:
            result = core.compile_from_tex(tex)
        except CompileError as exc:
            self._send_json(400, {"ok": False, "error": str(exc)})
            return
        except core.PipelineError as exc:
            self._send_json(400, {"ok": False, "error": str(exc)})
            return
        except Exception as exc:  # noqa: BLE001
            traceback.print_exc()
            self._send_json(500, {"ok": False, "error": f"{type(exc).__name__}: {exc}"})
            return

        pdf_b64 = ""
        if result.pdf_path and Path(result.pdf_path).exists():
            pdf_b64 = base64.b64encode(Path(result.pdf_path).read_bytes()).decode("ascii")

        self._send_json(200, {
            "ok": True,
            "pages": result.pages,
            "warnings": result.warnings,
            "tex": result.tex,
            "pdf_base64": pdf_b64,
        })

    def _generate(self):
        try:
            data = self._read_json_body()
        except json.JSONDecodeError:
            self._send_json(400, {"ok": False, "error": "Invalid request body."})
            return

        jd_text = (data.get("jd_text") or "").strip()
        deterministic = bool(data.get("deterministic"))
        model = data.get("model") or None

        # Context can be pasted resume text or a profile JSON string (rebuilds profile).
        source_text = data.get("context_text") or data.get("profile") or ""
        if not isinstance(source_text, str):
            source_text = json.dumps(source_text)

        # Notes are incremental, truthful additions (e.g. gap answers); they augment
        # the stored context and never rebuild the profile.
        notes = data.get("notes") or ""
        if not isinstance(notes, str):
            notes = json.dumps(notes)

        # Instructions are high-priority directives on HOW to edit (not new facts).
        instructions = data.get("instructions") or ""
        if not isinstance(instructions, str):
            instructions = json.dumps(instructions)

        # Fresh pass re-optimizes from the base profile, ignoring the converged draft.
        fresh_pass = bool(data.get("fresh_pass"))

        # An optional PDF resume arrives base64-encoded.
        resume_pdf_bytes = None
        pdf_b64_in = data.get("resume_pdf_base64")
        if pdf_b64_in:
            try:
                resume_pdf_bytes = base64.b64decode(pdf_b64_in)
            except (ValueError, TypeError):
                self._send_json(400, {"ok": False, "error": "Could not decode the uploaded PDF."})
                return

        if not jd_text:
            self._send_json(400, {"ok": False, "error": "Please paste a job description."})
            return

        try:
            result = core.generate(
                jd_text=jd_text,
                source_text=source_text,
                resume_pdf_bytes=resume_pdf_bytes,
                notes=notes,
                instructions=instructions,
                fresh_pass=fresh_pass,
                deterministic=deterministic,
                model=model,
                do_compile=True,
            )
        except CompileError as exc:
            self._send_json(400, {"ok": False, "error": str(exc)})
            return
        except core.PipelineError as exc:
            self._send_json(400, {"ok": False, "error": str(exc)})
            return
        except llm.LLMError as exc:
            self._send_json(502, {"ok": False, "error": f"LLM error: {exc}"})
            return
        except Exception as exc:  # noqa: BLE001 - surface compile/other errors to the UI
            traceback.print_exc()
            self._send_json(500, {"ok": False, "error": f"{type(exc).__name__}: {exc}"})
            return

        pdf_b64 = ""
        if result.pdf_path and Path(result.pdf_path).exists():
            pdf_b64 = base64.b64encode(Path(result.pdf_path).read_bytes()).decode("ascii")

        self._send_json(200, {
            "ok": True,
            "pages": result.pages,
            "used_llm": result.used_llm,
            "deterministic": result.deterministic,
            "profile_source": result.profile_source,
            "profile_name": store.profile_name(),
            "context_used": result.context_used,
            "gaps": result.gaps,
            "summary": result.summary,
            "notes_saved": result.notes_saved,
            "diff": result.diff,
            "changed": result.changed,
            "font_pt": result.font_pt,
            "textheight_extra": result.textheight_extra,
            "textwidth_extra": result.textwidth_extra,
            "hit_floor": result.hit_floor,
            "warnings": result.warnings,
            "tex": result.tex,
            "pdf_base64": pdf_b64,
        })

    def log_message(self, fmt, *args):  # quieter logging
        return


def main(argv=None) -> int:
    core.load_dotenv(app_paths.env_path())
    p = argparse.ArgumentParser(description="Run the resume pipeline web UI.")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8765, help="Port to listen on (default 8765).")
    p.add_argument("port_pos", nargs="?", type=int, default=None,
                   help="Port as a positional arg, e.g. 'python3 server.py 8002' "
                        "(overrides --port).")
    args = p.parse_args(argv)

    want = args.port_pos if args.port_pos is not None else args.port

    # Bind the requested port, falling back to the next few if it's taken (so a
    # busy 8000/8765 from another project doesn't stop us).
    httpd = None
    for candidate in range(want, want + 10):
        try:
            httpd = ThreadingHTTPServer((args.host, candidate), Handler)
            port = candidate
            break
        except OSError:
            continue
    if httpd is None:
        print(f"Could not bind any port in {want}-{want + 9}.")
        return 1
    if port != want:
        print(f"Port {want} was busy; using {port} instead.")
    url = f"http://{args.host}:{port}"

    # Start the (isolated) daily-digest scheduler.
    from digest_pipeline import scheduler as digest_scheduler
    digest_scheduler.start()
    _dcfg = digest_store.load_config()

    print(f"ResumeForge UI running at {url}")
    print(f"  gateway: {os.environ.get(llm.BASE_URL_ENV) or llm.DEFAULT_BASE_URL}")
    print(f"  model:   {os.environ.get('ANTHROPIC_MODEL') or llm.DEFAULT_MODEL}")
    print(f"  profile: {'stored' if store.has_profile() else 'none (paste one in the UI)'}")
    print(f"  digest:  scheduler {'ON' if _dcfg.get('enabled') else 'off'}, "
          f"email {'configured' if digest_email.is_configured() else 'not configured'}, "
          f"next: {digest_engine.next_run_human(_dcfg)}")
    print("Press Ctrl+C to stop.")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping.")
        httpd.shutdown()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
