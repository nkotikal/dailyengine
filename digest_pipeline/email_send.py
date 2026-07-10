"""SMTP email delivery for the Daily Digest (stdlib only).

Configured entirely through environment variables (keep secrets out of the UI/JSON):
  SMTP_HOST        - e.g. smtp.gmail.com   (required to send)
  SMTP_PORT        - default 587
  SMTP_USER        - login username (often your email address)
  SMTP_PASSWORD    - login password / app password
  SMTP_FROM        - From: address (defaults to SMTP_USER)
  SMTP_FROM_NAME   - display name (default "Daily Digest")
  SMTP_SECURITY    - starttls (default) | ssl | none
"""

import os
import smtplib
import ssl
from email.message import EmailMessage
from email.utils import formataddr, formatdate


class EmailError(RuntimeError):
    pass


def _cfg():
    return {
        "host": os.environ.get("SMTP_HOST", "").strip(),
        "port": int(os.environ.get("SMTP_PORT", "587") or "587"),
        "user": os.environ.get("SMTP_USER", "").strip(),
        "password": os.environ.get("SMTP_PASSWORD", ""),
        "from_addr": (os.environ.get("SMTP_FROM") or os.environ.get("SMTP_USER") or "").strip(),
        "from_name": os.environ.get("SMTP_FROM_NAME", "Daily Digest"),
        "security": os.environ.get("SMTP_SECURITY", "starttls").strip().lower(),
    }


def is_configured() -> bool:
    c = _cfg()
    return bool(c["host"] and c["from_addr"])


def from_address() -> str:
    """The address replies come back to (used to build one-tap mailto: links)."""
    return _cfg()["from_addr"]


def config_summary() -> dict:
    """Non-sensitive view of the email setup for the UI."""
    c = _cfg()
    return {
        "configured": is_configured(),
        "host": c["host"],
        "port": c["port"],
        "from": c["from_addr"],
        "security": c["security"],
        "has_password": bool(c["password"]),
    }


def send_email(*, to_addr: str, subject: str, html: str, text: str) -> None:
    to_addr = (to_addr or "").strip()
    if not to_addr:
        raise EmailError("No recipient address set. Add one in the digest settings.")
    c = _cfg()
    if not c["host"]:
        raise EmailError(
            "Email is not configured. Set SMTP_HOST (and SMTP_USER/SMTP_PASSWORD) in .env."
        )

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = formataddr((c["from_name"], c["from_addr"]))
    msg["To"] = to_addr
    msg["Reply-To"] = c["from_addr"]  # replies come back to the digest mailbox
    msg["Date"] = formatdate(localtime=True)
    msg.set_content(text or "Your daily digest.")
    msg.add_alternative(html or "<p>Your daily digest.</p>", subtype="html")

    try:
        if c["security"] == "ssl":
            ctx = ssl.create_default_context()
            with smtplib.SMTP_SSL(c["host"], c["port"], context=ctx, timeout=30) as s:
                _login_and_send(s, c, msg)
        else:
            with smtplib.SMTP(c["host"], c["port"], timeout=30) as s:
                s.ehlo()
                if c["security"] != "none":
                    s.starttls(context=ssl.create_default_context())
                    s.ehlo()
                _login_and_send(s, c, msg)
    except (smtplib.SMTPException, OSError) as exc:
        raise EmailError(f"Failed to send email: {exc}") from exc


def _login_and_send(server, c, msg) -> None:
    if c["user"] and c["password"]:
        server.login(c["user"], c["password"])
    server.send_message(msg)
