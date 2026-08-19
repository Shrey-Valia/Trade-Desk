"""Sentry wiring — does an error actually leave the process, and does it
leave without credentials attached?

Why this exists: `SENTRY_DSN` is the only thing standing between a 3am crash
and nobody finding out, and the wiring is easy to believe in without ever
testing. In particular the path that matters most is INDIRECT — a scheduled
job failure reaches Sentry only because run_logged re-raises, APScheduler
logs at ERROR, and the SDK's default logging integration promotes ERROR
records to events. Nothing about that chain is obvious from reading
_init_sentry, and any link breaking is silent.

No Sentry account and no network: sentry_sdk is initialised against a dummy
DSN with a Transport subclass that collects envelopes in memory. (Deliberately
NOT the one-line function transport — that API is deprecated, and
pyproject pins sentry-sdk only as >=2.0, so it would break on a major bump.)
"""

from __future__ import annotations

import logging

import pytest

sentry_sdk = pytest.importorskip("sentry_sdk")

# Imported by name (not via `sentry_sdk.transport.…`) so the base class below
# is statically resolvable — mypy cannot follow the attribute path from a
# bare `import sentry_sdk`. Safe after importorskip: a missing SDK skips the
# whole module before this line runs.
from sentry_sdk.transport import Transport  # noqa: E402

from config import settings  # noqa: E402
from main import _init_sentry, _sentry_scrub  # noqa: E402

# Syntactically valid, points nowhere; the custom transport means nothing is
# ever sent regardless.
_DUMMY_DSN = "https://public@example.invalid/1"


class _CapturingTransport(Transport):
    """Collects events in memory instead of sending them anywhere."""

    def __init__(self, sink: list[dict]):
        super().__init__({})
        self._sink = sink

    def capture_envelope(self, envelope):
        for item in envelope.items:
            if item.headers.get("type") == "event":
                self._sink.append(item.payload.json)

    def flush(self, *args, **kwargs):
        pass

    def kill(self):
        pass


@pytest.fixture
def captured(monkeypatch):
    """Init the real _init_sentry() against a capturing transport."""
    events: list[dict] = []
    monkeypatch.setattr(settings, "sentry_dsn", _DUMMY_DSN)
    monkeypatch.setattr(settings, "sentry_environment", "test-env")
    monkeypatch.setattr(settings, "sentry_release", "test-release")

    real_init = sentry_sdk.init

    def init_with_capture(**kwargs):
        kwargs["transport"] = _CapturingTransport(events)
        return real_init(**kwargs)

    monkeypatch.setattr(sentry_sdk, "init", init_with_capture)
    _init_sentry()
    yield events
    # Detach the client so a dummy-DSN hub can't leak into later tests.
    sentry_sdk.Scope.get_global_scope().set_client(None)


# -- the no-op contract -----------------------------------------------------


def test_blank_dsn_does_not_initialise(monkeypatch):
    """A dev box or CI run must never phone home."""
    monkeypatch.setattr(settings, "sentry_dsn", "")
    calls = []
    monkeypatch.setattr(sentry_sdk, "init", lambda **kw: calls.append(kw))
    _init_sentry()
    assert calls == []


# -- errors actually leave ---------------------------------------------------


def test_captured_exception_becomes_an_event(captured):
    try:
        raise RuntimeError("boom")
    except RuntimeError:
        sentry_sdk.capture_exception()
    sentry_sdk.flush()
    assert len(captured) >= 1
    assert "boom" in str(captured[-1])


def test_error_log_becomes_an_event(captured):
    """THE load-bearing path: APScheduler reports a failed job by logging at
    ERROR with exc_info. If the logging integration ever stops promoting
    those, every scheduled-job failure goes silent — backup, settlement,
    billing renewal — while the app looks healthy."""
    logger = logging.getLogger("apscheduler.executors.default")
    try:
        raise ValueError("settlement exploded")
    except ValueError:
        logger.error('Job "settle_combines" raised an exception', exc_info=True)
    sentry_sdk.flush()
    assert captured, "an ERROR log did not produce a Sentry event"
    assert "settlement exploded" in str(captured[-1])


def test_events_carry_environment_and_release(captured):
    """Without these an error can't be pinned to a deploy or a stage."""
    sentry_sdk.capture_message("tagged")
    sentry_sdk.flush()
    event = captured[-1]
    assert event.get("environment") == "test-env"
    assert event.get("release") == "test-release"


# -- and they leave without credentials -------------------------------------


@pytest.mark.parametrize(
    "header", ["Cookie", "cookie", "Set-Cookie", "Authorization", "X-API-Key"]
)
def test_scrub_removes_credential_headers(header):
    event = {"request": {"headers": {header: "td_session=super-secret"}}}
    scrubbed = _sentry_scrub(event, {})
    assert scrubbed["request"]["headers"][header] == "[scrubbed]"
    assert "super-secret" not in str(scrubbed)


def test_scrub_keeps_useful_headers():
    """Scrubbing must not blind the report — user-agent and path are how you
    reproduce the thing."""
    event = {"request": {"headers": {"User-Agent": "Firefox", "Cookie": "x=1"}}}
    out = _sentry_scrub(event, {})
    assert out["request"]["headers"]["User-Agent"] == "Firefox"
    assert out["request"]["headers"]["Cookie"] == "[scrubbed]"


def test_scrub_tolerates_events_without_request():
    """Scheduled-job errors have no HTTP request at all; before_send runs on
    them too and must not raise (a raising before_send drops the event)."""
    assert _sentry_scrub({}, {}) == {}
    assert _sentry_scrub({"request": {}}, {}) == {"request": {}}
    assert _sentry_scrub({"request": {"headers": None}}, {}) is not None
