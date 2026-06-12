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


@pytest.fixture(autouse=True)
def _fast_bcrypt():
    prior = settings.bcrypt_rounds
    settings.bcrypt_rounds = 4
    yield
    settings.bcrypt_rounds = prior


@pytest.fixture
def db_engine():
    # Import models so they register on Base.metadata before create_all.
    import models.account_state  # noqa: F401
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
