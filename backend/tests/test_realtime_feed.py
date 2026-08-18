"""WS6 — real-time data feed (built behind a flag).

Three contracts the feature MUST honor (no live socket — the stream is
mocked everywhere):

  (a) FLAG OFF  → get_quotes/get_bars behave exactly as the REST path; the
                  feed is never consulted (NoOp) and the SDK is hit as today.
  (b) FRESH     → with a mock feed enabled and a fresh streamed value, the
                  read-through serves it WITHOUT a REST/SDK call.
  (c) STALE     → when the streamed value is past its staleness window, the
                  read-through declines and falls back to the REST path.

Plus: LatestStore staleness math, the NoOp accessors, the "alpaca-stream"
breaker self-heal, the factory singleton, and the consumer-task lifecycle
(mock StockDataStream — never opens a socket).
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone

import pytest

from config import settings
import services.alpaca_client as ac
import services.realtime_feed as rf  # noqa: F401 — module handle for clarity
from services.realtime_feed import (
    AlpacaRealtimeFeed,
    FeedBar,
    FeedQuote,
    LatestStore,
    NoOpRealtimeFeed,
    get_realtime_feed,
    set_realtime_feed,
)
from services.resilience import get_breaker, reset_breakers


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    """Fresh cache + breakers + feed singleton + flag OFF around each case."""
    ac.cache._store.clear()  # type: ignore[attr-defined]
    reset_breakers()
    set_realtime_feed(None)
    # Never sleep on the shared token bucket in tests.
    monkeypatch.setattr(ac._interactive_bucket, "take", lambda *a, **k: 0.0)
    monkeypatch.setattr(ac._background_bucket, "take", lambda *a, **k: 0.0)
    # Flag defaults OFF; cases that need it on flip it explicitly. The feed
    # reads `config.settings.realtime_feed_enabled` at call time (lazy import),
    # so patch the shared settings object itself.
    monkeypatch.setattr(settings, "realtime_feed_enabled", False, raising=False)
    yield
    ac.cache._store.clear()  # type: ignore[attr-defined]
    reset_breakers()
    set_realtime_feed(None)


# ---------------------------------------------------------------------------
# Test doubles
# ---------------------------------------------------------------------------


class _Snap:
    """Minimal alpaca-py snapshot shape get_quotes reads."""

    def __init__(self, price, prev_close, high=0, low=0, vol=0):
        self.latest_trade = type("T", (), {"price": price})()
        self.previous_daily_bar = type("B", (), {"close": prev_close})()
        self.daily_bar = type("D", (), {"high": high, "low": low, "volume": vol})()


class _RestBar:
    """Minimal alpaca-py bar shape get_bars reads."""

    def __init__(self, ts, o=1.0, h=2.0, low=0.5, c=1.5, v=100):
        self.timestamp = ts
        self.open, self.high, self.low, self.close, self.volume = o, h, low, c, v


class _FakeStockClient:
    """Counts SDK calls so we can assert the REST path was / wasn't taken."""

    def __init__(self, snapshot=None, bars=None):
        self._snapshot = snapshot or {}
        self._bars = bars or {}
        self.snapshot_calls = 0
        self.bars_calls = 0

    def get_stock_snapshot(self, _req):
        self.snapshot_calls += 1
        return self._snapshot

    def get_stock_bars(self, _req):
        self.bars_calls += 1
        return type("Resp", (), {"data": self._bars})()


class _FakeFeed(NoOpRealtimeFeed):
    """A mock feed with a seeded store — no socket, no run loop. Subclasses
    NoOp so run/stop/subscribe are inert; we only override the accessors."""

    def __init__(self):
        self.store = LatestStore()

    def latest_quote(self, symbol):
        return self.store.get_quote(symbol.upper(), 3.0)

    def latest_bar(self, symbol, timeframe):
        return self.store.get_bar(symbol.upper(), timeframe, 75.0)


def _enable(monkeypatch, feed):
    """Flip the flag on and install `feed` as the process-wide singleton."""
    monkeypatch.setattr(settings, "realtime_feed_enabled", True, raising=False)
    set_realtime_feed(feed)


# ---------------------------------------------------------------------------
# (a) FLAG OFF — pure REST, feed never consulted.
# ---------------------------------------------------------------------------


def test_flag_off_get_quotes_is_pure_rest(monkeypatch):
    fake = _FakeStockClient(snapshot={"SPY": _Snap(100.0, 90.0)})
    monkeypatch.setattr(ac, "_stock_client", lambda: fake)

    out = ac.get_quotes(["SPY"])

    assert fake.snapshot_calls == 1            # REST was taken
    assert out["SPY"].price == 100.0
    assert out["SPY"].prev_close == 90.0
    # The NoOp feed never has data → the "alpaca-stream" breaker is untouched
    # (the read-through returns None before ever consulting it).
    import services.resilience as res
    assert "alpaca-stream" not in res._breakers


def test_flag_off_get_bars_is_pure_rest(monkeypatch):
    ts = datetime(2026, 6, 26, 14, 0, tzinfo=timezone.utc)
    fake = _FakeStockClient(bars={"SPY": [_RestBar(ts)]})
    monkeypatch.setattr(ac, "_stock_client", lambda: fake)

    out = ac.get_bars("SPY", "1m")

    assert fake.bars_calls == 1
    assert out is not None and len(out) == 1
    assert out[0].close == 1.5


def test_flag_off_stream_helpers_short_circuit_before_breaker():
    # Both read-through helpers return None on the NoOp feed WITHOUT consulting
    # the breaker — proving flag-off is byte-for-byte the no-read-through path.
    assert ac._stream_quote("SPY") is None
    assert ac._stream_bars("SPY", "1m") is None


# ---------------------------------------------------------------------------
# (b) FRESH — read-through serves the streamed value, no REST/SDK hit.
# ---------------------------------------------------------------------------


def _seed_prev_close(symbol: str, prev_close: float) -> None:
    """Seed a REST-cached prev_close under a DIFFERENT batch key than any
    single-symbol request will use, so `_cached_prev_close` (which scans all
    snapshot keys) finds it without `get_quotes`'s own 5s cache short-circuit
    returning early."""
    ac.cache.set(
        f"alpaca:snapshots:_seed_{symbol}",
        {symbol: ac.Quote(symbol, 50.0, prev_close)},
        300,
    )


def test_fresh_quote_served_from_stream_without_rest(monkeypatch):
    feed = _FakeFeed()
    feed.store.put_quote(
        FeedQuote(symbol="SPY", bid=99.9, ask=100.1, last=100.0, ts=datetime.now())
    )
    _enable(monkeypatch, feed)
    # Stream carries no prev_close — reuse a previously cached one.
    _seed_prev_close("SPY", 90.0)

    fake = _FakeStockClient(snapshot={"SPY": _Snap(100.0, 90.0)})
    monkeypatch.setattr(ac, "_stock_client", lambda: fake)

    out = ac.get_quotes(["SPY"])

    assert fake.snapshot_calls == 0            # REST NOT taken
    assert out["SPY"].price == 100.0           # streamed last
    assert out["SPY"].prev_close == 90.0       # reused from cache
    assert get_breaker("alpaca-stream").allow()  # healthy


def test_fresh_quote_declined_when_no_prev_close_cached(monkeypatch):
    """No cached prev_close → the streamed quote can't compute change_pct, so
    the read-through declines and REST fills it (and the prev_close)."""
    feed = _FakeFeed()
    feed.store.put_quote(
        FeedQuote(symbol="SPY", bid=99.9, ask=100.1, last=100.0, ts=datetime.now())
    )
    _enable(monkeypatch, feed)
    # Note: get_quotes' own 5s cache key is the SAME shape; clear so only the
    # read-through path is exercised.
    ac.cache._store.clear()  # type: ignore[attr-defined]

    fake = _FakeStockClient(snapshot={"SPY": _Snap(100.0, 90.0)})
    monkeypatch.setattr(ac, "_stock_client", lambda: fake)

    out = ac.get_quotes(["SPY"])

    assert fake.snapshot_calls == 1            # fell back to REST
    assert out["SPY"].prev_close == 90.0


def test_fresh_bar_merges_onto_cached_rest_tail(monkeypatch):
    """A fresh streamed 1m bar newer than the cached tail is appended; a
    same-timestamp one replaces it. The full REST history is preserved."""
    feed = _FakeFeed()
    base = datetime(2026, 6, 26, 14, 0, tzinfo=timezone.utc)
    newer = datetime(2026, 6, 26, 14, 1, tzinfo=timezone.utc)
    feed.store.put_bar(
        FeedBar("SPY", "1m", 3.0, 4.0, 2.5, 3.5, 200, newer)
    )
    _enable(monkeypatch, feed)

    # Prime the bars cache with a REST series ending at `base`.
    cache_key = f"alpaca:bars:SPY:1m:{datetime.now(ac._ET).date().isoformat()}"
    ac.cache.set(cache_key, [_RestBar(base)], 30)

    out = ac.get_bars("SPY", "1m")

    assert out is not None and len(out) == 2   # original + streamed tail
    assert out[-1].timestamp == newer
    assert out[-1].close == 3.5


def test_stream_bar_ignored_for_nonstreamed_timeframe(monkeypatch):
    """The stream only holds the 1m grain; a 5m request always misses the
    stream and reads pure REST cache."""
    feed = _FakeFeed()
    feed.store.put_bar(FeedBar("SPY", "1m", 3, 4, 2, 3.5, 1, datetime.now(timezone.utc)))
    _enable(monkeypatch, feed)

    base = datetime(2026, 6, 26, 14, 0, tzinfo=timezone.utc)
    cache_key = f"alpaca:bars:SPY:5m:{datetime.now(ac._ET).date().isoformat()}"
    ac.cache.set(cache_key, [_RestBar(base)], 60)

    out = ac.get_bars("SPY", "5m")
    assert out is not None and len(out) == 1   # unchanged REST series
    assert out[0].timestamp == base


# ---------------------------------------------------------------------------
# (c) STALE — past the window → fall back to REST.
# ---------------------------------------------------------------------------


def test_stale_quote_falls_back_to_rest(monkeypatch):
    # A LatestStore on a frozen clock: put at t=0, read at t=10 with a 3s TTL.
    clock = {"t": 0.0}
    store = LatestStore(clock=lambda: clock["t"])
    store.put_quote(FeedQuote("SPY", 99.9, 100.1, 100.0, datetime.now()))

    class _StaleFeed(NoOpRealtimeFeed):
        def latest_quote(self, symbol):
            return store.get_quote(symbol.upper(), 3.0)

    _enable(monkeypatch, _StaleFeed())
    clock["t"] = 10.0                          # now stale (>3s)
    ac.cache._store.clear()  # type: ignore[attr-defined]

    fake = _FakeStockClient(snapshot={"SPY": _Snap(100.0, 90.0)})
    monkeypatch.setattr(ac, "_stock_client", lambda: fake)

    out = ac.get_quotes(["SPY"])
    assert fake.snapshot_calls == 1            # stale → REST taken
    assert out["SPY"].prev_close == 90.0


def test_batch_declines_if_any_symbol_missing(monkeypatch):
    """A batch where ONE symbol lacks a fresh stream value falls back to REST
    for the WHOLE batch (no partial blend)."""
    feed = _FakeFeed()
    feed.store.put_quote(FeedQuote("SPY", 99.9, 100.1, 100.0, datetime.now()))
    # QQQ intentionally absent.
    _enable(monkeypatch, feed)
    _seed_prev_close("SPY", 90.0)

    fake = _FakeStockClient(
        snapshot={"SPY": _Snap(100.0, 90.0), "QQQ": _Snap(50.0, 45.0)}
    )
    monkeypatch.setattr(ac, "_stock_client", lambda: fake)

    out = ac.get_quotes(["SPY", "QQQ"])
    assert fake.snapshot_calls == 1            # whole batch went REST
    assert set(out) == {"SPY", "QQQ"}


# ---------------------------------------------------------------------------
# LatestStore + NoOp unit behavior
# ---------------------------------------------------------------------------


def test_latest_store_staleness_window():
    clock = {"t": 0.0}
    store = LatestStore(clock=lambda: clock["t"])
    store.put_quote(FeedQuote("SPY", 1, 2, 1.5, datetime.now()))
    assert store.get_quote("SPY", 3.0) is not None    # fresh
    clock["t"] = 2.9
    assert store.get_quote("SPY", 3.0) is not None    # still inside window
    clock["t"] = 3.1
    assert store.get_quote("SPY", 3.0) is None         # expired → None


def test_latest_store_last_value_wins():
    store = LatestStore()
    store.put_quote(FeedQuote("SPY", 1, 2, 1.0, datetime.now()))
    store.put_quote(FeedQuote("SPY", 1, 2, 9.0, datetime.now()))
    assert store.get_quote("SPY", 99.0).last == 9.0    # overwrite, not queue


def test_latest_store_bar_keyed_by_timeframe():
    store = LatestStore()
    store.put_bar(FeedBar("SPY", "1m", 1, 2, 0, 1.5, 1, datetime.now()))
    assert store.get_bar("SPY", "1m", 99.0) is not None
    assert store.get_bar("SPY", "5m", 99.0) is None    # different grain → miss


def test_noop_accessors_all_none():
    f = NoOpRealtimeFeed()
    assert f.latest_quote("SPY") is None
    assert f.latest_bar("SPY", "1m") is None
    # subscribe/unsubscribe/on_quote/on_bar/stop are inert no-ops.
    f.subscribe(["SPY"])
    f.unsubscribe(["SPY"])
    f.on_quote(lambda q: None)
    f.on_bar(lambda b: None)
    f.stop()


# ---------------------------------------------------------------------------
# Factory / singleton
# ---------------------------------------------------------------------------


def test_factory_returns_noop_when_flag_off(monkeypatch):
    monkeypatch.setattr(settings, "realtime_feed_enabled", False, raising=False)
    assert isinstance(get_realtime_feed(), NoOpRealtimeFeed)


def test_factory_returns_real_feed_when_flag_on(monkeypatch):
    monkeypatch.setattr(settings, "realtime_feed_enabled", True, raising=False)
    set_realtime_feed(None)
    feed = get_realtime_feed()
    assert isinstance(feed, AlpacaRealtimeFeed)
    # Singleton: same instance on the next call.
    assert get_realtime_feed() is feed


# ---------------------------------------------------------------------------
# "alpaca-stream" breaker self-heal
# ---------------------------------------------------------------------------


def test_stream_breaker_open_skips_read_through(monkeypatch):
    """When the alpaca-stream breaker is OPEN, the read-through declines even
    on a fresh value → polling resumes (self-heal)."""
    feed = _FakeFeed()
    feed.store.put_quote(FeedQuote("SPY", 99.9, 100.1, 100.0, datetime.now()))
    _enable(monkeypatch, feed)
    ac.cache.set("alpaca:snapshots:SPY", {"SPY": ac.Quote("SPY", 50.0, 90.0)}, 5)

    # Force the breaker open (fail_threshold default is 5).
    b = get_breaker("alpaca-stream", fail_threshold=1)
    b.record_failure()
    assert b.is_open

    assert ac._stream_quote("SPY") is None     # declined → caller goes REST


# ---------------------------------------------------------------------------
# AlpacaRealtimeFeed consumer lifecycle — MOCK stream, no socket.
# ---------------------------------------------------------------------------


class _FakeStream:
    """Stands in for alpaca-py StockDataStream: records subscriptions and
    lets the test drive a tick, then unblocks _run_forever on stop."""

    def __init__(self):
        self.quote_handler = None
        self.trade_handler = None
        self.bar_handler = None
        self.subscribed = set()
        self.run_started = False
        self._stop = None
        # Set once the run loop is live AND the quote handler is wired, so a
        # test can WAIT for readiness rather than poll for a fixed budget.
        self.ready = asyncio.Event()

    def _maybe_ready(self):
        if self.run_started and self.quote_handler is not None:
            self.ready.set()

    def subscribe_quotes(self, handler, *syms):
        self.quote_handler = handler
        self.subscribed |= set(syms)
        self._maybe_ready()

    def subscribe_trades(self, handler, *syms):
        self.trade_handler = handler

    def subscribe_bars(self, handler, *syms):
        self.bar_handler = handler

    def unsubscribe_quotes(self, *syms):
        self.subscribed -= set(syms)

    def unsubscribe_trades(self, *syms):
        pass

    def unsubscribe_bars(self, *syms):
        pass

    async def _run_forever(self):
        self.run_started = True
        self._stop = asyncio.Event()
        self._maybe_ready()
        await self._stop.wait()

    async def stop_ws(self):
        if self._stop is not None:
            self._stop.set()


async def test_consumer_subscribes_and_stores_ticks(monkeypatch):
    """End-to-end through the real AlpacaRealtimeFeed run loop with a fake
    stream: subscribe seeds the symbol set, a quote tick lands in the store,
    and stop() unblocks the loop cleanly. No socket is opened."""
    fake_stream = _FakeStream()
    feed = AlpacaRealtimeFeed(stream_factory=lambda: fake_stream)
    feed.subscribe(["SPY"])

    task = asyncio.create_task(feed.run())
    # WAIT for readiness; don't poll for a fixed budget. This used to be
    # `for _ in range(20): await asyncio.sleep(0.01)` — a 200ms wall-clock
    # allowance that is plenty on an idle machine and not enough on a loaded
    # one (caught failing while a docker build saturated the CPU). That made
    # the test measure host scheduling latency rather than the feed. The
    # timeout below is an upper bound for a hang, not a budget the happy path
    # spends: readiness normally arrives in microseconds.
    await asyncio.wait_for(fake_stream.ready.wait(), timeout=5.0)

    assert fake_stream.run_started
    assert "SPY" in fake_stream.subscribed

    # Drive a quote tick through the real handler → store.
    raw = type(
        "Q", (), {"symbol": "SPY", "bid_price": 99.0, "ask_price": 101.0,
                  "timestamp": datetime.now(timezone.utc)}
    )()
    await fake_stream.quote_handler(raw)
    assert feed.latest_quote("SPY") is not None
    assert feed.latest_quote("SPY").bid == 99.0

    # A trade tick refreshes `last`.
    traw = type("T", (), {"symbol": "SPY", "price": 100.5,
                          "timestamp": datetime.now(timezone.utc)})()
    await fake_stream.trade_handler(traw)
    assert feed.latest_quote("SPY").last == 100.5

    feed.stop()
    await asyncio.wait_for(task, timeout=5.0)   # loop exits cleanly
