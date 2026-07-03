"""Tiny OpenAI-compatible chat client (stdlib only) used as a fallback provider.

Both the digest and the resume pipeline route here when an OpenAI model is selected
(or when the primary AMD gateway is unreachable). Configure via env:
  OPENAI_API_KEY   - required to use it
  OPENAI_BASE_URL  - default https://api.openai.com/v1 (any OpenAI-compatible endpoint)
"""

import json
import os
import socket
import urllib.error
import urllib.parse
import urllib.request

KEY_ENV = "OPENAI_API_KEY"
BASE_ENV = "OPENAI_BASE_URL"
DEFAULT_BASE = "https://api.openai.com/v1"


class OpenAIError(RuntimeError):
    pass


def configured() -> bool:
    return bool(os.environ.get(KEY_ENV))


def _base() -> str:
    return (os.environ.get(BASE_ENV) or DEFAULT_BASE).rstrip("/")


def reachable(timeout: int = 4) -> bool:
    host = urllib.parse.urlparse(_base()).hostname
    if not host:
        return False
    try:
        socket.setdefaulttimeout(timeout)
        socket.getaddrinfo(host, 443)
        return True
    except OSError:
        return False


def _extract_json(text: str) -> dict:
    cleaned = (text or "").strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.split("\n", 1)[-1]
        if cleaned.rstrip().endswith("```"):
            cleaned = cleaned.rstrip()[:-3]
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        s, e = cleaned.find("{"), cleaned.rfind("}")
        if s != -1 and e > s:
            return json.loads(cleaned[s:e + 1])
        raise OpenAIError("OpenAI output was not valid JSON.")


def post_json(system: str, user: str, *, model: str, temperature: float = 0.3,
              max_tokens: int = 2048, timeout: int = 120) -> dict:
    """Chat-completions call that returns a parsed JSON object."""
    key = os.environ.get(KEY_ENV)
    if not key:
        raise OpenAIError(f"{KEY_ENV} is not set.")
    body = {
        "model": model,
        "messages": [{"role": "system", "content": system},
                     {"role": "user", "content": user}],
        "temperature": temperature,
        "max_tokens": max_tokens,
        "response_format": {"type": "json_object"},
    }
    req = urllib.request.Request(
        _base() + "/chat/completions",
        data=json.dumps(body).encode("utf-8"), method="POST",
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise OpenAIError(f"OpenAI HTTP {exc.code}: {detail}") from exc
    except urllib.error.URLError as exc:
        raise OpenAIError(f"Network error calling OpenAI: {exc.reason}") from exc
    try:
        content = payload["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise OpenAIError(f"Unexpected OpenAI response: {payload}") from exc
    return _extract_json(content)
