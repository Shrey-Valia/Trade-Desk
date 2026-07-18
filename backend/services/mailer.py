"""Provider-agnostic transactional mail transport.

The outbox job (jobs/send_outbox.py) is the ONLY caller — request paths
never send mail directly; they enqueue EmailOutbox rows via
services/notify.py and this transport drains them. `send` raises on any
failure so the job can track attempts / last_error and retry.

Providers:
  * ConsoleMailer (default) — "sends" by logging the fully rendered mail
    at INFO. Dev/demo posture: nothing leaves the box, and the rendered
    body (including password-reset links) is visible in the server log,
    which is exactly how you complete the flow locally.
  * SMTPMailer — real delivery via smtplib + STARTTLS per settings
    (smtp_host/port/username/password, mail_from).

Selection is settings.mail_provider ("console" | "smtp"); anything
unrecognized falls back to console so a typo can never silently drop mail
into a misconfigured relay.
"""

from __future__ import annotations

import logging
import smtplib
from email.message import EmailMessage
from typing import Protocol

from config import settings

log = logging.getLogger(__name__)


class Mailer(Protocol):
    def send(self, to: str, subject: str, body: str) -> None:
        """Deliver one message. Raises on failure (never returns an error)."""
        ...


class ConsoleMailer:
    """Dev-default transport: log the rendered mail instead of sending it."""

    def send(self, to: str, subject: str, body: str) -> None:
        log.info(
            "MAIL (console) to=%s subject=%r\n%s",
            to,
            subject,
            body,
        )


class SMTPMailer:
    """Real SMTP delivery. A connection is opened per send — the outbox
    drains at most ~50 mails per 30s run, so connection reuse isn't worth
    the stale-connection failure modes."""

    def send(self, to: str, subject: str, body: str) -> None:
        msg = EmailMessage()
        msg["From"] = settings.mail_from
        msg["To"] = to
        msg["Subject"] = subject
        msg.set_content(body)
        with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=30) as smtp:
            if settings.smtp_starttls:
                smtp.starttls()
            if settings.smtp_username:
                smtp.login(settings.smtp_username, settings.smtp_password)
            smtp.send_message(msg)


def get_mailer() -> Mailer:
    """Select the transport from settings.mail_provider. Called per outbox
    run (not cached) so a settings change takes effect without a restart."""
    if settings.mail_provider.strip().lower() == "smtp":
        return SMTPMailer()
    return ConsoleMailer()
