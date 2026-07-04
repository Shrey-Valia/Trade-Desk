"""get_live_option_quotes — the short-TTL live option-quote plane (audit D1).

The option SDK client is stubbed and the 300s chain snapshot is seeded
straight into the TTL cache, so no test touches the network. Buckets are
swapped for unthrottled ones so the paced fetches never sleep.
"""

from __future__ import annotations

import time as _time
from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from calculations.types import ContractRow
from config import settings
from services import alpaca_client
from services.alpaca_client import _ET, MarketDataUnavailable, get_live_option_quotes
from services.cache import cache
from services.rate_limit import TokenBucket, background_budget
from services.resilience import get_breaker, reset_breakers

TODAY = datetime.now(_ET).date()
OLD_TS = datetime(2026, 1, 2, 15, 0, tzinfo=timezone.utc)   # chain snapshot's as_of
LIVE_TS = datetime.now(timezone.utc)                        # a fresh quote print


def _chain_row(strike: float, side: str, *, bid=1.0, ask=1.2, expiry=None) -> ContractRow:
    return ContractRow(
        strike=strike,
        expiry=expiry or TODAY,
        type=side,
        iv=0.3,
        delta=0.5 if side == "call" else -0.5,
        gamma=0.01,
        volume=100,
        open_interest=None,
        bid=bid,
        ask=ask,
        last=1.1,
        as_of=OLD_TS,
    )


def _seed_chain(rows, sym="SPY", with_volume=0):
    cache.set(f"alpaca:chain_snap:{sym}:{with_volume}", rows, ttl_seconds=300)


def _occ(strike: float, side: str, sym="SPY") -> str:
    return alpaca_client._occ_symbol(sym, TODAY, side, strike)


def _sdk_quote(bid=2.0, ask=2.2, ts=LIVE_TS):
    return SimpleNamespace(bid_price=bid, ask_price=ask, timestamp=ts)


def _req_symbols(request) -> list[str]:
    syms = request.symbol_or_symbols
    return [syms] if isinstance(syms, str) else list(syms)


class _StubOptionClient:
    """Records latest-quote requests; answers from `quotes` or raises."""

    def __init__(self, quotes=None, error=None):
        self.quotes = dict(quotes or {})
        self.error = error
        self.requests = []

    def get_option_latest_quote(self, request):
        self.requests.append(request)
        if self.error is not None:
            raise self.error
        wanted = _req_symbols(request)
        return {s: q for s, q in self.quotes.items() if s in wanted}


def _patch_client(monkeypatch, stub):
    monkeypatch.setattr(alpaca_client, "_option_client", lambda: stub)


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    cache._store.clear()  # noqa: SLF001
    reset_breakers()
    monkeypatch.setattr(alpaca_client, "_interactive_bucket", TokenBucket(10_000.0, 10_000.0))
    monkeypatch.setattr(alpaca_client, "_background_bucket", TokenBucket(10_000.0, 10_000.0))
    yield
    cache._store.clear()  # noqa: SLF001
    reset_breakers()


# --- OCC symbol construction -------------------------------------------------


def test_occ_symbol_round_trips_through_parser():
    occ = alpaca_client._occ_symbol("SPY", date(2026, 7, 3), "call", 450.0)
    assert occ == "SPY260703C00450000"
    assert alpaca_client._parse_occ(occ) == (date(2026, 7, 3), "call", 450.0)

    occ_p = alpaca_client._occ_symbol("IWM", date(2026, 12, 31), "put", 187.5)
    assert occ_p == "IWM261231P00187500"
    assert alpaca_client._parse_occ(occ_p) == (date(2026, 12, 31), "put", 187.5)


# --- fresh serving + caching -------------------------------------------------


def test_serves_fresh_quotes_in_one_batched_request(monkeypatch):
    _seed_chain([
        _chain_row(450.0, "call"),
        _chain_row(449.0, "put"),
        # Tomorrow's 450 call must NOT satisfy a today-expiry request.
        _chain_row(450.0, "call", expiry=TODAY + timedelta(days=1)),
    ])
    stub = _StubOptionClient({
        _occ(450.0, "call"): _sdk_quote(2.0, 2.2),
        _occ(449.0, "put"): _sdk_quote(3.0, 3.4),
    })
    _patch_client(monkeypatch, stub)

    out = get_live_option_quotes("SPY", [(450.0, "call"), (449.0, "put")])

    assert set(out) == {(450.0, "call"), (449.0, "put")}
    row = out[(450.0, "call")]
    assert row.bid == 2.0 and row.ask == 2.2
    assert row.as_of == LIVE_TS  # the QUOTE's timestamp, not the chain's
    # Structure fields carry over from the snapshot row.
    assert row.iv == 0.3 and row.delta == 0.5 and row.last == 1.1
    assert out[(449.0, "put")].bid == 3.0
    # ONE batched request covering both contracts, on the configured feed.
    assert len(stub.requests) == 1
    assert sorted(_req_symbols(stub.requests[0])) == sorted(
        [_occ(450.0, "call"), _occ(449.0, "put")]
    )
    feed = stub.requests[0].feed
    assert getattr(feed, "value", feed) == settings.alpaca_options_feed


def test_caches_within_ttl(monkeypatch):
    _seed_chain([_chain_row(450.0, "call")])
    stub = _StubOptionClient({_occ(450.0, "call"): _sdk_quote(2.0, 2.2)})
    _patch_client(monkeypatch, stub)

    first = get_live_option_quotes("SPY", [(450.0, "call")])
    second = get_live_option_quotes("SPY", [(450.0, "call")])

    assert len(stub.requests) == 1  # second call served from the live cache
    assert second[(450.0, "call")].bid == first[(450.0, "call")].bid == 2.0


def test_max_age_zero_forces_a_refetch(monkeypatch):
    _seed_chain([_chain_row(450.0, "call")])
    stub = _StubOptionClient({_occ(450.0, "call"): _sdk_quote(2.0, 2.2)})
    _patch_client(monkeypatch, stub)

    get_live_option_quotes("SPY", [(450.0, "call")])
    stub.quotes[_occ(450.0, "call")] = _sdk_quote(2.5, 2.7)
    out = get_live_option_quotes("SPY", [(450.0, "call")], max_age_s=0.0)

    assert len(stub.requests) == 2
    assert out[(450.0, "call")].bid == 2.5


def test_refetches_once_the_window_elapses(monkeypatch):
    _seed_chain([_chain_row(450.0, "call")])
    stub = _StubOptionClient({_occ(450.0, "call"): _sdk_quote(2.0, 2.2)})
    _patch_client(monkeypatch, stub)
    clock = {"now": _time.monotonic()}
    monkeypatch.setattr(alpaca_client, "monotonic", lambda: clock["now"])

    get_live_option_quotes("SPY", [(450.0, "call")])
    clock["now"] += settings.live_option_quote_ttl_s + 1.0
    stub.quotes[_occ(450.0, "call")] = _sdk_quote(2.5, 2.7)
    out = get_live_option_quotes("SPY", [(450.0, "call")])

    assert len(stub.requests) == 2
    assert out[(450.0, "call")].bid == 2.5


def test_config_knob_tightens_the_window(monkeypatch):
    """live_option_quote_ttl_s = 0 → every call refreshes, regardless of the
    caller's (default) max_age_s."""
    monkeypatch.setattr(settings, "live_option_quote_ttl_s", 0.0)
    _seed_chain([_chain_row(450.0, "call")])
    stub = _StubOptionClient({_occ(450.0, "call"): _sdk_quote(2.0, 2.2)})
    _patch_client(monkeypatch, stub)

    get_live_option_quotes("SPY", [(450.0, "call")])
    get_live_option_quotes("SPY", [(450.0, "call")])

    assert len(stub.requests) == 2


# --- degradation -------------------------------------------------------------


def test_fetch_error_falls_back_to_chain_rows(monkeypatch):
    _seed_chain([_chain_row(450.0, "call"), _chain_row(449.0, "put")])
    stub = _StubOptionClient(error=RuntimeError("boom"))
    _patch_client(monkeypatch, stub)

    out = get_live_option_quotes("SPY", [(450.0, "call"), (449.0, "put")])

    assert set(out) == {(450.0, "call"), (449.0, "put")}
    row = out[(450.0, "call")]
    assert row.bid == 1.0 and row.ask == 1.2
    assert row.as_of == OLD_TS  # the fallback keeps its OLDER as_of


def test_open_breaker_short_circuits_to_chain_rows(monkeypatch):
    _seed_chain([_chain_row(450.0, "call")])
    stub = _StubOptionClient({_occ(450.0, "call"): _sdk_quote(2.0, 2.2)})
    _patch_client(monkeypatch, stub)
    breaker = get_breaker("alpaca")
    for _ in range(breaker.fail_threshold):
        breaker.record_failure()

    out = get_live_option_quotes("SPY", [(450.0, "call")])

    assert stub.requests == []  # CircuitOpenError raised before the SDK hop
    assert out[(450.0, "call")].bid == 1.0
    assert out[(450.0, "call")].as_of == OLD_TS


def test_stalled_sdk_call_falls_back(monkeypatch):
    _seed_chain([_chain_row(450.0, "call")])

    class _HangingClient:
        def get_option_latest_quote(self, request):
            _time.sleep(0.5)  # well past the shrunk deadline below
            return {}

    _patch_client(monkeypatch, _HangingClient())
    monkeypatch.setattr(settings, "alpaca_sdk_timeout_s", 0.05)

    out = get_live_option_quotes("SPY", [(450.0, "call")])

    assert out[(450.0, "call")].bid == 1.0  # chain-row fallback, no hang/raise


def test_symbol_missing_from_response_falls_back(monkeypatch):
    _seed_chain([_chain_row(450.0, "call"), _chain_row(449.0, "put")])
    stub = _StubOptionClient({_occ(450.0, "call"): _sdk_quote(2.0, 2.2)})  # no put
    _patch_client(monkeypatch, stub)

    out = get_live_option_quotes("SPY", [(450.0, "call"), (449.0, "put")])

    assert out[(450.0, "call")].bid == 2.0
    assert out[(450.0, "call")].as_of == LIVE_TS
    assert out[(449.0, "put")].bid == 1.0
    assert out[(449.0, "put")].as_of == OLD_TS


def test_empty_quote_prefers_chain_row(monkeypatch):
    _seed_chain([_chain_row(450.0, "call")])
    stub = _StubOptionClient(
        {_occ(450.0, "call"): SimpleNamespace(bid_price=None, ask_price=None, timestamp=LIVE_TS)}
    )
    _patch_client(monkeypatch, stub)

    out = get_live_option_quotes("SPY", [(450.0, "call")])

    assert out[(450.0, "call")].bid == 1.0
    assert out[(450.0, "call")].as_of == OLD_TS


# --- absent keys -------------------------------------------------------------


def test_keys_not_in_todays_chain_are_omitted(monkeypatch):
    _seed_chain([
        _chain_row(450.0, "call"),
        _chain_row(999.0, "call", expiry=TODAY + timedelta(days=7)),  # not 0DTE
    ])
    stub = _StubOptionClient({_occ(450.0, "call"): _sdk_quote(2.0, 2.2)})
    _patch_client(monkeypatch, stub)

    out = get_live_option_quotes(
        "SPY", [(450.0, "call"), (999.0, "call"), (123.0, "put")]
    )

    assert set(out) == {(450.0, "call")}
    # Only the resolvable contract was requested upstream.
    assert _req_symbols(stub.requests[0]) == [_occ(450.0, "call")]


def test_malformed_keys_are_skipped_not_raised(monkeypatch):
    _seed_chain([_chain_row(450.0, "call")])
    stub = _StubOptionClient({_occ(450.0, "call"): _sdk_quote(2.0, 2.2)})
    _patch_client(monkeypatch, stub)

    out = get_live_option_quotes(
        "SPY", [(450.0, "call"), ("not-a-strike", "call"), (450.0, "sideways")]
    )

    assert set(out) == {(450.0, "call")}


def test_returns_empty_when_chain_unavailable(monkeypatch):
    stub = _StubOptionClient({_occ(450.0, "call"): _sdk_quote()})
    _patch_client(monkeypatch, stub)
    monkeypatch.setattr(
        alpaca_client,
        "get_chain_snapshot",
        lambda sym, with_volume=True: (_ for _ in ()).throw(
            MarketDataUnavailable("SPY chain degraded")
        ),
    )

    out = get_live_option_quotes("SPY", [(450.0, "call")])

    assert out == {}
    assert stub.requests == []  # no OCC resolution → no quote request


def test_uncached_chain_resolves_via_get_chain_snapshot(monkeypatch):
    """When neither 300s variant is cached, the live path resolves through a
    normal get_chain_snapshot call (which self-caches)."""
    stub = _StubOptionClient({_occ(450.0, "call"): _sdk_quote(2.0, 2.2)})
    _patch_client(monkeypatch, stub)
    monkeypatch.setattr(
        alpaca_client,
        "get_chain_snapshot",
        lambda sym, with_volume=True: [_chain_row(450.0, "call")],
    )

    out = get_live_option_quotes("SPY", [(450.0, "call")])

    assert out[(450.0, "call")].bid == 2.0


def test_cached_live_quote_survives_chain_expiry(monkeypatch):
    """A fresh live cache line is served even after the 300s chain snapshot
    has expired — the live plane doesn't depend on the chain once warm."""
    _seed_chain([_chain_row(450.0, "call")])
    stub = _StubOptionClient({_occ(450.0, "call"): _sdk_quote(2.0, 2.2)})
    _patch_client(monkeypatch, stub)

    get_live_option_quotes("SPY", [(450.0, "call")])
    cache._store.pop("alpaca:chain_snap:SPY:0", None)  # noqa: SLF001
    monkeypatch.setattr(
        alpaca_client, "get_chain_snapshot", lambda sym, with_volume=True: None
    )
    out = get_live_option_quotes("SPY", [(450.0, "call")])

    assert out[(450.0, "call")].bid == 2.0
    assert len(stub.requests) == 1


# --- rate-bucket routing -----------------------------------------------------


class _RecordingBucket:
    def __init__(self):
        self.takes = 0

    def take(self, tokens: float = 1.0) -> float:
        self.takes += 1
        return 0.0


def test_live_fetch_uses_interactive_bucket_even_in_background(monkeypatch):
    """The order monitor runs under the background budget; live quotes must
    still draw the reserved interactive bucket so a stop check never queues
    behind a warming fan-out."""
    inter, back = _RecordingBucket(), _RecordingBucket()
    monkeypatch.setattr(alpaca_client, "_interactive_bucket", inter)
    monkeypatch.setattr(alpaca_client, "_background_bucket", back)
    _seed_chain([_chain_row(450.0, "call")])
    stub = _StubOptionClient({_occ(450.0, "call"): _sdk_quote(2.0, 2.2)})
    _patch_client(monkeypatch, stub)

    with background_budget():
        out = get_live_option_quotes("SPY", [(450.0, "call")])

    assert out[(450.0, "call")].bid == 2.0
    assert inter.takes == 1
    assert back.takes == 0
