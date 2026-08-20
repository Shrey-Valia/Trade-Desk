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
  * SMTPMailer — real delivery via smtplib per settings
    (smtp_host/port/username/password, mail_from). Supports both STARTTLS
    (port 587, the default) and implicit TLS / SMTPS (port 465, via
    smtp_ssl) because providers split roughly evenly between them.

Selection is settings.mail_provider ("console" | "smtp"); anything
unrecognized falls back to console so a typo can never silently drop mail
into a misconfigured relay.
"""

from __future__ import annotations

import logging
import smtplib
from email.message import EmailMessage
from email.utils import formatdate, make_msgid, parseaddr
from typing import Protocol

from config import settings

log = logging.getLogger(__name__)

# Sender domains that cannot receive or authenticate mail. The default
# mail_from is @tradedesk.local, which is fine for the console transport and
# poison for a real one: a .local From is unroutable, fails SPF/DKIM outright,
# and gets the message rejected or silently spam-foldered. Failing loudly at
# transport construction beats discovering it because no invitee can reset a
# password.
_UNROUTABLE_SENDER_TLDS = (".local", ".localhost", ".invalid", ".example", ".test")


class MailConfigError(RuntimeError):
    """SMTP transport asked for, but the configuration cannot deliver."""


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
    the stale-connection failure modes.

    Refuses to construct on a configuration that cannot deliver (no host, or
    an unroutable From domain), so the failure surfaces as a loud job error
    instead of mail that leaves and never arrives.
    """

    def __init__(self) -> None:
        if not settings.smtp_host.strip():
            raise MailConfigError(
                "MAIL_PROVIDER=smtp but SMTP_HOST is empty — set the relay "
                "host, or leave MAIL_PROVIDER=console. See docs/DEPLOYMENT.md."
            )
        _, addr = parseaddr(settings.mail_from)
        # rpartition returns the WHOLE string as the tail when there is no
        # separator, so an address with no "@" would otherwise sail through
        # looking like a plausible domain.
        local, at, domain = addr.rpartition("@")
        domain = domain.lower()
        if not at or not local or not domain or domain.endswith(
            _UNROUTABLE_SENDER_TLDS
        ):
            raise MailConfigError(
                f"MAIL_FROM={settings.mail_from!r} is not a deliverable sender "
                "(the default is @tradedesk.local). A real provider rejects or "
                "spam-folders an unroutable From, so every password reset would "
                "silently never arrive. Set MAIL_FROM to an address on a domain "
                "you control and have SPF/DKIM for."
            )

    def send(self, to: str, subject: str, body: str) -> None:
        msg = EmailMessage()
        msg["From"] = settings.mail_from
        msg["To"] = to
        msg["Subject"] = subject
        # RFC 5322 REQUIRES Date; smtplib does not add it and neither does
        # EmailMessage, so mail previously went out without one — a strong
        # spam signal that some providers reject outright. Message-ID is not
        # required but its absence is scored against you, and it is what makes
        # a delivery traceable in provider logs.
        msg["Date"] = formatdate(localtime=True)
        msg["Message-ID"] = make_msgid(
            domain=parseaddr(settings.mail_from)[1].rpartition("@")[2] or None
        )
        msg.set_content(body)

        if settings.smtp_ssl:
            # Implicit TLS (SMTPS, usually 465): the socket is wrapped before
            # the greeting, so no STARTTLS upgrade happens or is needed.
            with smtplib.SMTP_SSL(
                settings.smtp_host, settings.smtp_port, timeout=30
            ) as smtp:
                self._auth_and_send(smtp, msg)
            return
        with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=30) as smtp:
            if settings.smtp_starttls:
                smtp.starttls()
            self._auth_and_send(smtp, msg)

    @staticmethod
    def _auth_and_send(smtp, msg: EmailMessage) -> None:
        if settings.smtp_username:
            smtp.login(settings.smtp_username, settings.smtp_password)
        smtp.send_message(msg)


def get_mailer() -> Mailer:
    """Select the transport from settings.mail_provider. Called per outbox
    run (not cached) so a settings change takes effect without a restart."""
    if settings.mail_provider.strip().lower() == "smtp":
        return SMTPMailer()
    return ConsoleMailer()
