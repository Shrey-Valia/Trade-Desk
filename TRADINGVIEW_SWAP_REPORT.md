# TradingView widget swap — autonomous attempt, reverted

The swap was attempted and reverted per the user's explicit fallback
rule: "If after exploration Phase 2 cannot be made to work on the
free widget — REVERT all phases and restore the lightweight-charts
implementation. A working chart with no drawing tools beats a
TradingView widget with a broken breakeven overlay."

End state: **lightweight-charts implementation preserved unchanged**.
No commits. `tsc --noEmit` clean. `225/225` backend tests pass.

The failure is structural, not effort-bound: the free Advanced Chart
Widget does not expose the chart-introspection surface (events,
price-to-pixel APIs, post-construction methods) that an overlay
synchronized with pan/zoom requires. Documented in detail below so
this isn't re-attempted on the assumption that more effort would
crack it.

---

## What was attempted

### Phase 1 — TradingView widget integration (built, then reverted)

Replaced `frontend/src/components/stock/AnnotatedChart.tsx` with a
free TradingView widget embed. The implementation:

- Loaded `https://s3.tradingview.com/tv.js` once per page (cached
  promise so multiple charts don't re-fetch).
- Mapped our internal symbols to TV's `EXCHANGE:SYMBOL` format
  (`SPY` → `AMEX:SPY`, `QQQ` → `NASDAQ:QQQ`, `SPX` → `SP:SPX`, etc.).
- Mapped our `ChartTimeframe` ladder to TV's interval codes
  (`1m`→`"1"`, `5m`→`"5"`, `15m`→`"15"`, `1h`→`"60"`, `4h`→`"240"`,
  `1D`→`"D"`).
- Constructed `new window.TradingView.widget({ ... })` with
  `theme: "dark"`, `style: "1"` (candlestick), `toolbar_bg: "#131722"`
  (our bg-tier-0), `hide_side_toolbar: false` (drawing tools on),
  `hide_top_toolbar: false` (indicators on), `allow_symbol_change:
  false` (header search owns the symbol).
- Remounted on `symbol` or `timeframe` change (no post-construction
  setSymbol on the free widget).

**Verification**: the widget rendered cleanly. SPY candlesticks at
the 5m interval, drawing-tool sidebar on the left, indicators
dropdown on top, our TD logo in the rail, full chrome and ticker
search wired through correctly. Screenshot at
`screenshots/tradingview_phase1_attempt.png`.

### Investigation — what the free widget actually exposes

Before committing Phase 1, I attached a `window` message listener
and recorded everything the iframe broadcast over the page's
lifetime (initial load + a synthesized chart pan + 6+ seconds of
idle).

```js
window.__tvMessages = [];
window.addEventListener("message", (e) => window.__tvMessages.push(e));
// ... interact with chart ...
window.__tvMessages.length  →  0
```

**Total messages from the TradingView iframe: zero.** Including
during pan and after the chart was clearly responsive. This was
the disqualifying find.

Cross-checked via `window.TradingView.widget`'s return value: the
constructor returns an `iframeId`-style stub without `chart()`,
`activeChart()`, `subscribe()`, `priceToCoordinate()`, or
`onChartReady()` — all of which the user spec assumed were
available. Those APIs belong to TradingView's **paid Charting
Library**, distributed via a private GitHub repo (`github.com/
tradingview/charting_library` 404s on public web until you've been
approved). The free widget at `s3.tradingview.com/tv.js` is a
configuration-only embed.

Without `postMessage` events for visible-range / pan / zoom AND
without a programmatic price-to-coordinate function, an overlay div
positioned over the iframe cannot follow the chart as the user
interacts with it. The best a host can do is compute a price-Y
mapping from `/api/ticker/.../bars` data and hope the user doesn't
pan or zoom — which is exactly the "breakevens jitter on pan/zoom"
failure mode the spec explicitly called out as unacceptable.

### Phase 2 — not attempted

Per the spec: "If Phase 2 cannot land (the breakeven overlay can't be
rebuilt cleanly on TV widget) — STOP." The investigation completed
above made the conclusion clean enough to skip the attempt itself.
Trying Option B (overlay div with computed Y from bars data) would
have produced a visually broken overlay the moment the chart was
panned or zoomed, which is worse than not shipping the swap.

### Phase 3–5 — not attempted (dependent on Phase 2)

---

## Revert mechanics

The Phase 1 implementation was written and verified working
visually but **was never committed**. The working-tree change was
reverted via `git checkout HEAD -- frontend/src/components/stock/
AnnotatedChart.tsx`. The codebase is bit-identical to the
pre-attempt state:

```
$ git status
On branch main
nothing to commit, working tree clean

$ git log --oneline -3
6863752  Real intraday timeframe support: 1m/5m/15m/1h/4h/1D...
d0778c3  REWORK_SATURDAY.md: fix Phase 3 commit hash
101553f  Phase 3: Polish — CLOSE button restyle, ...
```

The Phase 1 screenshot (`screenshots/tradingview_phase1_attempt.png`)
is kept as evidence of what the chart looked like during the
attempt, in case the question comes back later.

---

## Why this isn't fixable by trying harder

This is the structural reality of the free Advanced Chart Widget,
documented here so the next sprint doesn't burn budget on a re-try:

1. **Cross-origin iframe.** The TV chart is served from
   `s.tradingview.com` and the host page is on `localhost:5173` (or
   prod). Same-origin policy blocks all introspection of the iframe's
   internal DOM, computed styles, scroll position, etc.

2. **No `postMessage` channel.** The widget's iframe broadcasts
   nothing the host can subscribe to. Empirically verified above.

3. **No programmatic API surface.** `new TradingView.widget(config)`
   returns an opaque object. The `chart()`, `activeChart()`,
   `subscribe()`, `createShape()`, `priceToCoordinate()`,
   `getVisibleRange()`, and `onChartReady()` methods are all on the
   PAID Charting Library, not the free widget.

4. **No drawing config.** The widget config accepts `studies` (an
   array of indicator IDs) and `saved_data` (paid-tier load), but
   not a "shapes" or "drawings" config that would let the host
   pre-seed horizontal lines.

5. **Approximation doesn't survive interaction.** If we computed
   the price-Y mapping ourselves from `/api/ticker/.../bars` min/max,
   the overlay would be correct ONLY when the user hasn't panned or
   zoomed. The moment they do, the SVG line stays at the same screen
   Y while the chart's price scale moves underneath it — the
   overlay would point to the wrong price.

The only path to TradingView visuals with a working overlay is
either:
- **Apply for Charting Library access** (TradingView's
  application form at the docs site; gating is opaque, "for
  brokerage and prop firm applicants" — probably qualifies us
  long-term, not in time for YC).
- **Self-host an open-source TradingView clone** with full API
  control (Klinecharts, Highcharts Stock, lightweight-charts +
  custom plugins). We're already on lightweight-charts; the
  drawing-tool / indicators gap is the real issue, and that
  needs its own engineering effort to solve.

---

## What stays as-is

- `frontend/src/components/stock/AnnotatedChart.tsx` —
  unchanged; lightweight-charts implementation continues to drive
  the candle render, BE overlay, entry marker, theta scrubber, and
  KEY LEVELS overlays.
- `frontend/src/components/positions/ChartToolbar.tsx` —
  unchanged; six-button timeframe ladder + LEGEND/LEVELS↓ controls.
- `frontend/src/types/chart.ts` — unchanged; CHART_TIMEFRAMES
  + DEFAULT_CHART_TIMEFRAME exports continue to work.
- `frontend/src/stores/chartPrefs.ts` — unchanged; the
  `showMarketAnnotations` toggle still drives KEY LEVELS overlays.
- All trading math, MLL/tier math, account state — untouched.

The two-magenta-lines bug (B-001 in AUDIT.md, fixed in commit
070fb28) is also preserved — single-leg positions still render
ONE magenta breakeven line, straddles still render TWO. That fix
is independent of the chart engine.

---

## What this means for the YC submission

The product retains the moving-breakeven hook (the YC
differentiator) on lightweight-charts. The cost is the gap that
prompted this attempt:

- **No drawing tools.** Users cannot draw a trendline, fib, or
  horizontal-line annotation on the chart. Compared to TradingView /
  Topstep / TOS, this is a visible UX gap. For a 60-second demo
  video, the workaround is to avoid showcasing "drawing on the
  chart" entirely — focus on the breakeven hook, the chain ladder,
  and the combine tier system.
- **No indicators dropdown.** RSI / MACD / EMA / Bollinger — none
  available. Same demo-video workaround.
- **Three toolbar stubs (`candles ▾`, drawing icons, `indicators ▾`)
  are already hidden** in commit 070fb28's Phase 1 fix, so the
  toolbar doesn't visibly advertise functionality it doesn't have.

The breakeven hook still WORKS — it's the single most important
piece of the product for the YC narrative. Trade-off accepted:
real BE overlay > drawing tools on the YC submission timeline.

---

## Recommended follow-up (post-YC)

Rank by realism:

1. **Apply for Charting Library access.** No cost; gate is approval-
   based. If approved, swap with Phase 1 + Phase 2 actually
   feasible (the Charting Library exposes `createShape({ shape:
   "horizontal_line", ... })` which natively tracks the chart). 1–4
   week turnaround.

2. **Self-build drawing-tool + indicator support on top of
   lightweight-charts.** Significant scope (probably 2–4 weeks of
   focused work for the basics) but uses the engine we already
   control. Open-source plugins exist for some indicators.

3. **Replace lightweight-charts with a different open-source
   library that has drawing tools.** Klinecharts has a richer
   built-in toolset; Highcharts Stock has commercial-licensed
   drawing tools. Each is its own evaluation cycle.

Not recommended:
- **Re-attempting the free widget.** No additional engineering
  effort solves the structural API gap.

---

## File-level summary

```
Files modified during the attempt:
  frontend/src/components/stock/AnnotatedChart.tsx  (written, then reverted)

Files committed:
  (none)

Files left on disk:
  screenshots/tradingview_phase1_attempt.png        (evidence of what rendered)
  TRADINGVIEW_SWAP_REPORT.md                        (this file)
```

End state matches start state byte-for-byte except for two
documentation artifacts. No code changes ship.
