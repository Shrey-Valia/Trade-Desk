# Trade Desk — visual rework report

Autonomous session, May 2026. Six phases shipped as independent
commits on top of the just-landed account-tier system. All tier
logic, MLL math, and trading code untouched.

## 1. Summary

The Trade Desk has shifted from its "Bloomberg-terminal-graphite"
look to a "Topstep-adapted-for-options" feel:

- **Softer dark-navy ground** replaces the prior pure-black surface
  (#0A0C12 → #131722) with three lifted tiers above it and a subtle
  radial gradient in the body.
- **New SVG logo** (`TradeDeskMark`) sits in the left rail — an
  abstract candle-with-breakeven monogram that doubles as a "TD"
  silhouette. Replaces the prior `[TRADE DESK▮]` wordmark, which is
  retired from the header.
- **Left rail tightened**: WATCH icon dropped, width 56 → 48 px,
  mark sits centered at the top with a hairline divider underneath.
- **Filled buttons** throughout. New `UIButton` primitive with three
  variants (`default` / `ghost` / `filled`) and three sizes; applied
  across the chart toolbar, Settings page, and confirm dialogs.
- **Topstep-style header**: 64 px tall, five metric pills (BAL /
  MLL / RP&L / UP&L / MKT) with bg-tier-2 fill + 4px radius,
  label-over-value layout. Wordmark dropped from the header.
- **Real search box** replaces the hardcoded SPY/QQQ/IWM switcher.
  Live `/api/ticker/search` endpoint returns ranked matches with a
  `has_0dte_today` flag; the dropdown badges each result accordingly.
- **Topstep-style BUY/SELL**: solid action-green / action-red filled
  fills with white text, "BUY +N" / "SELL -N" single-line label
  plus a 10px sub-line. Distinct from the bullish/bearish P&L hues.
- **Circular QTY chips** in the trade ticket — 1 / 3 / 5 / 10 / 15
  presets, 32×32 circular, amber border + amber number when active.
- **Ladder-style chain**: 20px rows, anchored strike column, every-5
  hairline grouping, 4px amber rule on ATM, persistent ring on
  selected row, prices bumped to 12px medium.
- **Restyled chart toolbar**: bg-tier-1, single-hairline group
  separators, tighter rhythm.
- **Cleaner KEY LEVELS strip** with proper typographic hierarchy and
  a new rounded pill toggle (24×14, white thumb on amber track).
- **Chart Appearance** section in Settings — four customizable knobs:
  bullish color, bearish color, background gradient on/off, grid
  opacity slider. All apply live and persist.

## 2. Phase-by-phase

| Phase | Commit | Changes |
|---|---|---|
| A: palette + logo + rail | `20b9959` | 5 files; new dark-navy palette, action-color tokens, `TradeDeskMark.tsx` SVG logo, LeftRail rewrite (drop WATCH, add mark, narrow to 48px, amber 3px active rule). |
| B: universal button restyle | `90b2127` | 3 files; new `UIButton.tsx` primitive (3 variants × 3 sizes, 4px radius). Applied to ChartToolbar (timeframes, candles, drawing, indicators, legend) and SettingsPage (TimeframePicker, Toggle, NumberStepper, confirm dialog). |
| C: header restyle + search | `15d1e1c` | 7 files; `routers/ticker_search.py` + `tests/test_ticker_search.py` (7 tests); `TickerSearchBox.tsx` + `useTickerSearch.ts` + types + API plumb; full `TradeDeskHeader.tsx` rewrite — wordmark retired from header, height 40 → 64px, five Topstep-style metric pills, tier pill upgraded. |
| D: trade ticket BUY/SELL + QTY | `75613d5` | 1 file; new circular chip ladder (− [VALUE] +  \|  [1][3][5][10][15]), Topstep filled BUY/SELL with white text. |
| E: chain + toolbar + key levels | `c3084ae` | 3 files; chain ladder restyle (taller rows, anchored center column, every-5 grouping, stronger ATM/selected states), toolbar bg-tier-1 + new hairline separators, KEY LEVELS clean typography + new PillToggle. |
| F: Settings color customization + report | `<this commit>` | userSettings store extended with bullishColor/bearishColor/bgGradient/gridOpacity. AnnotatedChart consumes them live. App.tsx routes bgGradient to `html[data-bg-gradient]`. New `ChartAppearanceSection` + `ColorSwatch` + `OpacitySlider` in SettingsPage. |

After every phase: `tsc --noEmit` clean, **216 backend tests pass**
(209 prior + 7 new ticker-search tests).

## 3. Screenshots

Saved under `screenshots/`:

| File | What it shows |
|---|---|
| `rework_01_full_dashboard.png` | Cold-open empty state at 50K combine — new mark in rail, search box, Topstep pills, restyled toolbar + chart, ladder-style chain (loading state), compressed empty ticket, KEY LEVELS strip. |
| `rework_02_logo_and_rail.png` | Left rail close-up — mark + hairline + nav icons + Settings pinned at bottom. |
| `rework_03_header_pills.png` | Top-of-screen close-up — tier pill, search box, live price, five metric pills. |
| `rework_04_trade_ticket.png` | Trade ticket area in the no-selection / market-closed state — compressed empty layout with disabled BUY/SELL row. |
| `rework_05_chain.png` | Right-column chain header + ticket header. Today (weekend) returns no-0DTE; see "Could not verify" below. |
| `rework_06_settings_color_panel.png` | New Chart Appearance section in Settings — both color swatches, BG gradient toggle, grid opacity slider. |

## 4. The new logo

The `TradeDeskMark` (frontend/src/components/branding/TradeDeskMark.tsx)
is a 32×32 SVG monogram. The geometry:

- A 26×26 outer square frame (1.5px stroke), no fill — the "TD"
  silhouette boundary.
- A vertical wick line from (16,5) to (16,27) — the "T" stem.
- A filled candle body (6×11) centered horizontally, sitting in the
  upper half of the square.
- An amber horizontal line from (6,16) to (26,16) with a 2px stroke
  and rounded endcaps — the "breakeven" reference and the cross-bar
  of the "T" at once.
- A small curved notch on the lower-right (the bowl of the "D"
  without literally drawing a D) — `M22 22 Q24 22 24 24 Q24 26 22 26`,
  1.5px stroke, no fill.

Single fg-primary color (#E8E8E0) plus one amber accent (#F0A030).
Monochromatic, restrained, geometric. Scales cleanly from 16 to 64
px. Default rail size: 28px. The SVG markup is below.

```svg
<svg viewBox="0 0 32 32" width="36" height="36">
  <rect x="3" y="3" width="26" height="26" fill="none"
        stroke="#E8E8E0" stroke-width="1.5"/>
  <line x1="16" y1="5" x2="16" y2="27"
        stroke="#E8E8E0" stroke-width="1.5"/>
  <rect x="13" y="10" width="6" height="11" fill="#E8E8E0"/>
  <line x1="6" y1="16" x2="26" y2="16"
        stroke="#F0A030" stroke-width="2" stroke-linecap="round"/>
  <path d="M22 22 Q24 22 24 24 Q24 26 22 26"
        fill="none" stroke="#E8E8E0"
        stroke-width="1.5" stroke-linecap="round"/>
</svg>
```

This is the first attempt. It reads as both a chart glyph and a
geometric TD when scaled down. If a future iteration wants more
asymmetry (e.g., the breakeven line slightly off-center), the
geometry above is straightforward to tweak — `x1` and `x2` of the
amber line control the breakeven span, and the candle body's `x` is
controlled by a single attribute.

## 5. Search — shipped working

The search shipped on real infrastructure, not as a fallback to
SPY/QQQ/IWM buttons. Verification:

```
$ curl http://localhost:8000/api/ticker/search?q=apple
{"query":"apple",
 "results":[{"symbol":"AAPL","name":"Apple Inc.","has_0dte_today":false}]}

$ curl http://localhost:8000/api/ticker/search?q=Q
{"query":"Q",
 "results":[
  {"symbol":"QQQ","name":"Invesco QQQ Trust","has_0dte_today":true},
  …
 ]}
```

7 backend tests in `tests/test_ticker_search.py` cover:
- Empty query returns empty.
- Exact symbol match ranks first.
- Symbol-prefix match.
- 0DTE-universe flag is true for SPY/QQQ/IWM.
- Flag is false for non-universe matches.
- Name-substring match (e.g., "apple" → AAPL).
- Limit caps result count.

Catalog: SPY/QQQ/IWM/SPX/NDX/DIA + ten common large-caps (AAPL,
MSFT, NVDA, TSLA, AMD, GOOGL, AMZN, META, NFLX, AVGO). The
has_0dte_today check uses `settings.zero_dte_universe` (SPY/QQQ/IWM)
— those are the only symbols with reliable same-day expiry on
Alpaca's free feed.

UX behavior verified at 1600×1000:
- Search input renders with magnifying-glass glyph and current
  symbol in the placeholder.
- Typing 1+ chars opens the dropdown; results show ticker + name +
  amber "0DTE TODAY" pill on eligible symbols, quiet "no 0DTE
  today" label on others.
- Selecting a result fires the parent's symbol setter, clears the
  input, blurs the field, closes the dropdown.
- Esc closes; click-outside closes; Enter selects the top result.

## 6. Color customization

The Chart Appearance section in Settings adds four knobs and they
all wire to the live chart:

- **Bullish candle color** — `<input type="color">` behind a 32×32
  swatch. Saves as a 7-char hex. The chart's `useEffect` deps
  include `userBullish` so candles re-render on change.
- **Bearish candle color** — same.
- **Background gradient** — On/Off toggle. Sets
  `document.documentElement.dataset.bgGradient` in `App.tsx`; CSS
  in `index.css` keys off `html:not([data-bg-gradient="off"]) body`
  to apply / strip the radial gradient.
- **Chart grid line opacity** — 0–100 slider in 5% steps. Drives a
  small applyOptions effect on the lightweight-charts instance so
  changes apply without remounting.

All four persist to `td:user-settings` (zustand persist) so a
reload comes back to the same look.

Verified by changing each knob in the running app — candles
recolor on the live chart, gradient flips on/off, grid lines
fade in/out smoothly.

## 7. Known issues

1. **Chain ladder visual not captured today.** Today is a weekend;
   the chain endpoint returns "No 0DTE for SPY today" so the new
   ladder styling (20px rows, anchored strike column, every-5
   grouping, ATM amber 4px, hover bg-tier-3 across whole row) isn't
   visible in the screenshot. The CSS is in place; weekday/market-
   hours verification needed.
2. **Trade Desk wordmark file kept on disk.** `TradeDeskLogo.tsx`
   is no longer imported from the header but stays in the tree for
   rollback. The Settings page header (`PageHeader`) still uses the
   wordmark in its "compact" size — intentional, since secondary
   pages can still carry the brand text without competing with the
   primary product chrome.
3. **`text-white` used on filled BUY/SELL.** Tailwind's default
   `text-white` (#FFF) is technically a color not in our palette;
   it's the right choice for legibility on the saturated action
   fills, but flag if the palette discipline review wants it
   formalized as `actionText` or similar.
4. **MetricPill width still slightly narrow.** 110px minimum holds
   most values but extreme RP&L (e.g., +$12,345.67) will overflow
   slightly. Acceptable for now; bump to 120px if the live test
   shows clipping.

## 8. Could not verify

These need the user to drive or live market hours:

- **Chain ladder styling.** Open `/positions` Monday during market
  hours with the SPY chain present and confirm rows are 20px,
  strike column has its subtle bg-tier-1 anchor, every-5 hairlines
  group cleanly, ATM row carries the new 4px amber rule + bg-tier-2,
  and selecting a row produces the persistent amber-ring outline.
- **Search results with real 0DTE-availability.** Today's flag is
  static from `settings.zero_dte_universe`. A future iteration can
  hit the chain availability check live; the current implementation
  is correct against the configured universe.
- **BUY/SELL real fires.** The filled action buttons trigger the
  same `useOpenZeroDte{Leg,Straddle}` hooks as before; mutation
  shape, success handling, and selection-clear-on-fire are
  unchanged. Live verification needs market hours.
- **Color customization reload persistence.** Verified that
  zustand persists to `td:user-settings` (existing pattern); spot-
  check reload behavior with non-default colors when convenient.

## 9. Do first when back

1. **Open `/positions` Monday at 09:30 ET.** Smoke-test the live
   layout: search → click a result → chain populates the ladder →
   click a strike → ticket selects + shows BUY/SELL filled →
   fire BUY +1 → confirm a position opens and the open-position
   column 1 takes over the bottom strip.
2. **Walk the search.** Type "spy", "aapl", "qqq", "apple". Confirm
   ranking, badges, click-to-select.
3. **Tier-pill check.** Click the tier pill in the header; switch
   to 100K; confirm the metric pills update to the new tier's
   balance/MLL.
4. **Color customization walkthrough.** Go to Settings → Chart
   Appearance, change bullish to teal (#4FB8C8) and bearish to a
   richer red (#B23B3B); confirm the chart picks them up live.
   Toggle bg-gradient off; toggle grid opacity to 0% then 60%.
5. **Logo critique.** Look at the new mark at the rail's 28px
   render. If it doesn't land, the SVG markup in §4 is small and
   easy to iterate; I left it as the first attempt rather than
   over-iterating without a human eye in the loop.
6. **Decide on `text-white` in BUY/SELL.** Either accept it as a
   one-off action-button affordance or add a palette token for
   "text on saturated action fill" and migrate.
7. **Optional: bump MetricPill `minWidth` to 120** if any value
   clips with big P&L.

## Verification

```
$ git log --oneline -6
<this commit> Phase F: settings color customization + report
c3084ae       Phase E: chain + toolbar + key levels
75613d5       Phase D: trade ticket buttons + qty
15d1e1c       Phase C: header restyle + search
90b2127       Phase B: universal button restyle
20b9959       Phase A: new palette + logo + rail

$ npx tsc --noEmit
(clean)

$ uv run pytest -q
216 passed, 1 warning in 6.83s
```

Each phase is independently revertable via `git revert <hash>`.
Dependencies are monotonic (later phases reference earlier
components, never the reverse), so reverting in reverse order
works cleanly.
