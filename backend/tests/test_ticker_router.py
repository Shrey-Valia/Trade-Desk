"""Router tests for routers/ticker.py — success shapes + the 404 no-bars
path. The degraded-feed 503 path is already covered in test_resilience.py,
so this file focuses on the happy-path response envelopes for
detail / bars / chart / metrics / indicators, plus the genuine "no data"
404s.

Every external data call (get_quotes / get_bars / get_year_bars /
get_chain_snapshot / next_earnings_for) is monkeypatched on the
`routers.ticker` module so nothing touches the network.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

import routers.ticker as ticker
from calculations.types import ContractRow
from services.alpaca_client import Quote
from services.cache import cache

_ET = ZoneInfo("America/New_York")


@dataclass
class _Bar:
    """Minimal bar stub matching the attributes ticker.py reads off an
    Alpaca bar object (timestamp/open/high/low/close/volume)."""

    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: int


@pytest.fixture(autouse=True)
def _clear_cache():
    """ticker.py caches responses per (symbol, timeframe). Clear around
    each test so monkeypatched data on one test can't be served to the
    next from a stale cache entry. TTLCache has no public clear(), so we
    reset its backing store directly."""
    cache._store.clear()
    yield
    cache._store.clear()


def _intraday_bars(n: int = 30, start_price: float = 100.0) -> list[_Bar]:
    base = datetime(2026, 6, 26, 14, 0, tzinfo=ZoneInfo("UTC"))  # within RTH (10:00 ET)
    bars = []
    for i in range(n):
        px = start_price + i * 0.1
        bars.append(
            _Bar(
                timestamp=base + timedelta(minutes=5 * i),
                open=px,
                high=px + 0.5,
                low=px - 0.5,
                close=px + 0.2,
                volume=1000 + i,
            )
        )
    return bars


def _quote(symbol: str = "SPY", price: float = 100.0) -> Quote:
    return Quote(
        symbol=symbol,
        price=price,
        prev_close=99.0,
        day_high=101.0,
        day_low=98.0,
        day_volume=5_000_000,
    )


# -- /detail -----------------------------------------------------------------


def test_detail_success_shape(api_client, monkeypatch):
    monkeypatch.setattr(ticker, "get_quotes", lambda syms: {"SPY": _quote("SPY", 100.0)})
    # Year bars drive 52-wk hi/lo + 20d avg volume.
    year = [
        _Bar(
            timestamp=datetime(2026, 1, 1, tzinfo=_ET) + timedelta(days=i),
            open=50 + i,
            high=200 - i,  # max high = 199 at i=1
            low=10 + i,    # min low = 11 at i=1
            close=100,
            volume=2_000_000,
        )
        for i in range(1, 40)
    ]
    monkeypatch.setattr(ticker, "get_year_bars", lambda s: year)
    monkeypatch.setattr(ticker, "next_earnings_for", lambda s: None)

    res = api_client.get("/api/ticker/spy/detail")
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["symbol"] == "SPY"  # uppercased
    assert body["price"] == 100.0
    # change vs prev_close (99) → +1.0 / +1.01%
    assert round(body["change_dollar"], 2) == 1.0
    assert body["fifty_two_week_high"] == max(b.high for b in year)
    assert body["fifty_two_week_low"] == min(b.low for b in year)
    assert body["avg_volume_20d"] == 2_000_000
    assert body["next_earnings_date"] is None
    assert body["days_to_earnings"] is None


def test_detail_falls_back_to_snapshot_when_no_year_bars(api_client, monkeypatch):
    monkeypatch.setattr(ticker, "get_quotes", lambda syms: {"SPY": _quote("SPY", 100.0)})
    monkeypatch.setattr(ticker, "get_year_bars", lambda s: None)
    monkeypatch.setattr(ticker, "next_earnings_for", lambda s: None)

    res = api_client.get("/api/ticker/SPY/detail")
    assert res.status_code == 200, res.text
    body = res.json()
    # With no year bars, 52wk hi/lo fall back to the day high/low.
    assert body["fifty_two_week_high"] == 101.0
    assert body["fifty_two_week_low"] == 98.0
    assert body["avg_volume_20d"] == 5_000_000  # day_volume


def test_detail_computes_days_to_earnings(api_client, monkeypatch):
    monkeypatch.setattr(ticker, "get_quotes", lambda syms: {"SPY": _quote()})
    monkeypatch.setattr(ticker, "get_year_bars", lambda s: None)
    future = (datetime.now(_ET).date() + timedelta(days=7)).isoformat()
    monkeypatch.setattr(ticker, "next_earnings_for", lambda s: future)

    body = api_client.get("/api/ticker/SPY/detail").json()
    assert body["next_earnings_date"] == future
    assert body["days_to_earnings"] == 7


def test_detail_404_when_no_quote(api_client, monkeypatch):
    monkeypatch.setattr(ticker, "get_quotes", lambda syms: {})
    res = api_client.get("/api/ticker/ZZZZ/detail")
    assert res.status_code == 404
    assert "ZZZZ" in res.json()["detail"]


# -- /bars -------------------------------------------------------------------


def test_bars_success_shape(api_client, monkeypatch):
    bars = _intraday_bars(10)
    monkeypatch.setattr(ticker, "get_bars", lambda s, tf: bars)

    res = api_client.get("/api/ticker/spy/bars?timeframe=5m")
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["symbol"] == "SPY"
    assert body["timeframe"] == "5m"
    assert body["oi_source"] == "bars_only"
    assert len(body["bars"]) == 10
    first = body["bars"][0]
    assert set(first) == {"t", "o", "h", "l", "c", "v"}
    # /bars carries empty annotations (the overlay comes from /chart).
    ann = body["annotations"]
    assert ann["max_pain"] is None
    assert ann["call_wall"] is None


def test_bars_404_when_no_bars(api_client, monkeypatch):
    monkeypatch.setattr(ticker, "get_bars", lambda s, tf: [])
    res = api_client.get("/api/ticker/SPY/bars?timeframe=5m")
    assert res.status_code == 404
    assert "no bars" in res.json()["detail"]


def test_bars_404_when_get_bars_returns_none(api_client, monkeypatch):
    monkeypatch.setattr(ticker, "get_bars", lambda s, tf: None)
    res = api_client.get("/api/ticker/SPY/bars?timeframe=5m")
    assert res.status_code == 404


# -- /chart ------------------------------------------------------------------


def _sample_chain(spot: float = 100.0) -> list[ContractRow]:
    expiry = datetime.now(_ET).date() + timedelta(days=14)  # inside near-term window
    rows: list[ContractRow] = []
    for strike in (90.0, 95.0, 100.0, 105.0, 110.0):
        for typ in ("call", "put"):
            rows.append(
                ContractRow(
                    strike=strike,
                    expiry=expiry,
                    type=typ,
                    iv=0.25,
                    delta=0.5 if typ == "call" else -0.5,
                    gamma=0.01,
                    volume=500,
                    open_interest=1000,
                    bid=1.0,
                    ask=1.2,
                    last=1.1,
                )
            )
    return rows


def test_chart_success_with_annotations(api_client, monkeypatch):
    bars = _intraday_bars(20)
    chain = _sample_chain()
    monkeypatch.setattr(ticker, "get_bars", lambda s, tf: bars)
    monkeypatch.setattr(ticker, "get_quotes", lambda syms: {"SPY": _quote("SPY", 100.0)})
    monkeypatch.setattr(ticker, "get_chain_snapshot", lambda s, with_volume=True: chain)
    monkeypatch.setattr(ticker, "next_earnings_for", lambda s: "2026-07-15")

    res = api_client.get("/api/ticker/SPY/chart?timeframe=5m")
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["symbol"] == "SPY"
    assert len(body["bars"]) == 20
    # Native OI present → oi_source is open_interest.
    assert body["oi_source"] == "open_interest"
    ann = body["annotations"]
    assert ann["earnings_date"] == "2026-07-15"
    assert ann["max_pain"] is not None
    assert ann["call_wall"] is not None and ann["put_wall"] is not None
    # support/resistance derived from the chart's own bars
    assert "support_levels" in ann and "resistance_levels" in ann


def test_chart_volume_proxy_when_no_native_oi(api_client, monkeypatch):
    bars = _intraday_bars(20)
    chain = _sample_chain()
    for c in chain:
        c.open_interest = None  # force the volume proxy
    monkeypatch.setattr(ticker, "get_bars", lambda s, tf: bars)
    monkeypatch.setattr(ticker, "get_quotes", lambda syms: {"SPY": _quote()})
    monkeypatch.setattr(ticker, "get_chain_snapshot", lambda s, with_volume=True: chain)
    monkeypatch.setattr(ticker, "next_earnings_for", lambda s: None)

    body = api_client.get("/api/ticker/SPY/chart?timeframe=5m").json()
    assert body["oi_source"] == "volume_proxy"


def test_chart_handles_empty_chain(api_client, monkeypatch):
    """No chain → annotations stay mostly empty but bars + S/R still return."""
    bars = _intraday_bars(20)
    monkeypatch.setattr(ticker, "get_bars", lambda s, tf: bars)
    monkeypatch.setattr(ticker, "get_quotes", lambda syms: {"SPY": _quote()})
    monkeypatch.setattr(ticker, "get_chain_snapshot", lambda s, with_volume=True: None)
    monkeypatch.setattr(ticker, "next_earnings_for", lambda s: None)

    res = api_client.get("/api/ticker/SPY/chart?timeframe=5m")
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["oi_source"] == "open_interest"  # the no-chain default
    assert body["annotations"]["max_pain"] is None
    assert len(body["bars"]) == 20


def test_chart_404_when_no_bars(api_client, monkeypatch):
    monkeypatch.setattr(ticker, "get_bars", lambda s, tf: [])
    res = api_client.get("/api/ticker/SPY/chart?timeframe=5m")
    assert res.status_code == 404


# -- /indicators -------------------------------------------------------------


def test_indicators_success_shape(api_client, monkeypatch):
    bars = _intraday_bars(60)
    monkeypatch.setattr(ticker, "get_bars", lambda s, tf: bars)

    res = api_client.get("/api/ticker/SPY/indicators?timeframe=5m&set=sma:20,rsi:14,vwap")
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["symbol"] == "SPY"
    assert len(body["times"]) == 60
    keys = {s["key"] for s in body["series"]}
    assert "sma:20" in keys
    assert "rsi:14" in keys
    assert "vwap" in keys
    # Every series is bar-aligned.
    for s in body["series"]:
        assert len(s["values"]) == 60


def test_indicators_expands_multicomponent_macd(api_client, monkeypatch):
    bars = _intraday_bars(60)
    monkeypatch.setattr(ticker, "get_bars", lambda s, tf: bars)

    body = api_client.get("/api/ticker/SPY/indicators?timeframe=5m&set=macd").json()
    keys = {s["key"] for s in body["series"]}
    assert {"macd_line", "macd_signal", "macd_hist"} <= keys


def test_indicators_skips_unknown_tokens(api_client, monkeypatch):
    bars = _intraday_bars(30)
    monkeypatch.setattr(ticker, "get_bars", lambda s, tf: bars)

    body = api_client.get(
        "/api/ticker/SPY/indicators?timeframe=5m&set=sma:10,bogus,zzz99"
    ).json()
    keys = {s["key"] for s in body["series"]}
    assert keys == {"sma:10"}


def test_indicators_404_when_no_bars(api_client, monkeypatch):
    monkeypatch.setattr(ticker, "get_bars", lambda s, tf: [])
    res = api_client.get("/api/ticker/SPY/indicators?timeframe=5m&set=sma:20")
    assert res.status_code == 404


# -- /metrics ----------------------------------------------------------------


def test_metrics_success_shape(api_client, monkeypatch):
    chain = _sample_chain()
    monkeypatch.setattr(ticker, "get_chain_snapshot", lambda s, with_volume=True: chain)
    monkeypatch.setattr(ticker, "get_quotes", lambda syms: {"SPY": _quote("SPY", 100.0)})
    # No year bars → vrp stays None; iv_rank stays None (no history). Both fine.
    monkeypatch.setattr(ticker, "get_year_bars", lambda s: None)
    # _historical_iv30 queries the REAL app engine (SessionLocal), not the
    # test's in-memory DB. Stub it so iv_rank exercises the "not enough
    # history" branch without depending on the options_snapshots table.
    monkeypatch.setattr(ticker, "_historical_iv30", lambda s: [])

    res = api_client.get("/api/ticker/SPY/metrics")
    assert res.status_code == 200, res.text
    body = res.json()
    # All metric keys present (values may be None when inputs are sparse).
    assert set(body) == {
        "iv_rank",
        "iv_rank_status",
        "vrp",
        "skew_25d",
        "pc_ratio",
        "max_pain",
        "as_of",
        "served_stale",
    }
    # P/C ratio is computable from the chain volumes (equal call/put → 1.0).
    assert body["pc_ratio"] == pytest.approx(1.0)
    assert body["max_pain"] is not None


def test_metrics_handles_empty_chain(api_client, monkeypatch):
    monkeypatch.setattr(ticker, "get_chain_snapshot", lambda s, with_volume=True: None)
    monkeypatch.setattr(ticker, "get_quotes", lambda syms: {"SPY": _quote()})
    monkeypatch.setattr(ticker, "get_year_bars", lambda s: None)

    res = api_client.get("/api/ticker/SPY/metrics")
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["max_pain"] is None
    assert body["skew_25d"] is None
    assert body["iv_rank"] is None
