"""Shared test scaffolding for the multi-user prop-firm shell.

Per-test in-memory SQLite (StaticPool so every connection sees the same
schema), get_session override, and authenticated clients that sign up
through the REAL auth endpoints — bcrypt cost is dropped to 4 so that
stays fast. TestClient keeps the session cookie automatically.

Existing test files keep their own local `client` fixtures where they
predate this; new/migrated files use these.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from config import settings
from database import Base, get_session
from main import app


def pytest_configure(config):
    config.addinivalue_line(
        "markers",
        "real_gates: run with the production compliance gates ON "
        "(suspended/KYC/tax/method/consent/e-sign) — skips the default "
        "_relax_compliance_gates fixture",
    )


@pytest.fixture(autouse=True)
def _relax_compliance_gates(request, monkeypatch):
    """The P0 compliance gates on the money endpoints (payout: KYC + tax +
    payout method; purchase/reset: ToS + risk consent; activation: signed
    funded-trader agreement) default ON in production. Left on, every
    pre-gate test that purchases a combine or requests a payout would 403
    before reaching its actual subject — so, exactly like the LIFTED
    financial-limiter budget above, they are relaxed here BY DEFAULT at the
    router binding site (routers.combines), leaving the service-level gate
    tests (test_legal / test_verification) on the real functions.

    Dedicated gate tests opt back in with @pytest.mark.real_gates and drive
    the production defaults end-to-end (tests/test_payout_desk.py)."""
    if request.node.get_closest_marker("real_gates"):
        yield
        return
    monkeypatch.setattr(
        "routers.combines.assert_payout_eligible", lambda db, user: None
    )
    monkeypatch.setattr("routers.combines.assert_consented", lambda db, user: None)
    monkeypatch.setattr(
        "routers.combines.assert_funded_agreement_signed", lambda db, user: None
    )
    yield


@pytest.fixture(autouse=True)
def _fast_bcrypt():
    prior = settings.bcrypt_rounds
    settings.bcrypt_rounds = 4
    yield
    settings.bcrypt_rounds = prior


@pytest.fixture(autouse=True)
def _reset_auth_rate_limiter():
    """The rate limiters are process-global; clear them between tests so
    hits from earlier cases (all sharing the TestClient host) don't bleed
    over. Covers the auth brute-force limiter, the global per-IP throttle
    applied by the main.py middleware, and the per-user financial limiter.

    The financial limiter's real default (a few purchases/payouts per minute)
    is intentionally tight, which would trip the lifecycle tests that
    legitimately buy 5-6 combines in a loop. So we LIFT its budget to a high
    ceiling for the test run by default; the dedicated rate-limit tests lower
    `max_attempts` themselves (monkeypatch) to exercise the 429, exactly like
    the auth/global limiter tests do."""
    from services.rate_limit import auth_limiter, financial_limiter, global_limiter

    prior_financial = financial_limiter.max_attempts
    financial_limiter.max_attempts = 1000

    auth_limiter.reset()
    global_limiter.reset()
    financial_limiter.reset()
    yield
    auth_limiter.reset()
    global_limiter.reset()
    financial_limiter.reset()
    financial_limiter.max_attempts = prior_financial


@pytest.fixture(autouse=True)
def _no_live_option_quotes(monkeypatch):
    """Default the live two-sided option-quote seam to empty so no test
    silently reaches the Alpaca network. With no quotes, `close_friction`
    returns 0 — the deterministic baseline the recompute tests assume.

    Tests that exercise spread-crossing friction (test_fill_realism,
    test_orders_api) monkeypatch this same seam themselves; because their
    patch runs after this autouse fixture, theirs wins. Patched in BOTH
    binding sites: services.fills (order_monitor's module-attr call +
    close_friction) and routers.zerodte (which imports it under an alias)."""

    def _empty(symbol, legs):
        return {}

    monkeypatch.setattr("services.fills.live_leg_quotes", _empty)
    try:
        monkeypatch.setattr("routers.zerodte._live_leg_quotes", _empty)
    except AttributeError:  # router not imported in this test's graph
        pass


@pytest.fixture
def db_engine():
    # Import models so they register on Base.metadata before create_all.
    import models.account_state  # noqa: F401
    import models.alert  # noqa: F401
    import models.auth_session  # noqa: F401
    import models.combine  # noqa: F401
    import models.payment  # noqa: F401
    import models.ticker_selection  # noqa: F401
    import models.trade  # noqa: F401
    import models.user  # noqa: F401
    import models.user_star  # noqa: F401

    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )
    Base.metadata.create_all(bind=engine)
    yield engine
    engine.dispose()


@pytest.fixture
def session_factory(db_engine):
    return sessionmaker(
        bind=db_engine, autoflush=False, autocommit=False, future=True
    )


@pytest.fixture
def api_client(db_engine, session_factory):
    """Unauthenticated TestClient against a fresh in-memory DB.

    Named api_client (not `client`) so test modules can define their
    own `client` fixture on top of auth_client without creating a
    recursive fixture chain.
    """

    def override_get_session():
        session = session_factory()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_session] = override_get_session
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.pop(get_session, None)


@pytest.fixture
def client(api_client):
    """Default unauthenticated client alias."""
    return api_client


def _signup(client: TestClient, email: str) -> TestClient:
    res = client.post(
        "/api/auth/signup",
        json={"email": email, "password": "password123", "display_name": "T"},
    )
    assert res.status_code == 201, res.text
    return client


@pytest.fixture
def auth_client(api_client):
    """Signed-up + signed-in client (cookie jar carries the session)."""
    return _signup(api_client, "trader@test.local")


@pytest.fixture
def second_user_client(db_engine, session_factory):
    """A second authenticated user on the SAME database — for isolation
    tests. Separate TestClient so cookie jars don't mix."""

    def override_get_session():
        session = session_factory()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_session] = override_get_session
    c = TestClient(app)
    _signup(c, "rival@test.local")
    return c


def make_combine(client: TestClient, tier: str = "50K", name: str | None = None) -> dict:
    """Purchase a combine through the real endpoint; returns CombineOut."""
    payload: dict = {"tier": tier}
    if name is not None:
        payload["name"] = name
    res = client.post("/api/combines/purchase", json=payload)
    assert res.status_code == 201, res.text
    return res.json()


def accept_legal(client: TestClient, doc_keys: tuple[str, ...] = ("tos", "risk")) -> None:
    """Checkbox-accept legal documents at their current versions — satisfies
    the purchase/reset consent gate (ToS + risk by default)."""
    res = client.post("/api/legal/accept", json={"doc_keys": list(doc_keys)})
    assert res.status_code == 200, res.text


def sign_funded_agreement(client: TestClient, typed_name: str = "Test Trader") -> None:
    """Typed-name e-sign of the funded-trader agreement — satisfies the
    activation gate."""
    res = client.post(
        "/api/legal/sign-funded-agreement", json={"typed_name": typed_name}
    )
    assert res.status_code == 200, res.text


def satisfy_payout_prereqs(client: TestClient) -> None:
    """Walk the signed-in user through EVERY production compliance gate on
    the money path: consent (tos+risk), the funded-agreement e-sign, a
    verified US KYC identity, a W-9 tax profile, and an ACH payout method —
    all via the real endpoints. For @pytest.mark.real_gates tests."""
    accept_legal(client)
    sign_funded_agreement(client)
    res = client.post(
        "/api/verification/kyc/submit",
        json={
            "legal_name": "Test Trader",
            "dob": "1990-01-15",
            "country": "US",
            "document_type": "passport",
        },
    )
    assert res.status_code == 200, res.text
    assert res.json()["status"] == "verified", res.text
    res = client.post(
        "/api/verification/tax/submit",
        json={
            "form_type": "W9",
            "legal_name": "Test Trader",
            "country": "US",
            "address": {
                "line1": "1 Test St",
                "city": "Testville",
                "region": "CA",
                "postal": "94000",
                "country": "US",
            },
            "tin_last4": "1234",
        },
    )
    assert res.status_code == 200, res.text
    res = client.post(
        "/api/verification/methods",
        json={
            "type": "ach",
            "label": "Test Checking",
            "details": {"routing_number": "021000021", "account_last4": "6789"},
        },
    )
    assert res.status_code == 201, res.text
