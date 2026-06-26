"""Real-time market-data feed seam.

Implements the architecture in `docs/realtime-data-feed-spike.md`: a flagged
background WebSocket consumer maintains an in-memory last-value-wins store that
`alpaca_client.get_quotes` / `get_bars` read from on the hot path, falling back
to the unchanged REST + TokenBucket + CircuitBreaker + TTLCache path on
miss/stale.

**Default OFF.** `get_realtime_feed()` returns `NoOpRealtimeFeed` unless
`settings.realtime_feed_enabled` is True, so importing this module and calling
the factory is byte-for-byte equivalent to today's behavior. The NoOp's
accessors always return None, so any read path consulting it falls straight
through to REST — zero behavior change until the flag (and a paid key) land.

Equities only: `alpaca-py 0.21.0`'s `alpaca.data.live` exposes
`StockDataStream` but NOT `OptionDataStream` — options streaming requires a
minor (additive) SDK bump and is deferred (see the spike doc §1.1 / §3 step 3).

Lifecycle (driven by the consumer task in `main.py` lifespan, flag-gated):

  feed.on_quote(...) / feed.on_bar(...)   # optional extra handlers
  feed.subscribe(symbols)                  # seed the subscription set
  await feed.run()                         # blocks; internal reconnect loop
  feed.stop()                              # on lifespan shutdown
"""

from __future__ import annotations

import asyncio
import logging
import random
import threading
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from typing import Callable, Iterable

log = logging.getLogger(__name__)


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


# ---------------------------------------------------------------------------
# LatestStore — in-memory last-value-wins, monotonic-clock staleness window.
# ---------------------------------------------------------------------------

# Mapping from our chart timeframe tokens to the alpaca-py stream's bar grain.
# The stream only emits the provider's native minute bars (subscribe_bars);
# we tag those as "1m". Other timeframes are never served from the stream —
# they keep coming from REST (the staleness/None on a miss does the routing).
_STREAM_BAR_TIMEFRAME = "1m"


class LatestStore:
    """Thread-safe, bounded, last-value-wins quote/bar store.

    Writes come from the async consumer (one thread/loop); reads come from
    the synchronous REST hot path (scheduler worker threads + the request
    thread). Guarded by one lock; `O(symbols)` memory regardless of tick rate
    because each (symbol[, timeframe]) key holds exactly one value.

    Staleness is measured on `time.monotonic()` — a wall-clock-independent
    liveness guard. A value older than its TTL reads as None so the hot path
    falls through to REST: the TTL *is* the stall detector (a silently
    half-open socket stops writing, entries age out, polling resumes).
    """

    def __init__(self, *, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        self._lock = threading.Lock()
        self._quotes: dict[str, tuple[FeedQuote, float]] = {}
        self._bars: dict[tuple[str, str], tuple[FeedBar, float]] = {}

    def put_quote(self, quote: FeedQuote) -> None:
        with self._lock:
            self._quotes[quote.symbol] = (quote, self._clock())

    def put_bar(self, bar: FeedBar) -> None:
        with self._lock:
            self._bars[(bar.symbol, bar.timeframe)] = (bar, self._clock())

    def get_quote(self, symbol: str, max_age_s: float) -> FeedQuote | None:
        with self._lock:
            entry = self._quotes.get(symbol)
        if entry is None:
            return None
        quote, ts = entry
        if (self._clock() - ts) > max_age_s:
            return None
        return quote

    def get_bar(self, symbol: str, timeframe: str, max_age_s: float) -> FeedBar | None:
        with self._lock:
            entry = self._bars.get((symbol, timeframe))
        if entry is None:
            return None
        bar, ts = entry
        if (self._clock() - ts) > max_age_s:
            return None
        return bar


class AlpacaRealtimeFeed(RealtimeFeed):
    """Equities `StockDataStream` consumer writing into a `LatestStore`.

    Owns a persistent WebSocket and the reconnect/backoff loop. A dedicated
    `"alpaca-stream"` circuit breaker tracks connection health: repeated
    reconnect failures open it, the loop backs off, and the read paths
    transparently serve from REST until a reconnect succeeds and closes it.

    `latest_quote`/`latest_bar` are the synchronous hot-path accessors,
    enforcing the staleness window from settings (quotes: a short TTL so a
    silent stall expires fast; bars: the streamed 1m grain).

    The store is owned here (created in `__init__`) so the read-through can
    reach it via `get_realtime_feed().latest_quote(...)` with no extra wiring.
    """

    # The stream client is constructed lazily so importing/instantiating the
    # feed performs NO network I/O (matters for the flag-off-still-safe
    # guarantee and for tests that never want a socket). The factory below
    # only builds this when the flag is on AND a paid key is present.
    def __init__(
        self,
        *,
        store: LatestStore | None = None,
        quote_ttl_s: float = 3.0,
        bar_ttl_s: float = 75.0,
        max_backoff_s: float = 30.0,
        breaker_name: str = "alpaca-stream",
        stream_factory: Callable[[], object] | None = None,
    ) -> None:
        self._store = store or LatestStore()
        self._quote_ttl_s = quote_ttl_s
        self._bar_ttl_s = bar_ttl_s
        self._max_backoff_s = max_backoff_s
        self._breaker_name = breaker_name
        self._stream_factory = stream_factory

        self._lock = threading.Lock()
        self._symbols: set[str] = set()
        self._quote_handlers: list[QuoteHandler] = []
        self._bar_handlers: list[BarHandler] = []
        self._stop = asyncio.Event()
        self._stream: object | None = None

    # -- subscription set ---------------------------------------------------

    def subscribe(self, symbols: Iterable[str]) -> None:
        new = {s.upper() for s in symbols}
        with self._lock:
            added = new - self._symbols
            self._symbols |= new
            stream = self._stream
        if stream is not None and added:
            # Live socket already up — register the delta now. On a future
            # reconnect the full set is re-applied (the provider forgets
            # subscriptions across sockets).
            self._apply_subscriptions(stream, added)

    def unsubscribe(self, symbols: Iterable[str]) -> None:
        drop = {s.upper() for s in symbols}
        with self._lock:
            removed = drop & self._symbols
            self._symbols -= drop
            stream = self._stream
        if stream is not None and removed:
            try:
                stream.unsubscribe_quotes(*removed)
                stream.unsubscribe_trades(*removed)
                stream.unsubscribe_bars(*removed)
            except Exception:  # noqa: BLE001
                log.warning("alpaca-stream unsubscribe failed for %s", removed)

    # -- hot-path accessors -------------------------------------------------

    def latest_quote(self, symbol: str) -> FeedQuote | None:
        return self._store.get_quote(symbol.upper(), self._quote_ttl_s)

    def latest_bar(self, symbol: str, timeframe: str) -> FeedBar | None:
        # Only the streamed grain ("1m") is ever populated; any other
        # timeframe is a guaranteed miss → REST. Keyed exactly so a "5m"
        # request never accidentally reads a 1m bar.
        return self._store.get_bar(symbol.upper(), timeframe, self._bar_ttl_s)

    # -- handler registration ----------------------------------------------

    def on_quote(self, handler: QuoteHandler) -> None:
        with self._lock:
            self._quote_handlers.append(handler)

    def on_bar(self, handler: BarHandler) -> None:
        with self._lock:
            self._bar_handlers.append(handler)

    # -- consumer loop ------------------------------------------------------

    async def run(self) -> None:
        """Connect + consume until `stop()`. Reconnects with capped
        exponential backoff + jitter, gated by the `"alpaca-stream"`
        breaker so a flapping socket self-heals into the REST fallback."""
        from services.resilience import get_breaker

        breaker = get_breaker(self._breaker_name)
        attempt = 0
        while not self._stop.is_set():
            if not breaker.allow():
                # Breaker open — don't hammer; wait out the cooldown while
                # the read paths serve from REST.
                await self._sleep_or_stop(min(breaker.retry_after(), self._max_backoff_s))
                continue
            try:
                await self._connect_and_consume()
                breaker.record_success()
                attempt = 0
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001
                breaker.record_failure()
                if self._stop.is_set():
                    break
                attempt += 1
                backoff = min(self._max_backoff_s, (2 ** (attempt - 1)))
                backoff += random.uniform(0, backoff * 0.25)  # jitter
                log.warning(
                    "alpaca-stream consume failed (attempt %d): %s — reconnecting in %.1fs",
                    attempt,
                    exc,
                    backoff,
                )
                await self._sleep_or_stop(backoff)

    async def _connect_and_consume(self) -> None:
        stream = self._build_stream()
        with self._lock:
            self._stream = stream
            symbols = set(self._symbols)
        if symbols:
            self._apply_subscriptions(stream, symbols)
        try:
            # alpaca-py's StockDataStream.run() wraps asyncio.run() (its own
            # loop). We're already inside a loop, so drive the coroutine the
            # public run() delegates to. The consume blocks until stop_ws().
            await stream._run_forever()  # noqa: SLF001 — the only async entry
        finally:
            with self._lock:
                self._stream = None

    def _build_stream(self) -> object:
        if self._stream_factory is not None:
            return self._stream_factory()
        # Imported lazily so module import / the flag-off path never touches
        # the live-stream SDK surface.
        from alpaca.data.live import StockDataStream
        from config import settings

        return StockDataStream(settings.alpaca_api_key, settings.alpaca_api_secret)

    def _apply_subscriptions(self, stream: object, symbols: Iterable[str]) -> None:
        syms = tuple(symbols)
        if not syms:
            return
        try:
            stream.subscribe_quotes(self._handle_quote, *syms)
            stream.subscribe_trades(self._handle_trade, *syms)
            stream.subscribe_bars(self._handle_bar, *syms)
        except Exception:  # noqa: BLE001
            log.warning("alpaca-stream subscribe failed for %s", syms)
            raise

    # -- provider payload adapters (async — invoked by the SDK socket) -----

    async def _handle_quote(self, raw) -> None:
        bid = float(getattr(raw, "bid_price", 0) or 0)
        ask = float(getattr(raw, "ask_price", 0) or 0)
        # No trade price on a quote tick: carry forward the last trade if we
        # have one, else use the mid so `price` is never absurd. The trade
        # handler overwrites `last` with the real print when one arrives.
        prior = self._store.get_quote(raw.symbol, self._quote_ttl_s)
        last = prior.last if prior is not None else _mid(bid, ask)
        q = FeedQuote(
            symbol=raw.symbol,
            bid=bid,
            ask=ask,
            last=last,
            ts=getattr(raw, "timestamp", None) or datetime.now(),
        )
        self._store.put_quote(q)
        self._fire_quote(q)

    async def _handle_trade(self, raw) -> None:
        # A trade carries the real `last`; merge it onto the standing quote so
        # the read path's `price` is the freshest print.
        prior = self._store.get_quote(raw.symbol, self._quote_ttl_s)
        bid = prior.bid if prior is not None else 0.0
        ask = prior.ask if prior is not None else 0.0
        q = FeedQuote(
            symbol=raw.symbol,
            bid=bid,
            ask=ask,
            last=float(getattr(raw, "price", 0) or 0),
            ts=getattr(raw, "timestamp", None) or datetime.now(),
        )
        self._store.put_quote(q)
        self._fire_quote(q)

    async def _handle_bar(self, raw) -> None:
        b = FeedBar(
            symbol=raw.symbol,
            timeframe=_STREAM_BAR_TIMEFRAME,
            open=float(getattr(raw, "open", 0) or 0),
            high=float(getattr(raw, "high", 0) or 0),
            low=float(getattr(raw, "low", 0) or 0),
            close=float(getattr(raw, "close", 0) or 0),
            volume=int(getattr(raw, "volume", 0) or 0),
            ts=getattr(raw, "timestamp", None) or datetime.now(),
        )
        self._store.put_bar(b)
        self._fire_bar(b)

    def _fire_quote(self, q: FeedQuote) -> None:
        with self._lock:
            handlers = list(self._quote_handlers)
        for h in handlers:
            try:
                h(q)
            except Exception:  # noqa: BLE001
                log.warning("realtime quote handler raised", exc_info=True)

    def _fire_bar(self, b: FeedBar) -> None:
        with self._lock:
            handlers = list(self._bar_handlers)
        for h in handlers:
            try:
                h(b)
            except Exception:  # noqa: BLE001
                log.warning("realtime bar handler raised", exc_info=True)

    # -- shutdown -----------------------------------------------------------

    def stop(self) -> None:
        self._stop.set()
        with self._lock:
            stream = self._stream
        if stream is not None:
            # stop_ws() is async; signal the socket to close. Best-effort —
            # the run loop also exits on the _stop event.
            try:
                close = stream.stop_ws()
                if asyncio.iscoroutine(close):
                    # Schedule on the running loop if there is one; otherwise
                    # the _stop event + socket teardown handle it.
                    try:
                        asyncio.get_running_loop().create_task(close)
                    except RuntimeError:
                        close.close()
            except Exception:  # noqa: BLE001
                log.warning("alpaca-stream stop_ws failed", exc_info=True)

    async def _sleep_or_stop(self, seconds: float) -> None:
        """Sleep up to `seconds`, returning early if stop() fires."""
        if seconds <= 0:
            return
        try:
            await asyncio.wait_for(self._stop.wait(), timeout=seconds)
        except asyncio.TimeoutError:
            return


def _mid(bid: float, ask: float) -> float:
    if bid > 0 and ask > 0:
        return (bid + ask) / 2.0
    return bid or ask or 0.0


# ---------------------------------------------------------------------------
# Process-wide singleton + factory.
# ---------------------------------------------------------------------------

_feed_lock = threading.Lock()
_feed_singleton: RealtimeFeed | None = None


def get_realtime_feed() -> RealtimeFeed:
    """Factory for the process-wide feed.

    Returns `NoOpRealtimeFeed` unless `settings.realtime_feed_enabled` is True
    (the flag defaults False, so this is the no-op today — calling it is safe
    and inert). When enabled, returns a single shared `AlpacaRealtimeFeed`
    whose `LatestStore` the read-through and the consumer task both reach
    through this same instance.

    The lookup is defensive (`getattr`) so the module imports cleanly even if
    `Settings` lacks the field; any error falls back to the no-op so an
    accidentally-flipped flag in a broken config still changes nothing.
    """
    global _feed_singleton
    try:
        from config import settings

        if not getattr(settings, "realtime_feed_enabled", False):
            return NoOpRealtimeFeed()
    except Exception:  # noqa: BLE001 — never let the seam break a caller
        return NoOpRealtimeFeed()

    with _feed_lock:
        # Build once and reuse. The flag-off branch above returns a fresh NoOp
        # WITHOUT touching the singleton, so `_feed_singleton` is only ever
        # None (initial) or a real/explicitly-installed feed — no stale-NoOp
        # case to upgrade, and an explicit `set_realtime_feed()` override (e.g.
        # a test mock) is always honored.
        if _feed_singleton is None:
            _feed_singleton = _build_real_feed()
        return _feed_singleton


def _build_real_feed() -> RealtimeFeed:
    """Construct the real feed, honoring staleness knobs from settings.
    Constructing it performs NO network I/O (the stream is built lazily in
    `run()`)."""
    try:
        from config import settings

        return AlpacaRealtimeFeed(
            quote_ttl_s=getattr(settings, "realtime_quote_ttl_s", 3.0),
            bar_ttl_s=getattr(settings, "realtime_bar_ttl_s", 75.0),
        )
    except Exception:  # noqa: BLE001
        # If anything about constructing the real feed fails, degrade to the
        # no-op so the read paths keep polling rather than crashing.
        log.warning("failed to build AlpacaRealtimeFeed; using NoOp", exc_info=True)
        return NoOpRealtimeFeed()


def set_realtime_feed(feed: RealtimeFeed | None) -> None:
    """Override the process-wide singleton (tests / explicit wiring).

    Passing a feed installs it; passing None clears it so the next
    `get_realtime_feed()` rebuilds from the flag. Lets tests inject a mock
    feed with a pre-seeded store without opening a socket.
    """
    global _feed_singleton
    with _feed_lock:
        _feed_singleton = feed


__all__ = [
    "FeedQuote",
    "FeedBar",
    "RealtimeFeed",
    "NoOpRealtimeFeed",
    "AlpacaRealtimeFeed",
    "LatestStore",
    "get_realtime_feed",
    "set_realtime_feed",
    "QuoteHandler",
    "BarHandler",
]
