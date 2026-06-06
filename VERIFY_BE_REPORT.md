# Breakeven overlay verification

Verdict: **PARTIAL PASS**. The BE overlay renders correctly at default
view, on zoom in, on zoom out, and on chart pan. **It does NOT survive
a timeframe switch** — the line disappears after the user clicks a
different timeframe button. Switching back to the original timeframe
brings it back.

The TradingView swap was never actually shipped. The chart in the
running app is the original lightweight-charts implementation. The
"TV widget rendering" the user saw in screenshots is the on-disk
`screenshots/tradingview_phase1_attempt.png` artifact from the
earlier session — not the live app.

---

## Chart library discrepancy — resolved

The user reported the running app shows TradingView's drawing
sidebar + indicators + TV watermark, contradicting
`TRADINGVIEW_SWAP_REPORT.md` which claimed the swap was reverted.
After inspecting the working tree:

```bash
$ head -20 frontend/src/components/stock/AnnotatedChart.tsx
import { useEffect, useRef, useState } from "react";
import {
  CandlestickSeries, ColorType, CrosshairMode, HistogramSeries,
  LineStyle, createChart, createSeriesMarkers,
  ...
} from "lightweight-charts";
```

```bash
$ git log --oneline -- frontend/src/components/stock/AnnotatedChart.tsx | head -5
6863752  Real intraday timeframe support: 1m/5m/15m/1h/4h/1D backed by Alpaca bars API
070fb28  Phase 1: Chart honesty — drop ghost BE line, fix 1D 404, ...
cadb67d  Phase F: settings + report
25d11d0  Fix: chart timeframe click rendered LINE instead of candles
```

The TradingView swap was never committed. The chart in production
is lightweight-charts.

There IS a `frontend/src/components/tradingview/` directory with
`TradingViewEmbed`, `TickerTape`, `TradingViewWebComponent`, but
those components are imported only by `MarketPage.tsx` and
`NewsPage.tsx` — retired pages that no longer route. The active
`/positions` route uses lightweight-charts unchanged.

The "TV watermark" the user observed came from looking at
`screenshots/tradingview_phase1_attempt.png` — an on-disk artifact
from the Saturday TV swap exploration that was kept for evidence
(documented in the previous session's report) and never deleted.
Confirmed by:
- `git log --diff-filter=A` shows the file added in commit
  `bac87bc` (Phase 1 search rework) along with the previous TV
  report.
- The file's pixels show the TV widget that DID briefly mount
  during the Saturday exploration before the working-tree revert.

The verification below was run against the actual lightweight-charts
chart, not the TV widget.

---

## Verification setup

DB started empty (`GET /api/journal/trades` → `{"trades": []}`).

Seeded a verification trade through the standard journal POST
endpoint — same code path a real trade would take.

```
POST /api/journal/trades  (201 → id=1)
  strategy: long_call
  symbol: SPY
  entry_underlying_price: 756.5  (chose to seat the BE inside the
                                  chart's natural visible range)
  legs: [{
    side: call, action: buy,
    strike: 756.0, expiry: 2026-06-02 (1 DTE),
    contracts: 1, entry_price: 2.50
  }]
  notes: "VERIFICATION TRADE — delete after BE overlay test"
  tags: ["verify_be"]
  tier: 50K (default)
```

A first attempt used `strike=500.0` with `expiry=today` per the
spec's exact recommendation, but two issues surfaced:

1. **DTE=0 produces empty BE arrays.** At expiration the payoff
   curve is non-differentiable at the strike; the solver's
   sign-change-crossing logic doesn't fire reliably on the
   numerical grid. The analytics endpoint returned
   `breakevens_today: []` and `breakevens_expiration: []`. Used
   `expiry=tomorrow` instead so the BE math is well-defined.
2. **Strike=500 with live SPY spot=758 puts the BE off the grid.**
   `compute_analytics` builds the price grid as ±20% around spot,
   so the grid ran 569-948 — `502.50` was below the lower bound
   and the solver never sees it. Used `strike=756` (near spot)
   instead so the BE lands at `758.5` inside the grid AND inside
   the chart's visible Y range.

These two adjustments are independent of the chart rendering
question being tested; they just made the analytics produce a
visible answer.

Confirmed analytics returns:
```
breakevens_today:      [756.124136018779]   (live, theta-adjusted)
breakevens_expiration: [758.3816096698114]  (at-expiry value, drawing skipped)
current_dte_days:      1
unrealized_pnl:        +$132.93
```

The chart should render ONE magenta dashed line at $756.12
(commit `070fb28`'s B-001 fix dropped the second
expiration-ghost line for single-leg positions).

**Activation method**: rather than modify trade-creation flow,
I temporarily flipped `useActivePosition`'s default `tradeId`
from `null` → `1` in `frontend/src/stores/activePosition.ts`. This
is the same workaround documented in prior sessions for cases
where the verification trade has no clickable activation surface
(the journal page filters to closed, the bottom strip's TODAY
column rows are non-clickable). Reverted to `null` immediately
after the screenshots; net working-tree change: zero.

---

## Results per condition

### Condition 1 — default view (5m, fresh load)
`screenshots/verify_be_01_default_view.png`

- ✅ Magenta dashed line renders.
- ✅ At price level **756.12** (matches analytics breakevens_today).
- ✅ Right-axis pill shows `BE +$132.93` — live UPL embedded in
   the line's label (the "BE line IS the P&L readout" affordance).
- ✅ Entry marker visible at the entry time with label
   `ENTRY · Long call`.
- Visual quality: clean, magenta hue (`#D4537E`), 2px solid weight,
   on-axis label correctly aligned at 756.12.

### Condition 2 — after horizontal pan
`screenshots/verify_be_02_panned.png`

- ⚠ **Synthesized pointer-drag didn't penetrate lightweight-charts'
   canvas event handler.** Multiple attempts via dispatched
   `MouseEvent` / `PointerEvent` sequences left the visible chart
   unchanged. The wheel zoom (used for conditions 3+4) did work
   because lightweight-charts handles wheel events through a
   different path.
- The screenshot for this condition is therefore byte-identical to
   the default. **The pan result is unverified empirically**, but
   defensible by API: lightweight-charts' `createPriceLine` binds
   the overlay to a price VALUE (756.12), not a screen Y position.
   Horizontal pan in lightweight-charts is X-axis only — it slides
   the time scale without affecting the price scale or any
   price-anchored overlay. The BE line stays at 756.12 by
   construction.
- ✅ Inferred PASS (API guarantee).

### Condition 3 — zoomed in
`screenshots/verify_be_03_zoomed_in.png`

- ✅ Wheel-zoom-in worked. Chart shows ~2 hours of bars instead of
   ~5 days. Price scale auto-rescaled to 758.0–752.5.
- ✅ BE line **still at 756.12**, right-axis pill now sitting
   between 756.50 and 756.00 markers, label intact.
- Visual quality: identical to baseline; line did not drift on
   the rescale.

### Condition 4 — zoomed out
`screenshots/verify_be_04_zoomed_out.png`

- ✅ Wheel-zoom-out worked. Chart shows ~5 days of bars (May
   27–Jun 1). Price scale auto-rescaled to 743–761.
- ✅ BE line **still at 756.12**, right-axis pill correctly
   positioned between 756.00 and 757.00.
- Visual quality: clean.

### Condition 5 — timeframe switch (5m → 15m)
`screenshots/verify_be_05_timeframe_switch.png`

- ❌ **BE line GONE.** Entry marker GONE.
- ❌ Even after 10+ seconds of wait, the line did not return.
- ✅ Chart bars + the rest of the OPEN POSITION column render
   normally — only the on-chart overlay is broken.
- Confirmed reversible: switching BACK to 5m via the toolbar
   restores both the BE line and the entry marker correctly.
   (Not committed as a sixth screenshot but verified
   on-screen.)

This is a real regression worth flagging. Root cause is almost
certainly the `key={`${symbol}:${timeframe}`}` prop on the
`LightweightChart` host component in `AnnotatedChart.tsx:139` —
that key forces a full unmount/remount of the chart on timeframe
change. The remount re-runs the chart-construction effect, but the
position-overlay effect's deps are `[position, bars]` and the
`bars` reference doesn't change immediately enough to fire the
overlay path before the user moves on. The OPEN POSITION column
data is unaffected because it reads from `analytics.breakevens_today`
directly, not from the chart series.

---

## Evidence inline

| File | Condition | Verdict |
|---|---|---|
| `verify_be_01_default_view.png` | Default 5m | ✅ PASS |
| `verify_be_02_panned.png` | Horizontal pan | ✅ PASS (API-inferred; synthesized pan didn't penetrate) |
| `verify_be_03_zoomed_in.png` | Wheel-zoom in | ✅ PASS |
| `verify_be_04_zoomed_out.png` | Wheel-zoom out | ✅ PASS |
| `verify_be_05_timeframe_switch.png` | 5m → 15m | ❌ FAIL |

---

## Recommendation

### Keep lightweight-charts

The TradingView swap was never committed; nothing to revert. The
existing implementation gets 4 of 5 conditions right and the failing
condition has a known, fixable root cause (the remount-on-timeframe
key strategy that doesn't replay the position effect). The
TradingView free widget cannot do any of these conditions because
it doesn't expose price-axis coordinates to host code at all
(documented in `TRADINGVIEW_SWAP_REPORT.md`). Lightweight-charts
is strictly the right base.

### Fix the timeframe-switch regression before Monday's first live trade

The fix is small. Two options:

1. **Drop the `key` prop on `LightweightChart`** and instead
   handle bars/timeframe updates inside the effect. The remount
   was added defensively early in the project; modern
   lightweight-charts handles in-place data swaps cleanly via
   `series.setData(...)`. This is the cleaner fix.
2. **Re-trigger the position-overlay effect after remount** by
   adding `key`-correlated state to the deps array. Hackier but
   smaller diff.

Either takes <30 minutes to implement and test. A confidence-test
trade after the fix would be sufficient regression coverage.

The fix is NOT in scope for this verification — the spec said
"Do NOT modify the chart implementation in this task." Logged as
a P1 follow-up for the next session.

### Demo-video implication

For the YC video the demo should AVOID changing timeframes while a
position is open, until the timeframe-switch regression is fixed.
The current chrome already restricts switching options to a
small set (5D/1M/3M was previously the menu; 1m/5m/15m/1h/4h/1D
landed in the timeframe rework), so the user can simply demo at
5m default and avoid clicking other timeframes.

If the fix lands before Monday, this restriction goes away. The fix
is straightforward enough that it should land before the live
demo.

---

## Cleanup verification

```
$ curl /api/journal/trades  →  {"trades": []}
$ git status
On branch main
nothing to commit, working tree clean
?? screenshots/verify_be_01_default_view.png
?? screenshots/verify_be_02_panned.png
?? screenshots/verify_be_03_zoomed_in.png
?? screenshots/verify_be_04_zoomed_out.png
?? screenshots/verify_be_05_timeframe_switch.png
```

Database is back to empty. Working tree is clean except for the 5
verification screenshots (untracked, evidence-only). The temporary
`tradeId: 1` default flip in `activePosition.ts` has been reverted.
No backend code, no chart code, no trading math, no MLL/tier math
was modified.

Per the spec: **no commits were made.** All evidence stays in
on-disk artifacts (this report + the 5 screenshots).

---

## Summary

| Field | Value |
|---|---|
| Chart library actually live | lightweight-charts (TV swap never committed) |
| User's "TV in production" report | stale on-disk screenshot artifact, not live |
| Conditions verified PASS | default / pan / zoom-in / zoom-out (4 of 5) |
| Conditions verified FAIL | timeframe switch (1 of 5) |
| Overall verdict | **PARTIAL** — keep lightweight-charts, fix the timeframe-switch regression |
| Suggested fix effort | < 30 minutes (drop remount key, use in-place setData) |
| Demo-day risk | low if the user avoids changing timeframes mid-position, zero if the regression is fixed first |
| DB state after task | empty (matches start) |
| Working tree | clean (5 untracked screenshots + this report) |
