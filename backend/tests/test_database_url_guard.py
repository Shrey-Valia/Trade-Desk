"""Boot guard: a production deployment must not run on a RELATIVE sqlite path.

`sqlite:///./data/dashboard.db` is right for local dev (cwd is `backend/`)
and catastrophic in a container — resolved against the image's
/app/backend WORKDIR it puts the database in the writable layer instead of
the mounted /app/data volume, so every container recreate silently wipes
it while the backup job keeps writing to the volume's absolute default.

Found for real: docker-compose.yml used to pass the host `.env`
DATABASE_URL straight through, which did exactly this. Compose is fixed to
default the container to an absolute path, and this guard is the
belt-and-braces that catches the same mistake arriving by any other route
(a hand-set fly secret, a `docker run -e`, a copied .env).

The guard mirrors the existing pre-tier legacy-DB refusal: a loud boot
failure beats silent data loss.
"""

from __future__ import annotations

import pytest

from config import settings
from database import _assert_durable_sqlite_path


def _prod(monkeypatch) -> None:
    monkeypatch.setattr(settings, "app_env", "production")


def _dev(monkeypatch) -> None:
    monkeypatch.setattr(settings, "app_env", "development")


# -- the refusal ------------------------------------------------------------


@pytest.mark.parametrize(
    "url",
    [
        "sqlite:///./data/dashboard.db",
        "sqlite:///data/dashboard.db",
        "sqlite:///../data/dashboard.db",
    ],
)
def test_production_refuses_relative_sqlite(monkeypatch, url):
    _prod(monkeypatch)
    with pytest.raises(RuntimeError, match="RELATIVE sqlite path"):
        _assert_durable_sqlite_path(url)


def test_refusal_names_the_fix(monkeypatch):
    """The message has to be actionable at 2am: it must show the absolute
    form AND point at the runbook, or the reader's next move is to delete
    the guard."""
    _prod(monkeypatch)
    with pytest.raises(RuntimeError) as exc:
        _assert_durable_sqlite_path("sqlite:///./data/dashboard.db")
    msg = str(exc.value)
    assert "sqlite:////app/data/dashboard.db" in msg
    assert "docs/DEPLOYMENT.md" in msg


# -- what must still be allowed ---------------------------------------------


def test_production_allows_absolute_sqlite(monkeypatch):
    """The image default — four slashes — is the whole point."""
    _prod(monkeypatch)
    _assert_durable_sqlite_path("sqlite:////app/data/dashboard.db")


def test_production_allows_postgres(monkeypatch):
    """Non-sqlite URLs have no path-resolution problem to guard."""
    _prod(monkeypatch)
    _assert_durable_sqlite_path("postgresql+psycopg://u:p@db:5432/trade")


def test_development_allows_relative_sqlite(monkeypatch):
    """The dev default MUST keep working — `sqlite:///./data/dashboard.db`
    with cwd=backend/ is how every contributor runs the app, and the whole
    test suite boots this way."""
    _dev(monkeypatch)
    _assert_durable_sqlite_path("sqlite:///./data/dashboard.db")


def test_in_memory_sqlite_is_untouched_in_dev(monkeypatch):
    """conftest builds in-memory engines; the guard must never fire there."""
    _dev(monkeypatch)
    _assert_durable_sqlite_path("sqlite://")
    _assert_durable_sqlite_path("sqlite:///:memory:")
