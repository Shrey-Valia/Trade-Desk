"""Chart timeframe config — the 1m/5m/15m/1h/4h/1D ladder.

Verifies the contract WITHOUT hitting Alpaca's network: the
_TIMEFRAME_CONFIG table is the single source of truth for which
timeframes the bars endpoint accepts, what Alpaca TimeFrame each
maps to, and how big the lookback window is. Live calls are
exercised by the running app + manual verification; this test
fences the config.
"""

from __future__ import annotations

from alpaca.data.timeframe import TimeFrame, TimeFrameUnit

from services.alpaca_client import _DEFAULT_TIMEFRAME, _TIMEFRAME_CONFIG


def test_exactly_six_timeframes_supported():
    assert set(_TIMEFRAME_CONFIG) == {"1m", "5m", "15m", "1h", "4h", "1D"}


def test_default_timeframe_is_in_the_set():
    assert _DEFAULT_TIMEFRAME in _TIMEFRAME_CONFIG


def test_default_timeframe_is_5m():
    assert _DEFAULT_TIMEFRAME == "5m"


def test_intraday_timeframes_filter_to_rth():
    # 1m / 5m / 15m / 1h are intraday and use the RTH filter so the
    # left edge isn't padded with sparse pre-market / post-market bars.
    for tf in ("1m", "5m", "15m", "1h"):
        _, _, _, rth_only = _TIMEFRAME_CONFIG[tf]
        assert rth_only is True, f"{tf} must use RTH filter"


def test_4h_and_1d_do_not_filter_to_rth():
    # Aggregated grains (4h, daily) span session boundaries naturally;
    # filtering breaks the bar shape.
    for tf in ("4h", "1D"):
        _, _, _, rth_only = _TIMEFRAME_CONFIG[tf]
        assert rth_only is False, f"{tf} must NOT use RTH filter"


def test_lookback_windows_grow_with_interval():
    # Lookback days should grow monotonically across the ladder —
    # 1m has the shortest window, 1D the longest. Catches a typo
    # that would put 1h above 1D etc.
    lookbacks = [
        _TIMEFRAME_CONFIG[tf][1]
        for tf in ("1m", "5m", "15m", "1h", "4h", "1D")
    ]
    for a, b in zip(lookbacks, lookbacks[1:]):
        assert a <= b, f"lookback ladder out of order: {lookbacks}"


def test_lookback_windows_match_spec():
    # Exact contract from the user spec — these values back the
    # ~120-390 bars-in-view target.
    expected_lookback_days = {
        "1m":  3,
        "5m":  5,
        "15m": 7,
        "1h":  28,
        "4h":  90,
        "1D":  180,
    }
    for tf, expected in expected_lookback_days.items():
        actual = _TIMEFRAME_CONFIG[tf][1]
        assert actual == expected, (
            f"{tf} lookback expected {expected}d, got {actual}d"
        )


def test_alpaca_timeframe_mapping():
    """Each chart timeframe maps to the correct Alpaca TimeFrame
    granularity. Catches a 5m→Minute or 4h→Hour swap."""
    expected = {
        "1m":  TimeFrame.Minute,
        "5m":  TimeFrame(5, TimeFrameUnit.Minute),
        "15m": TimeFrame(15, TimeFrameUnit.Minute),
        "1h":  TimeFrame.Hour,
        "4h":  TimeFrame(4, TimeFrameUnit.Hour),
        "1D":  TimeFrame.Day,
    }
    for tf, want in expected.items():
        got, _, _, _ = _TIMEFRAME_CONFIG[tf]
        # TimeFrame uses a NamedTuple-style equality (amount + unit).
        assert got.amount_value == want.amount_value, f"{tf} amount mismatch"
        assert got.unit_value == want.unit_value, f"{tf} unit mismatch"


def test_cache_ttls_are_short_for_intraday():
    # Intraday bars should NOT cache for an hour — they update every
    # minute or so during market hours. Cap intraday TTLs at 300s and
    # require daily bars to cache longer (>= 600s).
    for tf in ("1m", "5m", "15m", "1h"):
        _, _, ttl, _ = _TIMEFRAME_CONFIG[tf]
        assert ttl <= 300, f"{tf} cache TTL too long: {ttl}s"
    _, _, daily_ttl, _ = _TIMEFRAME_CONFIG["1D"]
    assert daily_ttl >= 600
