"""SPA static-fallback path-traversal guard (main._safe_spa_file).

Regression for the review-wave critical finding: the single-container deploy
serves the built frontend from the backend process, and a naive "'..' not in
path" check let a percent-encoded absolute path (GET /%2Fetc%2Fpasswd →
spa_path "/etc/passwd") escape the dist dir and read arbitrary files —
including the production SQLite DB. The guard must contain every candidate
inside the dist directory.
"""

from __future__ import annotations

import pytest

from main import _safe_spa_file


@pytest.fixture
def dist(tmp_path):
    """A fake built-frontend dir with a real asset and a secret one level up
    (the traversal target)."""
    d = tmp_path / "dist"
    d.mkdir()
    (d / "index.html").write_text("<!doctype html>")
    (d / "favicon.svg").write_text("<svg/>")
    (tmp_path / "secret.db").write_text("SQLITE-SECRET")
    return d


def test_real_dist_file_is_served(dist):
    got = _safe_spa_file(dist, "favicon.svg")
    assert got is not None
    assert got.name == "favicon.svg"


def test_client_route_falls_back(dist):
    # A client route (no such file) → None → caller serves index.html.
    assert _safe_spa_file(dist, "admin") is None
    assert _safe_spa_file(dist, "payouts") is None


def test_empty_path_falls_back(dist):
    assert _safe_spa_file(dist, "") is None


@pytest.mark.parametrize(
    "attack",
    [
        "/etc/hosts",  # absolute path — the %2F-encoded vector, no ".."
        "../secret.db",  # classic relative traversal
        "../../secret.db",
        "..",
    ],
)
def test_traversal_and_absolute_paths_are_blocked(dist, tmp_path, attack):
    # Even when the target genuinely exists (secret.db one level up), the
    # containment check refuses it — the caller serves index.html instead.
    assert _safe_spa_file(dist, attack) is None


def test_absolute_path_to_existing_file_outside_dist_blocked(dist, tmp_path):
    secret = tmp_path / "secret.db"
    assert secret.is_file()  # the file really exists and is readable
    # Passing its absolute path (what `/%2F…%2Fsecret.db` decodes to) must
    # still be refused — this is the exact arbitrary-file-read vector.
    assert _safe_spa_file(dist, str(secret)) is None
