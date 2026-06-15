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

from resume_pipeline import compile as texc
from resume_pipeline.compile import CompileError
from resume_pipeline import core, llm, store

ROOT = Path(__file__).resolve().parent
WEB = ROOT / "web"

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
        elif self.path.startswith("/static/"):
            self._serve_file(self.path[len("/static/"):])
        elif self.path in ("/styles.css", "/app.js"):
            self._serve_file(self.path.lstrip("/"))
        else:
            self._send(404, "Not found", "text/plain; charset=utf-8")

    def do_POST(self):
        if self.path == "/api/generate":
            self._generate()
        elif self.path == "/api/reset":
            self._reset()
        elif self.path == "/api/compile":
            self._compile_tex()
        else:
            self._send(404, "Not found", "text/plain; charset=utf-8")

    # -- endpoints ----------------------------------------------------------

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
    core.load_dotenv()
    p = argparse.ArgumentParser(description="Run the resume pipeline web UI.")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8000)
    args = p.parse_args(argv)

    httpd = ThreadingHTTPServer((args.host, args.port), Handler)
    url = f"http://{args.host}:{args.port}"
    print(f"ResumeForge UI running at {url}")
    print(f"  gateway: {os.environ.get(llm.BASE_URL_ENV) or llm.DEFAULT_BASE_URL}")
    print(f"  model:   {os.environ.get('ANTHROPIC_MODEL') or llm.DEFAULT_MODEL}")
    print(f"  profile: {'stored' if store.has_profile() else 'none (paste one in the UI)'}")
    print("Press Ctrl+C to stop.")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping.")
        httpd.shutdown()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
