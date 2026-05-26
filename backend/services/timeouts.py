"""Per-call timeout wrapper for blocking external SDK calls.

The Alpaca SDK clients don't accept a request timeout at construction
(see StockHistoricalDataClient.__init__ — no `timeout` parameter), and
their internal session doesn't expose one we can pin. The Finnhub
client has a 10s class-level DEFAULT_TIMEOUT but several of our
scheduled jobs make 30+ sequential calls; a single 10s stall on the
wire can still chain into a >60s tick that collides with the next
APScheduler fire.

This module gives the job layer a uniform way to enforce a deadline
without touching the underlying SDK code (which is also tagged as
frozen elsewhere): `run_with_timeout(fn, *args, timeout_s=N)` submits
the call to a single-worker `ThreadPoolExecutor` and gives up after
`timeout_s` seconds. The thread itself keeps running until the SDK
call returns or the process exits — but the SCHEDULER tick is freed
to return control, so APScheduler doesn't pile up missed runs.

Use this from the job layer (jobs/*.py), not from request handlers —
request handlers should fail fast with a 5xx if a dependency is slow,
not silently swallow the call.
"""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor, TimeoutError as _TimeoutError
from typing import Any, Callable, TypeVar

log = logging.getLogger(__name__)

T = TypeVar("T")


class CallTimeout(Exception):
    """Raised when run_with_timeout's deadline is exceeded.

    The underlying call MAY still complete in its background thread —
    we don't (and can't) interrupt blocking C-extension I/O. The caller
    should treat this as "no result this tick, try again on the next."
    """


# Single shared executor per process so we don't churn threads on every
# call. Two workers is enough for a job layer that processes symbols
# sequentially: one for the live call, one in reserve so a stuck call
# doesn't block a NEW timeout attempt from registering.
_EXECUTOR = ThreadPoolExecutor(max_workers=2, thread_name_prefix="td-timeout")


def run_with_timeout(
    fn: Callable[..., T],
    *args: Any,
    timeout_s: float,
    **kwargs: Any,
) -> T:
    """Run `fn(*args, **kwargs)` and raise CallTimeout after `timeout_s`.

    Any exception raised by `fn` propagates as normal. CallTimeout is
    raised if the deadline elapses; callers typically catch it and skip
    that symbol/iteration."""
    future = _EXECUTOR.submit(fn, *args, **kwargs)
    try:
        return future.result(timeout=timeout_s)
    except _TimeoutError:
        log.warning("call to %s timed out after %.1fs", fn.__qualname__, timeout_s)
        raise CallTimeout(
            f"{fn.__qualname__} exceeded {timeout_s:.0f}s deadline"
        )
