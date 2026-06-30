"""Google Calendar client (read events + upload schedule) using stdlib urllib.

Account-switchable and dependency-free: it authenticates with an OAuth2 refresh
token supplied via environment variables, so you can point it at ANY Google
account later just by changing the .env values (no code change):

  GOOGLE_CLIENT_ID
  GOOGLE_CLIENT_SECRET
  GOOGLE_REFRESH_TOKEN          (one-time consent; e.g. via OAuth Playground)
  GOOGLE_CALENDAR_ID            (default "primary")
  GOOGLE_TIMEZONE              (IANA name, default "America/New_York")

Until those are set, ``is_configured()`` is False and the feature stays inactive;
the rest of the digest works regardless.
"""

import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta

TOKEN_URL = "https://oauth2.googleapis.com/token"
API = "https://www.googleapis.com/calendar/v3"

_token_cache = {"access_token": None, "expires_at": 0}


class GCalError(RuntimeError):
    pass


def _cfg():
    return {
        "client_id": os.environ.get("GOOGLE_CLIENT_ID", "").strip(),
        "client_secret": os.environ.get("GOOGLE_CLIENT_SECRET", "").strip(),
        "refresh_token": os.environ.get("GOOGLE_REFRESH_TOKEN", "").strip(),
        "calendar_id": os.environ.get("GOOGLE_CALENDAR_ID", "primary").strip() or "primary",
        "timezone": os.environ.get("GOOGLE_TIMEZONE", "America/New_York").strip(),
    }


def is_configured() -> bool:
    c = _cfg()
    return bool(c["client_id"] and c["client_secret"] and c["refresh_token"])


def status() -> dict:
    c = _cfg()
    return {
        "configured": is_configured(),
        "calendar_id": c["calendar_id"],
        "timezone": c["timezone"],
        "account_hint": "set via GOOGLE_* env vars (switchable any time)",
    }


def _access_token() -> str:
    if not is_configured():
        raise GCalError("Google Calendar is not configured (set GOOGLE_* in .env).")
    now = time.time()
    if _token_cache["access_token"] and _token_cache["expires_at"] - 60 > now:
        return _token_cache["access_token"]
    c = _cfg()
    data = urllib.parse.urlencode({
        "client_id": c["client_id"],
        "client_secret": c["client_secret"],
        "refresh_token": c["refresh_token"],
        "grant_type": "refresh_token",
    }).encode("utf-8")
    req = urllib.request.Request(TOKEN_URL, data=data, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise GCalError(f"OAuth token refresh failed (HTTP {exc.code}): {detail}") from exc
    except urllib.error.URLError as exc:
        raise GCalError(f"Network error refreshing token: {exc.reason}") from exc
    tok = payload.get("access_token")
    if not tok:
        raise GCalError(f"No access_token in OAuth response: {payload}")
    _token_cache["access_token"] = tok
    _token_cache["expires_at"] = now + int(payload.get("expires_in", 3600))
    return tok


def _api(method: str, path: str, body: dict | None = None) -> dict:
    token = _access_token()
    url = f"{API}{path}"
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(url, data=data, method=method, headers={
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    })
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            raw = resp.read().decode("utf-8")
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise GCalError(f"Calendar API {method} {path} failed (HTTP {exc.code}): {detail}") from exc
    except urllib.error.URLError as exc:
        raise GCalError(f"Network error calling Calendar API: {exc.reason}") from exc


def list_events(day: datetime | None = None) -> list:
    """Return today's (or the given day's) events as [{summary, start, end, all_day}]."""
    c = _cfg()
    day = day or datetime.now()
    start = day.replace(hour=0, minute=0, second=0, microsecond=0)
    end = start + timedelta(days=1)
    params = urllib.parse.urlencode({
        "timeMin": start.astimezone().isoformat(),
        "timeMax": end.astimezone().isoformat(),
        "singleEvents": "true",
        "orderBy": "startTime",
    })
    cal = urllib.parse.quote(c["calendar_id"])
    payload = _api("GET", f"/calendars/{cal}/events?{params}")
    out = []
    for it in payload.get("items", []):
        s = it.get("start", {})
        e = it.get("end", {})
        out.append({
            "summary": it.get("summary", "(no title)"),
            "start": s.get("dateTime") or s.get("date", ""),
            "end": e.get("dateTime") or e.get("date", ""),
            "all_day": "date" in s,
        })
    return out


def render_events_text(events: list) -> str:
    lines = []
    for e in events:
        when = e["start"]
        # Trim ISO to HH:MM when it's a dateTime.
        if "T" in when:
            try:
                when = datetime.fromisoformat(when).strftime("%-I:%M %p")
            except (ValueError, TypeError):
                pass
        lines.append(f"  {when} - {e['summary']}")
    return "\n".join(lines)


def create_events_from_schedule(parsed: dict, base_date: datetime | None = None) -> dict:
    """Upload the parsed planner's events to the calendar. Returns a summary."""
    if not is_configured():
        raise GCalError("Google Calendar is not configured (set GOOGLE_* in .env).")
    c = _cfg()
    base_date = base_date or datetime.now()
    base_midnight = base_date.replace(hour=0, minute=0, second=0, microsecond=0)
    created, errors = 0, []
    for ev in parsed.get("events", []):
        start = base_midnight + timedelta(
            days=ev.get("day_offset", 0), hours=ev.get("hour24", 9), minutes=ev.get("minute", 0)
        )
        end = start + timedelta(minutes=ev.get("duration_min", 60))
        body = {
            "summary": ev.get("summary", "Task"),
            "description": ev.get("description", ""),
            "start": {"dateTime": start.isoformat(), "timeZone": c["timezone"]},
            "end": {"dateTime": end.isoformat(), "timeZone": c["timezone"]},
        }
        cal = urllib.parse.quote(c["calendar_id"])
        try:
            _api("POST", f"/calendars/{cal}/events", body)
            created += 1
        except GCalError as exc:
            errors.append(str(exc))
    return {"created": created, "errors": errors, "total": len(parsed.get("events", []))}
