"""services/preflight — the production configuration check.

Two things are being pinned here, and the second matters more than the first:

  1. that each finding fires on the configuration it describes; and
  2. that the REFUSE/WARN split doesn't drift. A refusal that starts firing
     on a merely-risky setting turns the next restart of a healthy
     deployment into an outage, so the set of refusals is asserted
     exhaustively rather than one case at a time.

Every test forces APP_ENV explicitly. Nothing here may fire outside
production — the whole suite runs in development, where all of these
defaults are correct.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from config import settings
from main import app
from services.preflight import Finding, PreflightError, check_config, run_preflight


@pytest.fixture
def admin_client(api_client, monkeypatch):
    """An authenticated admin on the same database, bootstrapped through the
    admin_emails allowlist — the same pattern tests/test_admin.py uses."""
    monkeypatch.setattr(settings, "admin_emails", ("admin@test.local",))
    c = TestClient(app)
    c.post(
        "/api/auth/signup",
        json={"email": "admin@test.local", "password": "test-password-123"},
    )
    # /me applies the allowlist promotion, so the role is persisted before a
    # test clears admin_emails to provoke that very finding.
    assert c.get("/api/auth/me").json()["role"] == "admin"
    return c


@pytest.fixture
def prod(monkeypatch):
    """A production deployment configured the way a careful operator would:
    every finding silent. Individual tests break one thing at a time."""
    monkeypatch.setattr(settings, "app_env", "production")
    monkeypatch.setattr(settings, "admin_emails", ("ops@example.com",))
    monkeypatch.setattr(settings, "signup_require_invite", True)
    monkeypatch.setattr(settings, "mail_provider", "smtp")
    monkeypatch.setattr(settings, "frontend_base_url", "https://trade-desk.fly.dev")
    monkeypatch.setattr(settings, "payout_auto_approve_override", None)
    monkeypatch.setattr(settings, "kyc_auto_verify_override", None)
    monkeypatch.setattr(settings, "sentry_dsn", "https://key@sentry.example/1")
    monkeypatch.setattr(settings, "backup_offsite_provider", "s3")
    monkeypatch.setattr(settings, "cookie_secure_override", None)
    monkeypatch.setattr(settings, "trust_proxy", True)
    return monkeypatch


def _keys(findings: list[Finding]) -> list[str]:
    return [f.key for f in findings]


class TestNotProduction:
    @pytest.mark.parametrize("env", ["development", "dev", "test", "staging", ""])
    def test_nothing_fires_outside_production(self, monkeypatch, env):
        """A laptop and CI must see an empty list even with every 'risky'
        default in place — otherwise the check becomes noise people learn to
        ignore, which is how the real one gets missed."""
        monkeypatch.setattr(settings, "app_env", env)
        monkeypatch.setattr(settings, "admin_emails", ())
        monkeypatch.setattr(settings, "mail_provider", "console")
        monkeypatch.setattr(settings, "sentry_dsn", "")
        monkeypatch.setattr(settings, "backup_offsite_provider", "none")
        assert check_config(on_fly=True) == []

    def test_run_preflight_is_silent_and_raises_nothing(self, monkeypatch):
        monkeypatch.setattr(settings, "app_env", "development")
        monkeypatch.setattr(settings, "frontend_base_url", "http://localhost:5173")
        monkeypatch.setattr(settings, "mail_provider", "smtp")
        assert run_preflight(on_fly=False) == []


class TestCleanProduction:
    def test_a_fully_configured_deployment_reports_nothing(self, prod):
        assert check_config(on_fly=True) == []

    def test_prod_defaults_alone_silence_the_money_switches(self, prod):
        """payout/KYC auto-approval follow app_env now, so an operator who
        never touches them gets the safe posture and no warning."""
        assert settings.payout_auto_approve is False
        assert settings.kyc_auto_verify is False
        assert "PAYOUT_AUTO_APPROVE" not in _keys(check_config(on_fly=True))
        assert "KYC_AUTO_VERIFY" not in _keys(check_config(on_fly=True))


class TestRefusals:
    def test_real_mail_with_a_localhost_app_url_refuses(self, prod):
        prod.setattr(settings, "frontend_base_url", "http://localhost:5173")
        findings = check_config(on_fly=True)
        refusals = [f for f in findings if f.level == "refuse"]
        assert _keys(refusals) == ["FRONTEND_BASE_URL"]
        with pytest.raises(PreflightError, match="FRONTEND_BASE_URL"):
            run_preflight(on_fly=True)

    @pytest.mark.parametrize(
        "url",
        [
            "http://localhost:5173",
            "http://127.0.0.1:8000",
            "http://0.0.0.0:8000",
            "https://app.local",
            "https://app.example",
            "https://staging.test",
            "not-a-url",
        ],
    )
    def test_every_unroutable_link_host_is_caught(self, prod, url):
        prod.setattr(settings, "frontend_base_url", url)
        assert "FRONTEND_BASE_URL" in _keys(check_config(on_fly=True))

    @pytest.mark.parametrize(
        "url", ["https://trade-desk.fly.dev", "https://app.mydomain.com", "http://1.2.3.4"]
    )
    def test_a_reachable_link_host_is_fine(self, prod, url):
        prod.setattr(settings, "frontend_base_url", url)
        assert "FRONTEND_BASE_URL" not in _keys(check_config(on_fly=True))

    def test_console_mail_does_not_refuse_on_a_localhost_url(self, prod):
        """Console mail never leaves the box, so a localhost link URL is
        merely the dev default, not a broken user flow. Refusing here would
        block every console-mail deployment for no gain."""
        prod.setattr(settings, "mail_provider", "console")
        prod.setattr(settings, "frontend_base_url", "http://localhost:5173")
        findings = check_config(on_fly=True)
        assert [f for f in findings if f.level == "refuse"] == []
        assert "MAIL_PROVIDER" in _keys(findings)

    def test_refusals_are_exhaustively_one_rule(self, prod):
        """The guard rail on this module: with EVERYTHING misconfigured at
        once, exactly one refusal exists. Adding a refusal is a deliberate
        act that has to update this test."""
        prod.setattr(settings, "admin_emails", ())
        prod.setattr(settings, "signup_require_invite", False)
        prod.setattr(settings, "mail_provider", "smtp")
        prod.setattr(settings, "frontend_base_url", "http://localhost:5173")
        prod.setattr(settings, "payout_auto_approve_override", True)
        prod.setattr(settings, "kyc_auto_verify_override", True)
        prod.setattr(settings, "sentry_dsn", "")
        prod.setattr(settings, "backup_offsite_provider", "none")
        prod.setattr(settings, "cookie_secure_override", False)
        prod.setattr(settings, "trust_proxy", False)

        findings = check_config(on_fly=True)
        assert [f.key for f in findings if f.level == "refuse"] == ["FRONTEND_BASE_URL"]
        assert len([f for f in findings if f.level == "warn"]) == 8
        # worst first, so a log reader sees the fatal one at the top
        assert findings[0].level == "refuse"


class TestWarnings:
    def test_empty_admin_emails(self, prod):
        prod.setattr(settings, "admin_emails", ())
        assert "ADMIN_EMAILS" in _keys(check_config(on_fly=True))

    def test_open_signup(self, prod):
        prod.setattr(settings, "signup_require_invite", False)
        assert "SIGNUP_REQUIRE_INVITE" in _keys(check_config(on_fly=True))

    def test_console_mail(self, prod):
        prod.setattr(settings, "mail_provider", "console")
        assert "MAIL_PROVIDER" in _keys(check_config(on_fly=True))

    def test_payout_auto_approve_explicitly_on(self, prod):
        prod.setattr(settings, "payout_auto_approve_override", True)
        finding = next(f for f in check_config(on_fly=True) if f.key == "PAYOUT_AUTO_APPROVE")
        assert finding.level == "warn"
        assert "reviewer_id=None" in finding.problem

    def test_kyc_auto_verify_explicitly_on(self, prod):
        prod.setattr(settings, "kyc_auto_verify_override", True)
        assert "KYC_AUTO_VERIFY" in _keys(check_config(on_fly=True))

    def test_missing_sentry_dsn(self, prod):
        prod.setattr(settings, "sentry_dsn", "")
        assert "SENTRY_DSN" in _keys(check_config(on_fly=True))

    @pytest.mark.parametrize("provider", ["none", "", "off", "disabled", "NONE"])
    def test_offsite_backups_disabled(self, prod, provider):
        prod.setattr(settings, "backup_offsite_provider", provider)
        assert "BACKUP_OFFSITE_PROVIDER" in _keys(check_config(on_fly=True))

    def test_cookie_secure_forced_off(self, prod):
        prod.setattr(settings, "cookie_secure_override", False)
        assert "COOKIE_SECURE" in _keys(check_config(on_fly=True))

    def test_trust_proxy_off_behind_fly(self, prod):
        prod.setattr(settings, "trust_proxy", False)
        finding = next(f for f in check_config(on_fly=True) if f.key == "TRUST_PROXY")
        assert "behind Fly's proxy" in finding.problem

    def test_trust_proxy_on_with_no_proxy(self, prod):
        """The opposite mistake, and the more dangerous of the two: trusting
        a client-controlled header with nothing in front of you."""
        prod.setattr(settings, "trust_proxy", True)
        finding = next(f for f in check_config(on_fly=False) if f.key == "TRUST_PROXY")
        assert "client-controlled" in finding.problem

    def test_trust_proxy_is_never_reported_twice(self, prod):
        for fly in (True, False):
            prod.setattr(settings, "trust_proxy", not fly)
            assert _keys(check_config(on_fly=fly)).count("TRUST_PROXY") == 1

    def test_warnings_do_not_stop_startup(self, prod, caplog):
        prod.setattr(settings, "admin_emails", ())
        prod.setattr(settings, "sentry_dsn", "")
        findings = run_preflight(on_fly=True)  # must not raise
        assert len(findings) == 2
        assert "ADMIN_EMAILS" in caplog.text
        assert "SENTRY_DSN" in caplog.text


class TestFindingContent:
    def test_every_finding_carries_an_actionable_fix(self, prod):
        prod.setattr(settings, "admin_emails", ())
        prod.setattr(settings, "signup_require_invite", False)
        prod.setattr(settings, "mail_provider", "console")
        prod.setattr(settings, "payout_auto_approve_override", True)
        prod.setattr(settings, "kyc_auto_verify_override", True)
        prod.setattr(settings, "sentry_dsn", "")
        prod.setattr(settings, "backup_offsite_provider", "none")
        prod.setattr(settings, "cookie_secure_override", False)
        prod.setattr(settings, "trust_proxy", False)
        for finding in check_config(on_fly=True):
            assert finding.fix.strip(), f"{finding.key} has no fix"
            assert finding.problem.strip(), f"{finding.key} has no problem statement"
            assert finding.key.isupper(), f"{finding.key} should name the env var"
            assert finding.key in finding.render()

    def test_no_secret_value_is_ever_echoed(self, prod):
        """These findings are logged and rendered in the admin console, so a
        finding must name the SETTING, never its value."""
        prod.setattr(settings, "sentry_dsn", "")
        prod.setattr(settings, "smtp_password", "hunter2-super-secret")
        prod.setattr(settings, "backup_s3_secret_access_key", "sk-live-do-not-log")
        prod.setattr(settings, "admin_emails", ())
        rendered = " ".join(f.render() for f in check_config(on_fly=True))
        assert "hunter2-super-secret" not in rendered
        assert "sk-live-do-not-log" not in rendered


class TestAdminEndpoint:
    def test_requires_admin(self, client):
        assert client.get("/api/admin/preflight").status_code in (401, 403)

    def test_reports_environment_and_findings(self, admin_client, monkeypatch):
        monkeypatch.setattr(settings, "app_env", "production")
        monkeypatch.setattr(settings, "admin_emails", ())
        body = admin_client.get("/api/admin/preflight").json()
        assert body["is_production"] is True
        assert body["environment"] == "production"
        assert "ADMIN_EMAILS" in [f["key"] for f in body["findings"]]
        assert all({"level", "key", "problem", "fix"} == set(f) for f in body["findings"])

    def test_is_empty_on_a_development_box(self, admin_client, monkeypatch):
        monkeypatch.setattr(settings, "app_env", "development")
        body = admin_client.get("/api/admin/preflight").json()
        assert body["is_production"] is False
        assert body["findings"] == []
