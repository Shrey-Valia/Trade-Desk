"""Resilience primitives for flaky upstreams (Alpaca / Finnhub / FRED).

The app hammers Alpaca and the logs fill with "too many requests": every
watchlist tick fans out per-symbol calls, and when the account is being
rate-limited each one still tries, times out, and retries — making the
throttling worse.

A circuit breaker fixes the cascade: once an upstream returns enough
consecutive failures, the breaker OPENS and subsequent calls short-circuit
immediately (raising CircuitOpenError, which the existing per-call
try/except turns into a graceful "no data") for a cooldown window — so we
stop calling a service that's already saying no. After the cooldown one
probe is allowed (half-open); a success closes the breaker, a failure
re-opens it.

`resilient_call` adds modest exponential-backoff retries for *transient*
errors but deliberately does NOT retry rate-limit errors (retrying a 429
is what digs the hole deeper) — those just trip the breaker faster.

Clock + sleep are injectable so the behaviour is unit-testable without
real time.
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Callable, TypeVar

log = logging.getLogger(__name__)

T = TypeVar("T")


class CircuitOpenError(RuntimeError):
    """Raised by resilient_call when the breaker is open (call skipped)."""


class CircuitBreaker:
    def __init__(
        self,
        name: str,
        *,
        fail_threshold: int = 5,
        cooldown: float = 30.0,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.name = name
        self.fail_threshold = fail_threshold
        self.cooldown = cooldown
        self._clock = clock
        self._lock = threading.Lock()
        self._fails = 0
        self._opened_at: float | None = None

    def allow(self) -> bool:
        """True if a call may proceed (closed, or half-open after cooldown)."""
        with self._lock:
            if self._opened_at is None:
                return True
            return (self._clock() - self._opened_at) >= self.cooldown

    def record_success(self) -> None:
        with self._lock:
            was_open = self._opened_at is not None
            self._fails = 0
            self._opened_at = None
        if was_open:
            log.info("circuit '%s' closed after a successful probe", self.name)

    def record_failure(self) -> None:
        with self._lock:
            self._fails += 1
            tripped = self._fails >= self.fail_threshold
            if tripped:
                reopening = self._opened_at is not None
                self._opened_at = self._clock()
        if tripped and not reopening:
            log.warning(
                "circuit '%s' OPEN after %d failures — cooling down %.0fs",
                self.name,
                self._fails,
                self.cooldown,
            )

    @property
    def is_open(self) -> bool:
        return not self.allow()

    def retry_after(self) -> float:
        """Seconds until the breaker would permit a probe again.

        0 when closed or already half-open (a call may proceed now).
        Used to populate the HTTP `Retry-After` header on the degraded
        503 response so the frontend can back off for exactly the
        cooldown window instead of guessing."""
        with self._lock:
            if self._opened_at is None:
                return 0.0
            remaining = self.cooldown - (self._clock() - self._opened_at)
            return max(0.0, remaining)


_breakers: dict[str, CircuitBreaker] = {}
_registry_lock = threading.Lock()


def get_breaker(name: str, **kwargs) -> CircuitBreaker:
    """Process-wide breaker for `name` (created once; kwargs apply only on
    first creation)."""
    with _registry_lock:
        b = _breakers.get(name)
        if b is None:
            b = CircuitBreaker(name, **kwargs)
            _breakers[name] = b
        return b


def reset_breakers() -> None:
    """Test helper — clear the registry."""
    with _registry_lock:
        _breakers.clear()


def breaker_retry_after(name: str, *, default: float = 30.0) -> int:
    """Suggested `Retry-After` (whole seconds) for the named breaker.

    Returns the breaker's remaining cooldown rounded UP, or `default`
    when the breaker doesn't exist yet (a degraded response can be
    raised by a path that never created the breaker). Always >= 1 so the
    header is never "retry immediately", which would just re-trip."""
    with _registry_lock:
        b = _breakers.get(name)
    remaining = b.retry_after() if b is not None else default
    return max(1, int(remaining + 0.999))


def _is_rate_limited(exc: Exception) -> bool:
    s = str(exc).lower()
    return "too many requests" in s or "429" in s or "rate limit" in s


def resilient_call(
    name: str,
    fn: Callable[[], T],
    *,
    retries: int = 1,
    base_delay: float = 0.3,
    sleep: Callable[[float], None] = time.sleep,
    breaker_kwargs: dict | None = None,
) -> T:
    """Call `fn` under the named circuit breaker.

    Raises CircuitOpenError immediately if the breaker is open (caller's
    existing except returns None/cached). Retries transient failures with
    exponential backoff; rate-limit errors are NOT retried and trip the
    breaker. The breaker records exactly one failure per exhausted call."""
    breaker = get_breaker(name, **(breaker_kwargs or {}))
    if not breaker.allow():
        raise CircuitOpenError(f"{name} circuit open")
    attempt = 0
    while True:
        try:
            result = fn()
        except Exception as exc:  # noqa: BLE001
            if _is_rate_limited(exc) or attempt >= retries:
                breaker.record_failure()
                raise
            attempt += 1
            sleep(base_delay * (2 ** (attempt - 1)))
            continue
        breaker.record_success()
        return result
