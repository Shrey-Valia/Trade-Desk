"""Real SMTP delivery: message validity, transport config, and retry policy.

Every test here corresponds to a way the FIRST real send would have failed
or silently lost mail:

  * the message went on the wire with no Date and no Message-ID. RFC 5322
    REQUIRES Date; its absence is a strong spam signal and some providers
    reject outright. Verified against a real socket, not by reading code —
    smtplib does not add either header and neither does EmailMessage.
  * MAIL_FROM defaulted to @tradedesk.local. A real provider cannot deliver
    an unroutable From, so every password reset would have vanished into
    spam with no error anywhere.
  * retries fired at the job's 30s cadence, exhausting all five attempts
    ~2.5 minutes after the first failure — a brief provider outage
    PERMANENTLY dropped whatever was queued.
  * a permanent 5xx refusal was retried for hours like a transient blip.
"""

from __future__ import annotations

import smtplib
import socket
import threading
from datetime import UTC, datetime, timedelta
from email import message_from_string

import pytest
from sqlalchemy import select

from config import settings
from jobs.send_outbox import _BACKOFF, _is_permanent, send_outbox
from models.notification import EmailOutbox
from services.mailer import MailConfigError, SMTPMailer, get_mailer
from services.notify import enqueue_email

# -- a real SMTP sink -------------------------------------------------------


class _Sink:
    """Minimal SMTP server on localhost that captures one message.

    Deliberately a real socket: the bug this pins was invisible to any
    assertion about EmailMessage objects, because it was smtplib's
    serialization that omitted the headers.
    """

    def __init__(self):
        self.srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.srv.bind(("127.0.0.1", 0))
        self.srv.listen(1)
        self.port = self.srv.getsockname()[1]
        self.raw: str | None = None
        self.thread = threading.Thread(target=self._serve, daemon=True)
        self.thread.start()

    def _serve(self):
        conn, _ = self.srv.accept()
        f = conn.makefile("rb")
        conn.sendall(b"220 sink ESMTP\r\n")
        body, in_data = [], False
        while True:
            line = f.readline()
            if not line:
                break
            if in_data:
                if line.strip() == b".":
                    in_data = False
                    self.raw = b"".join(body).decode(errors="replace")
                    conn.sendall(b"250 OK queued\r\n")
                    continue
                body.append(line)
                continue
            up = line.decode(errors="replace").strip().upper()
            if up.startswith(("EHLO", "HELO")):
                conn.sendall(b"250-sink\r\n250 SIZE 10240000\r\n")
            elif up.startswith(("MAIL FROM", "RCPT TO")):
                conn.sendall(b"250 OK\r\n")
            elif up.startswith("DATA"):
                in_data = True
                conn.sendall(b"354 End data\r\n")
            elif up.startswith("QUIT"):
                conn.sendall(b"221 Bye\r\n")
                break
            else:
                conn.sendall(b"250 OK\r\n")
        conn.close()
        self.srv.close()


@pytest.fixture
def sink(monkeypatch):
    s = _Sink()
    monkeypatch.setattr(settings, "smtp_host", "127.0.0.1")
    monkeypatch.setattr(settings, "smtp_port", s.port)
    monkeypatch.setattr(settings, "smtp_starttls", False)
    monkeypatch.setattr(settings, "smtp_ssl", False)
    monkeypatch.setattr(settings, "smtp_username", "")
    monkeypatch.setattr(settings, "mail_from", "Trade Desk <no-reply@tradedesk.io>")
    yield s


# -- the message is RFC-valid ----------------------------------------------


def test_wire_message_has_date_and_message_id(sink):
    """The original bug, pinned at the level it actually occurred: bytes on
    a socket."""
    SMTPMailer().send("trader@example.com", "Reset your password", "link")
    sink.thread.join(timeout=5)
    assert sink.raw is not None, "sink captured nothing"

    msg = message_from_string(sink.raw)
    assert msg["Date"], "RFC 5322 requires Date; providers spam-folder without it"
    assert msg["Message-ID"], "absence is scored against deliverability"
    # Message-ID must be scoped to the sending domain, not the local hostname.
    assert msg["Message-ID"].rstrip(">").endswith("tradedesk.io")
    assert msg["Subject"] == "Reset your password"
    assert msg["To"] == "trader@example.com"


# -- unshippable configuration fails LOUDLY --------------------------------


def test_unroutable_mail_from_is_refused(monkeypatch):
    """The shipped default. Silently spam-foldering every reset is worse
    than refusing to start the transport."""
    monkeypatch.setattr(settings, "smtp_host", "smtp.example.net")
    monkeypatch.setattr(settings, "mail_from", "Trade Desk <no-reply@tradedesk.local>")
    with pytest.raises(MailConfigError, match="not a deliverable sender"):
        SMTPMailer()


@pytest.mark.parametrize(
    "addr",
    [
        "a@host.localhost",
        "a@thing.invalid",
        "a@foo.example",
        "a@bar.test",
        "no-at-sign",
    ],
)
def test_other_undeliverable_senders_refused(monkeypatch, addr):
    monkeypatch.setattr(settings, "smtp_host", "smtp.example.net")
    monkeypatch.setattr(settings, "mail_from", addr)
    with pytest.raises(MailConfigError):
        SMTPMailer()


def test_missing_smtp_host_is_refused(monkeypatch):
    monkeypatch.setattr(settings, "smtp_host", "  ")
    monkeypatch.setattr(settings, "mail_from", "a@tradedesk.io")
    with pytest.raises(MailConfigError, match="SMTP_HOST is empty"):
        SMTPMailer()


def test_console_provider_never_validates(monkeypatch):
    """Dev must keep working with the .local default untouched."""
    monkeypatch.setattr(settings, "mail_provider", "console")
    monkeypatch.setattr(settings, "mail_from", "Trade Desk <no-reply@tradedesk.local>")
    mailer = get_mailer()
    mailer.send("x@test.local", "s", "b")  # logs, raises nothing


def test_unrecognised_provider_falls_back_to_console(monkeypatch):
    """A typo must not silently drop mail into a misconfigured relay."""
    monkeypatch.setattr(settings, "mail_provider", "sendgrid-ish-typo")
    assert type(get_mailer()).__name__ == "ConsoleMailer"


# -- retry policy -----------------------------------------------------------


def test_transient_failure_schedules_backoff(session_factory, monkeypatch):
    """The lost-password-reset bug: retries must be spaced by _BACKOFF, not
    by the 30s job cadence."""

    class _Boom:
        def send(self, *a):
            raise TimeoutError("connection timed out")

    s = session_factory()
    enqueue_email(s, "x@test.local", "password_reset", "Reset", "link")
    s.commit()
    s.close()
    monkeypatch.setattr("services.mailer.get_mailer", lambda: _Boom())

    before = datetime.now(UTC)
    assert send_outbox(session_factory=session_factory) == {"sent": 0, "failed": 0}

    check = session_factory()
    row = check.execute(select(EmailOutbox)).scalar_one()
    assert row.status == "queued"
    assert row.next_attempt_at is not None
    # First backoff step, with slack for execution time.
    assert row.next_attempt_at >= before + _BACKOFF[0] - timedelta(seconds=5)
    check.close()


def test_permanent_refusal_fails_without_burning_attempts(
    session_factory, monkeypatch
):
    """A 550 will refuse identically forever. Sitting in the queue for hours
    only delays the operator noticing."""
    s = session_factory()
    enqueue_email(s, "nobody@test.local", "payout_paid", "Paid", "body")
    s.commit()
    s.close()
    mailer = RefusingMailerLocal()
    monkeypatch.setattr("services.mailer.get_mailer", lambda: mailer)
    monkeypatch.setattr(settings, "mail_max_attempts", 5)

    assert send_outbox(session_factory=session_factory) == {"sent": 0, "failed": 1}

    check = session_factory()
    row = check.execute(select(EmailOutbox)).scalar_one()
    assert row.status == "failed"
    assert row.attempts == 1, "must not consume the whole retry budget"
    check.close()
    # And never retried.
    assert send_outbox(session_factory=session_factory) == {"sent": 0, "failed": 0}
    assert mailer.calls == 1


class RefusingMailerLocal:
    def __init__(self):
        self.calls = 0

    def send(self, to, subject, body):
        self.calls += 1
        raise smtplib.SMTPRecipientsRefused({to: (550, b"No such user")})


@pytest.mark.parametrize(
    "exc,expected",
    [
        (smtplib.SMTPRecipientsRefused({"a@b.c": (550, b"nope")}), True),
        (smtplib.SMTPResponseException(550, "rejected"), True),
        (smtplib.SMTPResponseException(451, "try later"), False),
        (smtplib.SMTPResponseException(421, "too busy"), False),
        (TimeoutError("timeout"), False),
        (ConnectionRefusedError("refused"), False),
        (RuntimeError("who knows"), False),
    ],
)
def test_permanence_classification(exc, expected):
    """4xx and unknown errors must be treated as transient — guessing
    "permanent" on a blip throws mail away."""
    assert _is_permanent(exc) is expected


def test_legacy_rows_with_null_next_attempt_are_eligible(
    session_factory, monkeypatch
):
    """Rows queued before the column existed read NULL and must still send."""
    sent = []

    class _Ok:
        def send(self, to, subject, body):
            sent.append(to)

    s = session_factory()
    row = EmailOutbox(
        to_email="legacy@test.local",
        template="t",
        subject="s",
        body="b",
        status="queued",
        next_attempt_at=None,
    )
    s.add(row)
    s.commit()
    s.close()
    monkeypatch.setattr("services.mailer.get_mailer", lambda: _Ok())

    assert send_outbox(session_factory=session_factory) == {"sent": 1, "failed": 0}
    assert sent == ["legacy@test.local"]
