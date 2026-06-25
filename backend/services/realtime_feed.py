"""Real-time market-data feed seam (DESIGN STUB — wired to nothing).

This module exists to give the WS-D design spike
(`docs/realtime-data-feed-spike.md`) a concrete interface to implement
against. It is deliberately inert:

  * NOTHING imports it. No router, job, or read path references it.
  * The default factory returns a NO-OP feed and the gating flag
    (`realtime_feed_enabled`) does not exist on `config.Settings` yet,
    so even if it were called it would resolve to the no-op.
  * It performs NO network I/O, starts NO tasks, and mutates NO shared
    state. Importing this file has zero side effects.

The intended migration (see the doc) is:

  1. Land this seam (free, no behavior change).  ← you are here
  2. Add `realtime_feed_enabled: bool = False` to `config.Settings`.
  3. Implement `AlpacaRealtimeFeed` (wraps `alpaca.data.live.StockDataStream`
     / `OptionDataStream`) writing into a `LatestStore`.
  4. Have `alpaca_client.get_quotes`/`get_bars` consult the feed's
     `latest_quote`/`latest_bar` at the top of the hot path, behind the
     flag, falling back to the existing REST + TokenBucket + CircuitBreaker
     + TTLCache path on a miss/stale entry.

Until step 2, `get_realtime_feed()` always returns `NoOpRealtimeFeed`.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from typing import Callable, Iterable


# A handler invoked by the consumer when a fresh tick arrives. Implementations
# call these last-value-wins (overwrite per symbol) — there is no queue, so a
# slow consumer drops intermediate ticks rather than growing memory.
QuoteHandler = Callable[["FeedQuote"], None]
BarHandler = Callable[["FeedBar"], None]


@dataclass(frozen=True)
class FeedQuote:
    """A top-of-book quote pushed by the stream.

    Intentionally minimal and decoupled from `alpaca_client.Quote` so the
    seam doesn't drag SDK types around. An adapter maps provider payloads to
    this shape; the read-path integration maps this back to the existing
    `Quote` on the hot path.
    """

    symbol: str
    bid: float
    ask: float
    last: float
    ts: datetime  # provider timestamp of the tick


@dataclass(frozen=True)
class FeedBar:
    """A closed bar pushed by the stream, keyed by (symbol, timeframe)."""

    symbol: str
    timeframe: str
    open: float
    high: float
    low: float
    close: float
    volume: int
    ts: datetime


class RealtimeFeed(ABC):
    """Abstract WebSocket-backed market-data feed.

    A concrete implementation maintains a persistent provider WebSocket and
    an in-memory last-value-wins store, so the synchronous read paths
    (`get_quotes`/`get_bars`) can serve fresh data without a network hop.

    Lifecycle:  `subscribe(...)` → `run()` (blocks, internal reconnect loop)
    → `stop()`.  Handlers registered via `on_quote`/`on_bar` fire on each
    fresh tick.  `latest_quote`/`latest_bar` are the synchronous accessors
    the read paths call.
    """

    @abstractmethod
    def subscribe(self, symbols: Iterable[str]) -> None:
        """Add `symbols` to the live subscription set.

        Implementations re-apply the full set on every (re)connect, since the
        provider does not remember subscriptions across sockets.
        """

    @abstractmethod
    def unsubscribe(self, symbols: Iterable[str]) -> None:
        """Drop `symbols` from the live subscription set (e.g. when a chain
        leaves the screen — important for bounding OPRA volume)."""

    @abstractmethod
    def latest_quote(self, symbol: str) -> FeedQuote | None:
        """Most recent quote for `symbol`, or None if none has arrived /
        the entry is past its staleness window. None signals the read path
        to fall back to REST."""

    @abstractmethod
    def latest_bar(self, symbol: str, timeframe: str) -> FeedBar | None:
        """Most recent closed bar for `(symbol, timeframe)`, or None."""

    @abstractmethod
    def on_quote(self, handler: QuoteHandler) -> None:
        """Register a callback fired on each fresh quote."""

    @abstractmethod
    def on_bar(self, handler: BarHandler) -> None:
        """Register a callback fired on each fresh closed bar."""

    @abstractmethod
    async def run(self) -> None:
        """Connect and consume until stopped. Owns the reconnect/backoff loop
        and is gated by a dedicated `"alpaca-stream"` circuit breaker so a
        flapping socket self-heals into the REST fallback."""

    @abstractmethod
    def stop(self) -> None:
        """Signal `run()` to disconnect and return (called on lifespan
        shutdown)."""


class NoOpRealtimeFeed(RealtimeFeed):
    """Inert default: accepts subscriptions, never connects, never has data.

    Every accessor returns None so a read path consulting it always falls
    through to the existing REST path. This is what `get_realtime_feed()`
    returns while the feature flag is off (i.e. today), guaranteeing no
    behavior change.
    """

    def subscribe(self, symbols: Iterable[str]) -> None:  # noqa: D102
        return None

    def unsubscribe(self, symbols: Iterable[str]) -> None:  # noqa: D102
        return None

    def latest_quote(self, symbol: str) -> FeedQuote | None:  # noqa: D102
        return None

    def latest_bar(self, symbol: str, timeframe: str) -> FeedBar | None:  # noqa: D102
        return None

    def on_quote(self, handler: QuoteHandler) -> None:  # noqa: D102
        return None

    def on_bar(self, handler: BarHandler) -> None:  # noqa: D102
        return None

    async def run(self) -> None:  # noqa: D102
        return None

    def stop(self) -> None:  # noqa: D102
        return None


def get_realtime_feed() -> RealtimeFeed:
    """Factory for the process-wide feed.

    Returns `NoOpRealtimeFeed` unless `settings.realtime_feed_enabled` is set
    True AND a concrete adapter is registered. Neither exists yet, so this is
    always the no-op today — calling it is safe and inert. The lookup is done
    defensively with `getattr` so this stub imports cleanly against the
    current `Settings` (which has no such field).
    """
    try:
        from config import settings

        if getattr(settings, "realtime_feed_enabled", False):
            # A concrete adapter (e.g. AlpacaRealtimeFeed) would be
            # constructed here once implemented. Until then, fall through to
            # the no-op so an accidentally-flipped flag still changes nothing.
            return NoOpRealtimeFeed()
    except Exception:  # noqa: BLE001 — never let the seam break a caller
        pass
    return NoOpRealtimeFeed()


__all__ = [
    "FeedQuote",
    "FeedBar",
    "RealtimeFeed",
    "NoOpRealtimeFeed",
    "get_realtime_feed",
    "QuoteHandler",
    "BarHandler",
]
