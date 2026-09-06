"""Production configuration preflight: say out loud what this deployment is.

WHY THIS EXISTS: every serious near-miss this project has had came from
configuration, not code. The demo dry-run nearly died because `ADMIN_EMAILS`
was empty and the operator console 403'd. The container smoke test found the
session cookie shipping without `Secure` because compose had erased
`APP_ENV`. `MAIL_FROM` defaulted to an unroutable `.local` domain. In every
case the app booted happily and looked fine — the defaults that are right
for a laptop are wrong for a deployment, and nothing ever said so.

So this runs once at startup under `APP_ENV=production` and reports, in one
block, every setting whose value means something different in a deployment
than it does on a laptop.

TWO LEVELS, and the split is deliberate:

  REFUSE — boot stops. Reserved for configurations that are silently
    destructive or that make a user-facing flow impossible to complete. A
    refusal that fires on a merely-risky setting is worse than the setting:
    it turns a running deployment into an outage on the next restart. There
    is exactly one refusal here (plus the RELATIVE-sqlite-path refusal in
    database.py, which predates this module).

  WARN — logged loudly, and surfaced to the operator console via
    GET /api/admin/preflight, but the app serves. Everything that is a
    posture choice rather than a broken flow.

Nothing here fires outside production: a dev box and the test suite see an
empty finding list, because on a laptop every one of these defaults is the
right answer.
"""

from __future__ import annotations

import logging
import os
from typing import Literal, NamedTuple
from urllib.parse import urlparse

from config import settings

log = logging.getLogger(__name__)

Level = Literal["refuse", "warn"]

# Hosts an emailed link can never be opened from by a recipient. The same
# reasoning as services/mailer.py's unroutable-sender check, applied to the
# other end of the flow.
_UNROUTABLE_HOSTS = ("localhost", "127.0.0.1", "0.0.0.0", "::1", "")
_UNROUTABLE_TLDS = (".local", ".localhost", ".invalid", ".example", ".test")


class Finding(NamedTuple):
    level: Level
    key: str
    problem: str
    fix: str

    def render(self) -> str:
        return f"[{self.level.upper()}] {self.key}: {self.problem} → {self.fix}"


def _host_is_unroutable(url: str) -> bool:
    host = (urlparse(url).hostname or "").lower()
    return host in _UNROUTABLE_HOSTS or host.endswith(_UNROUTABLE_TLDS)


def _on_fly() -> bool:
    """Fly sets these in every machine. Used only to sharpen advice that is
    otherwise unknowable from config alone (e.g. there IS a proxy in front)."""
    return bool(os.environ.get("FLY_APP_NAME") or os.environ.get("FLY_MACHINE_ID"))


def check_config(*, on_fly: bool | None = None) -> list[Finding]:
    """Every production-posture finding, worst first. Empty outside production.

    Pure: reads settings and the environment, touches nothing. `on_fly` is
    injectable so tests don't have to fake Fly's environment variables.
    """
    if not settings.is_production:
        return []
    fly = _on_fly() if on_fly is None else on_fly
    findings: list[Finding] = []

    # -- REFUSE -------------------------------------------------------------
    # Real mail with a localhost app URL. Every link the app sends —
    # password reset, admin-minted reset, payout status — is built from
    # frontend_base_url, so this combination sends real recipients a URL that
    # resolves to their OWN machine. The mail is delivered, nothing errors,
    # and the account is simply unrecoverable. Refusing is safe here because
    # it can only fire when someone has deliberately configured real mail.
    if settings.mail_provider.strip().lower() != "console" and _host_is_unroutable(
        settings.frontend_base_url
    ):
        findings.append(
            Finding(
                "refuse",
                "FRONTEND_BASE_URL",
                f"real mail is enabled (MAIL_PROVIDER={settings.mail_provider!r}) but "
                f"links would point at {settings.frontend_base_url!r}, which no "
                "recipient can open — every password reset would be undeliverable "
                "in the only way that still looks like success",
                "set FRONTEND_BASE_URL to the app's public origin "
                "(e.g. https://trade-desk.fly.dev)",
            )
        )

    # -- WARN ---------------------------------------------------------------
    if not settings.admin_emails:
        findings.append(
            Finding(
                "warn",
                "ADMIN_EMAILS",
                "empty, so no account is auto-promoted at signin and /admin 403s "
                "for everyone — there is no operator seat and no way to mint one "
                "through the UI",
                'set ADMIN_EMAILS to a JSON array, e.g. ["you@example.com"], and '
                "sign in once to claim it",
            )
        )

    if not settings.signup_require_invite:
        findings.append(
            Finding(
                "warn",
                "SIGNUP_REQUIRE_INVITE",
                "off, so POST /api/auth/signup is open to the public internet",
                "set SIGNUP_REQUIRE_INVITE=1 for the invite-only posture, or leave "
                "it off deliberately",
            )
        )

    if settings.mail_provider.strip().lower() == "console":
        findings.append(
            Finding(
                "warn",
                "MAIL_PROVIDER",
                "'console': every transactional mail is written to stdout instead "
                "of sent, so a user who forgets their password recovers only by an "
                "operator fishing the token out of the logs",
                "set MAIL_PROVIDER=smtp with MAIL_FROM and the SMTP_* secrets in "
                "the same command, then add SPF+DKIM for the sending domain",
            )
        )

    if settings.payout_auto_approve:
        findings.append(
            Finding(
                "warn",
                "PAYOUT_AUTO_APPROVE",
                "explicitly ON in production: a requested payout approves itself "
                f"after {settings.payout_review_window_h}h with reviewer_id=None — "
                "real money leaving on a timer, with no human in the audit trail",
                "unset it (production then defaults to OFF) or set "
                "PAYOUT_AUTO_APPROVE=0",
            )
        )

    if settings.kyc_auto_verify:
        findings.append(
            Finding(
                "warn",
                "KYC_AUTO_VERIFY",
                "explicitly ON in production: identity submissions are decided by "
                "the simulated provider, so everyone outside the OFAC list is "
                "verified instantly and no human ever sees a document",
                "unset it (production then defaults to OFF) or set KYC_AUTO_VERIFY=0",
            )
        )

    if not settings.sentry_dsn:
        findings.append(
            Finding(
                "warn",
                "SENTRY_DSN",
                "unset, so an unhandled exception — including a scheduled job "
                "dying — is invisible outside the container's logs",
                "fly secrets set SENTRY_DSN=… (see docs/DEPLOYMENT.md)",
            )
        )

    provider = (settings.backup_offsite_provider or "none").strip().lower()
    if provider in ("", "none", "off", "disabled"):
        findings.append(
            Finding(
                "warn",
                "BACKUP_OFFSITE_PROVIDER",
                "'none': nightly backups are written beside the live database on "
                "the same volume, so one lost volume takes the database and every "
                "backup of it together",
                "configure a bucket — docs/DEPLOYMENT.md → 'Offsite copies'",
            )
        )

    if not settings.cookie_secure:
        findings.append(
            Finding(
                "warn",
                "COOKIE_SECURE",
                "explicitly off in production: the session cookie is sent over "
                "plain HTTP, which is a session-theft hole on any shared network",
                "unset COOKIE_SECURE (production then defaults to on)",
            )
        )

    if fly and not settings.trust_proxy:
        findings.append(
            Finding(
                "warn",
                "TRUST_PROXY",
                "off while running behind Fly's proxy, so every request appears to "
                "come from the proxy — the auth brute-force throttle is keyed on "
                "one IP for all users and effectively rate-limits the whole app",
                "set TRUST_PROXY=1 (correct ONLY behind a proxy that appends the "
                "real client IP, which Fly does)",
            )
        )

    if not fly and settings.trust_proxy:
        findings.append(
            Finding(
                "warn",
                "TRUST_PROXY",
                "on with no detected proxy: X-Forwarded-For is client-controlled, "
                "so an attacker can rotate the header to walk past the auth "
                "throttle entirely",
                "set TRUST_PROXY=0 unless something really does sit in front",
            )
        )

    order = {"refuse": 0, "warn": 1}
    findings.sort(key=lambda f: order[f.level])
    return findings


class PreflightError(RuntimeError):
    """A production configuration that cannot work. Raised at startup."""


def run_preflight(*, on_fly: bool | None = None) -> list[Finding]:
    """Called once from the lifespan. Logs everything, raises on a refusal.

    Returns the findings so the caller (and the admin endpoint) can show
    them; the log block is the copy an operator reads in `fly logs` right
    after a deploy, which is the moment these are cheapest to fix.
    """
    findings = check_config(on_fly=on_fly)
    if not findings:
        if settings.is_production:
            log.info("preflight: production configuration looks complete")
        return findings

    refusals = [f for f in findings if f.level == "refuse"]
    warnings = [f for f in findings if f.level == "warn"]

    if warnings:
        log.warning(
            "preflight: %d production configuration warning(s) —\n  %s",
            len(warnings),
            "\n  ".join(f.render() for f in warnings),
        )
    if refusals:
        detail = "\n  ".join(f.render() for f in refusals)
        raise PreflightError(
            f"refusing to start: {len(refusals)} production configuration "
            f"error(s) —\n  {detail}\n"
            "See docs/DEPLOYMENT.md. Set APP_ENV to something other than "
            "'production' only if this really is not a deployment."
        )
    return findings
