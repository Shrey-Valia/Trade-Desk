#!/usr/bin/env python3
"""Send ONE real email through the configured SMTP transport, or explain why
the config can't deliver. The mail equivalent of scripts/check_keys.py.

  backend/.venv/bin/python backend/scripts/send_test_email.py you@yourdomain.com

Run it from the REPO ROOT so the .env beside docker-compose.yml is the one
loaded. Prints the resolved configuration first — credentials are shown only
as "set"/"unset", never echoed.

THIS ACTUALLY SENDS MAIL. It is the only way to learn what a provider does
with your From domain, your SPF/DKIM records and your credentials; a unit
test cannot tell you that your DNS is wrong. Check the spam folder too — a
message that arrives but is filtered is a failure worth knowing about, and
it is the single most likely outcome of an unverified sending domain.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import settings  # noqa: E402


def main() -> int:
    if len(sys.argv) != 2:
        print(__doc__)
        return 2
    to = sys.argv[1]

    print("Resolved mail configuration")
    print(f"  MAIL_PROVIDER  : {settings.mail_provider}")
    print(f"  MAIL_FROM      : {settings.mail_from}")
    print(f"  SMTP_HOST      : {settings.smtp_host or '(unset)'}")
    print(f"  SMTP_PORT      : {settings.smtp_port}")
    print(f"  SMTP_STARTTLS  : {settings.smtp_starttls}")
    print(f"  SMTP_SSL       : {settings.smtp_ssl}")
    print(f"  SMTP_USERNAME  : {'set' if settings.smtp_username else '(unset)'}")
    print(f"  SMTP_PASSWORD  : {'set' if settings.smtp_password else '(unset)'}")
    print()

    if settings.mail_provider.strip().lower() != "smtp":
        print(
            "MAIL_PROVIDER is not 'smtp', so mail would be LOGGED, not sent.\n"
            "Set MAIL_PROVIDER=smtp to test real delivery."
        )
        return 1

    from services.mailer import MailConfigError, SMTPMailer

    try:
        mailer = SMTPMailer()
    except MailConfigError as exc:
        print(f"[FAIL] configuration cannot deliver:\n  {exc}")
        return 1

    subject = "Trade Desk — SMTP test"
    body = (
        "If you are reading this, the transactional mail path works.\n\n"
        "This is the same transport that carries password resets and payout "
        "notifications. If it landed in spam, the sending domain still needs "
        "SPF/DKIM before you invite anyone.\n"
    )
    try:
        mailer.send(to, subject, body)
    except Exception as exc:  # noqa: BLE001 — report, don't traceback
        print(f"[FAIL] send raised {type(exc).__name__}: {exc}")
        print(
            "\nCommon causes: wrong port for the TLS mode (587 = STARTTLS, "
            "465 = SMTP_SSL=1), credentials not yet verified by the provider, "
            "or a From domain the provider will not authorise."
        )
        return 1

    print(f"[OK] accepted for delivery to {to}")
    print("Now check the inbox AND the spam folder.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
