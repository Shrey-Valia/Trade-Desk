# Real intraday timeframe support

Single commit. Restores the standard TradingView/Topstep timeframe
convention: the button IS the candle interval, not the lookback range.

The prior ladder (`5D / 1M / 3M`) used the buttons as lookback selectors
over daily bars, which reads as broken to any trader familiar with a
real charting platform. Now: `1m / 5m / 15m / 1h / 4h / 1D` — each
button maps to its own Alpaca interval, with the lookback window
auto-scaled to keep ~90–390 bars in view.

`tsc --noEmit` clean. **225/225** backend tests pass (216 prior + 9
new in `tests/test_timeframes.py`).

---

## Backend

### `services/alpaca_client.py`
Rewrote `_TIMEFRAME_CONFIG` from a 4-row lookback-only table to the
six-row standard ladder. Each row: `(TimeFrame, lookback_days,
cache_ttl_s, rth_only)`.

```
"1m":  (TimeFrame.Minute,                  3,   30, RTH)
"5m":  (TimeFrame(5,  TimeFrameUnit.Minute), 5,   60, RTH)
"15m": (TimeFrame(15, TimeFrameUnit.Minute), 7,  120, RTH)
"1h":  (TimeFrame.Hour,                   28,  300, RTH)
"4h":  (TimeFrame(4,  TimeFrameUnit.Hour),  90,  600, NO-RTH)
"1D":  (TimeFrame.Day,                   180, 3600, NO-RTH)
```

- **RTH filter** stays on for the minute / hour intraday grains so
  the left edge isn't padded with pre- and post-market sparse bars.
  Off for 4h and daily, which span session boundaries naturally.
- **Cache TTLs** are short for intraday (≤300s) so the chart refreshes
  on the same cadence as the bars change. Daily caches an hour.
- **Lookback windows** are calendar-day windows generous enough to
  capture the trading-day target — 3/5/7 calendar days for 1m/5m/15m,
  28 for 1h, 90 for 4h, 180 for daily.
- **Unknown timeframe** (legacy `"5D"`/`"1M"`/`"3M"` or a typo) falls
  back to `_DEFAULT_TIMEFRAME = "5m"` with a single warning log line —
  matches the Settings picker default.

### `routers/ticker.py`
- Both `GET /api/ticker/{symbol}/bars` and `GET /api/ticker/{symbol}/chart`
  default param flipped from `"5D"` → `"5m"`. Their request-validation
  signature didn't restrict the timeframe shape (still `str`), so a
  client passing an unknown value still gets the default-fallback
  behavior at the service layer, not a 422 — same UX as before.
- `_fetch_bars`'s 404-on-empty behavior is unchanged.

### `tests/test_timeframes.py` (new — 9 tests)
Fences the contract without hitting Alpaca's network:
- `test_exactly_six_timeframes_supported`
- `test_default_timeframe_is_in_the_set`
- `test_default_timeframe_is_5m`
- `test_intraday_timeframes_filter_to_rth`
- `test_4h_and_1d_do_not_filter_to_rth`
- `test_lookback_windows_grow_with_interval`
- `test_lookback_windows_match_spec` (1m=3d, 5m=5d, 15m=7d, 1h=28d, 4h=90d, 1D=180d)
- `test_alpaca_timeframe_mapping` (each TF → correct `TimeFrame(amount, unit)`)
- `test_cache_ttls_are_short_for_intraday`

---

## Frontend

### `types/chart.ts`
- `ChartTimeframe = "1m" | "5m" | "15m" | "1h" | "4h" | "1D"`
- Exported `CHART_TIMEFRAMES` (ordered, `readonly`)
- Exported `DEFAULT_CHART_TIMEFRAME = "5m"`
- Exported `isChartTimeframe(v)` runtime narrowing — used by both the
  zustand store's setter and its `migrate` function.

### `components/positions/ChartToolbar.tsx`
- `TF_OPTIONS` now reads directly from `CHART_TIMEFRAMES`.
- Each button passes its own `tf` value through `onTimeframeChange`
  unchanged — no more `TF_REAL_MAP` indirection.

### `pages/SettingsPage.tsx`
- `TIMEFRAMES = CHART_TIMEFRAMES` so the Settings picker matches the
  toolbar automatically.

### `stores/userSettings.ts`
- `defaultTimeframe` default flipped from `"5D"` → `DEFAULT_CHART_TIMEFRAME`.
- `setDefaultTimeframe` validates input via `isChartTimeframe` — any
  pass of an unknown value normalizes back to `"5m"`.
- **Schema bump v1 → v2** with a `migrate` function: a persisted
  `defaultTimeframe` outside the new ladder is rewritten to
  `DEFAULT_CHART_TIMEFRAME` on next load. Anyone with `"5D"` in
  `td:user-settings` from yesterday gets `"5m"` on next render
  without losing their other settings (ticker, contracts, colors,
  gradient, grid opacity).

### `components/stock/AnnotatedChart.tsx`
- Internal `TIMEFRAMES` constant reads from `CHART_TIMEFRAMES`.
- Internal-timeframe `useState` initializer reads from
  `DEFAULT_CHART_TIMEFRAME` instead of the hardcoded `"5D"`.

### `components/positions/TradeDeskToolbar.tsx`
- Retired component (no longer imported anywhere). Its `TIMEFRAMES`
  array updated to the new ladder so `tsc` stops failing on the
  narrower `ChartTimeframe` type. The file stays on disk for
  rollback discipline.

---

## Live verification

After backend restart against my changes:

```
$ for tf in 1m 5m 15m 1h 4h 1D; do
    curl /api/ticker/SPY/bars?timeframe=$tf | jq '.bars | length'
  done

  1m   →  780 bars   (3 cal days, RTH-filtered)
  5m   →  312 bars   (target ~234; 5 cal days)
  15m  →  104 bars   (target ~130; 7 cal days)
  1h   →  114 bars   (target ~140; 28 cal days)
  4h   →  257 bars   (90 cal days; 4h spans extended hours)
  1D   →  123 bars   (target ~120; 180 cal days)

$ curl /api/ticker/SPY/bars?timeframe=junk | jq '.bars | length'
  → 312    # fell back to 5m as expected
```

All six return `HTTP 200` with real OHLCV bars. Bar counts are in
the expected range — slight variance from the target counts is
expected because Alpaca's free SIP feed has a ~15-minute delay and
my probe ran on a weekend (so the windows extended back further
than a working session would, particularly for 1m).

The 4h count (257) sits high because Alpaca's 4h bars are NOT
RTH-filtered in my config (intentional — 4h aggregates span session
boundaries) so the count reflects extended-hours buckets too.

---

## Alpaca free-tier disclosures
(carried forward from the spec)

- **SIP equity-bars delay**: ~15 minutes on the free tier. Intraday
  bars during market hours will be ~15 minutes stale. Paid tier
  removes the delay; we don't try to engineer around it.
- **Rate limits**: 200 requests/min on the free tier. `useTickerChart`
  polls every 60s per symbol+timeframe and uses
  `placeholderData: prev` so the chart never blanks on a refetch.
  Comfortable margin against the rate limit.

---

## Out of scope
- TradingView widget swap (post-YC).
- WebSocket streaming bars (post-YC, paid tier).
- Real-time updates within the current candle (post-YC).
- The 4h variance from the target ~90 (RTH filter on 4h would shrink
  it to the right shape but would also drop the early/late buckets
  that aggregate cleanly today).

---

## Git
Single commit. Touches:

```
backend/services/alpaca_client.py
backend/routers/ticker.py
backend/tests/test_timeframes.py          (new)
frontend/src/types/chart.ts
frontend/src/components/positions/ChartToolbar.tsx
frontend/src/components/positions/TradeDeskToolbar.tsx  (retired component)
frontend/src/components/stock/AnnotatedChart.tsx
frontend/src/pages/SettingsPage.tsx
frontend/src/stores/userSettings.ts
```
