# UI Revamp Plan — Bloomberg Terminal Archetype

## Intent

Take the dashboard from "thoughtful personal terminal" (warm light theme, purple primary, friendly emoji categories) to "Bloomberg Terminal" (graphite-black surface, IBM Plex Mono, hairline borders, amber + cyan accents, zero decorative chrome). Every panel that already ships gets a visual rebuild against the new token system; no functional behavior changes; no new ML, no new data sources.

Why this archetype: the dashboard is information-dense, used by one person, single-screen, single-session. Every other archetype (modern fintech / Wall St formal / premium SaaS) optimizes for explanation. Bloomberg optimizes for information per square inch, which is what this product actually is.

## What this is NOT

- Not a feature add (no new panels, no new data sources, no new ML)
- Not a mobile revamp (single 1920×1080 workspace; mobile stays out of scope, deferred separately)
- Not a dark-mode-toggle (Bloomberg goes one direction — dark — full commit, no light fallback)
- Not a typography sampler (one typeface only: IBM Plex Mono, including headings)
- Not a behavior change (every existing interaction, sort, filter, hover, click stays identical)

---

## Step 1 — Establish `DESIGN.md`

There is no DESIGN.md today. The revamp creates one. This file becomes the contract every future change calibrates against, and the source of truth that `palette.js` re-exports.

`DESIGN.md` ships in commit 1 of the revamp, before any component touches. It contains:

1. The four token tables below (palette, type, density, chrome)
2. The component-level rules (what's hairline-separated vs. surface-elevated)
3. The two semantic-color carve-outs (when green/red is allowed vs. when amber/cyan replaces it)
4. The anti-pattern list (no shadows, no rounded corners beyond 2px, no font weights above 500, no emoji)

---

## Step 2 — Token redesign

### Palette (full replacement of `palette.js`)

```
BG TIER 0 (deepest)        #0A0C12   graphite black, slight blue tint
BG TIER 1 (panel)          #0E1118   one notch up — used for the main detail area
BG TIER 2 (elevated)       #11141C   two notches — selected ticker row, active tab, hover

FG PRIMARY                 #E8E8E0   warm off-white (Bloomberg signature)
FG SECONDARY               #8A8A82   labels, axis ticks, sub-context
FG TERTIARY                #5A5A52   disabled, separator labels, prefix glyphs

BORDER                     #1F222A   1px hairline everywhere
BORDER STRONG              #2A2E38   used only for selected/focused panel boundaries

BULLISH (price moves)      #4DD17C   never pure green; used ONLY for positive %change / candle up
BEARISH (price moves)      #E85C5C   never pure red; used ONLY for negative %change / candle down

ACCENT AMBER               #F0A030   selected state, alert/warning, focus rings, OPEX, FOMC
ACCENT CYAN                #4FB8C8   neutral level markers, expandable affordances, link state

# Status semantics (replaces statusPalette)
STATUS OPEN                bg #11141C, fg #4DD17C, single hairline border
STATUS CLOSED              bg #11141C, fg #8A8A82
STATUS PRE / AFTER         bg #11141C, fg #F0A030

# Event semantics (replaces eventPalette)
EARNINGS                   border-left 2px solid #4FB8C8
FOMC / FOMC_MINUTES        border-left 2px solid #F0A030
FED_SPEAK                  border-left 2px solid #8A8A82
ECONOMIC                   border-left 2px solid #F0A030  (high) | #8A8A82 (med/low)
OPEX                       border-left 2px dashed #F0A030
QUAD_WITCHING              border-left 2px solid  #F0A030 + uppercase tracked label
```

DELETED tokens (no longer used anywhere): `primary`, `primaryLight`, `primaryDark`, `bullishLight`, `bullishDark`, `bearishLight`, `warning`, `warningLight`, `warningDark`, `info`, `infoLight`, `hot`, `fomcText`, `bgSecondary`, `neutralBg`, `neutralDark`.

### Type ramp (full replacement)

```
Font family — primary    "IBM Plex Mono", ui-monospace, monospace
Font family — fallback   none (system-ui only as deepest unreachable fallback)

micro    9px / 12px  — uppercase labels, axis ticks, sub-context lines
tiny    11px / 14px  — body of pills, indices, row metadata
body    13px / 18px  — default body text, ticker rows, watchlist items
medium  15px / 20px  — ticker symbol in price header, section headlines if needed
large   17px / 22px  — metric card values (IV Rank 72, VRP +4.2pp)
display 19px / 24px  — only used for the current price in price header (892.41)

WEIGHTS (only these)
regular  400   — body, labels, secondary
medium   500   — values, selected state, primary text in price header

KILLED weights: 600, 700, semibold, bold, black. Bloomberg never goes heavy.

TRACKING
default 0
uppercase labels: 0.08em
tabular numbers: font-variant-numeric: tabular-nums (always on for ALL numbers)

LINE HEIGHT discipline
Display + large + medium: tight (1.2)
Body and below: 1.35
Uppercase labels: 1.0 (single line, no descent)
```

### Density

```
Panel padding              4px (vertical) / 6px (horizontal) — used for cells in metric rows
Row padding                4-6px — watchlist rows, calendar event pills, table rows
Section padding            8px — only at the outermost panel level
Inter-panel gutter         0 (hairline 1px border IS the gutter)
Outer page margin          0 (the page is the surface; no centered max-width container)

NEVER PERMITTED
12px+ padding              ❌
24px+ padding              ❌ (slop indicator)
gap-4 / space-y-4          ❌ — use gap-px (the hairline border becomes the separator)
rounded                    ❌ — use rounded-none default
rounded-md                 ❌
rounded-lg                 ❌
```

### Chrome

```
Borders                    1px solid #1F222A, hairline only
Border radius              0 default; 2px allowed on pills/badges; nothing higher
Shadows                    none. Period.
Backdrop blur              none
Gradients                  none
Transitions                opacity 100ms ease-out only (used for hover); no transform/scale animations
Cursor                     default; pointer only on actual buttons + ticker rows
Focus ring                 2px solid #F0A030, offset 1px (amber, replaces the current purple)
```

---

## Step 3 — Per-surface redesign

Each surface lists: current state (one line), target ASCII wireframe, file path, token migrations, open questions.

### 3.1 `DashboardHeader` — top bar

Current: 32-36px tall, purple wordmark, status pill with custom hex, 4 index cells with mixed font sizes (9/11/9px).

Target — 28px tall full-width hairline bar:

```
┌────────────────────────────────────────────────────────────────────────────────────────────────────┐
│ OPTIONS TERMINAL   ● OPEN  15:42:11 ET     SPX 5234.18 +0.42  NDX 18421.50 +0.71  VIX 13.84 -2.1  │
└────────────────────────────────────────────────────────────────────────────────────────────────────┘
```

- Wordmark: 11px uppercase tracked, FG SECONDARY
- Status: 9px FG BULLISH dot (●) + 11px label (OPEN/CLOSED/PRE/AFTER) — no pill, just the dot + word
- Clock: 11px tabular, FG TERTIARY (de-emphasized — the user can see their OS clock)
- Index cells: 11px symbol + 13px tabular price + 11px signed change (green/red) — all on one line, no stacking
- Separator between cells: 12px of negative space, no `|`
- Bottom 1px hairline ends the bar; no top border

File: `src/components/layout/DashboardHeader.tsx`
- Delete the inline hex `StatusPill` palette (currently 4 hardcoded pairs)
- Delete the stacked-baseline `IndexCell` — replace with single-line format
- Skeleton: replaces the `"—"` placeholder with 7 hairline blocks matching final widths

Open question (review pass 1 will surface): does the wordmark deserve to exist at all, given the user knows what app they're in? Bloomberg has no top-of-screen wordmark.

### 3.2 `CalendarStrip` — calendar bar

Current: 7-column grid with day pills (chunky), text-tiny weekday + text-xs2 day number, today highlighted with 2px purple left rule. Event pills have soft pastel backgrounds. Loading is a single text line that causes the largest layout jump in the app (the audit already flagged this in Phase 8c — skeleton was added, this is just the visual treatment).

Target — 60px tall hairline strip:

```
┌──────────┬──────────┬──────────┬──────────┬──────────┬──────────┬──────────┐
│ MON  13  │ TUE  14  │ WED  15  │ THU  16  │ FRI  17  │ SAT  18  │ SUN  19  │
│ CPI      │          │ ▎NVDA ER │ ▎FOMC    │ OPEX     │          │          │
│          │          │   AMC    │   +Powell│          │          │          │
│          │          │          │ Jobless  │          │          │          │
└──────────┴──────────┴──────────┴──────────┴──────────┴──────────┴──────────┘
```

- Column separator: 1px vertical hairline (`border-r border-border`)
- Today's column: 2px amber left rule, BG TIER 1 (one elevation up from page bg)
- Weekday + day number: 9px MON + 11px 13, separated by 4px space, FG SECONDARY
- Event pills: NO background fill, just a 2px left rule in the event-type color (cyan for ER, amber for FOMC/OPEX, gray for fed_speak/economic, dashed amber for OPEX). Pill body is 11px FG PRIMARY.
- Pill truncation: 1-char ellipsis when overflow, native `title=` shows full label (already wired in Phase 8c)

File: `src/components/layout/CalendarStrip.tsx`
- Delete `eventPalette` entirely; replace with `eventBorder` map producing `border-l-2` className + accent color
- Delete the inline `fontSize: 11` (audit-flagged)
- Skeleton already exists from Phase 8a/b — re-style its `bg-bg-secondary` blocks to use BG TIER 1

Open question (pass 2): do importance-high economic releases (CPI, NFP, FOMC) deserve a stronger visual treatment than the current 2px rule — e.g., amber underline under the pill text — or does that violate "every section has one job"?

### 3.3 `WatchlistColumn` — left rail

Current: ~240px column, 5 emoji-iconed categories (🔥 📅 ⚡ 📈 📉), category headers in `text-xs2`, items render with bold ticker + colored pct + gray subtitle. Selected item has 2px purple left rule + light purple bg.

Target — 240px hairline rail:

```
┌────────────────────────┐
│ WATCHLIST    15:42 ET  │
├────────────────────────┤
│ ▾ HOT NOW          (5) │
│   NVDA      +1.40%     │
│     Calls 2.4× puts    │
│ ▎ AAPL      -0.82%     │  ← selected (amber 2px left rule)
│     ER tomorrow AMC    │
│   TSLA      +3.12%     │
│     Unusual call flow  │
│   ...                  │
│ ▸ EARNINGS ≤5d     (3) │  ← collapsed
│ ▸ UNUSUAL OPTIONS  (8) │
│ ▸ SENTIMENT ▲      (4) │
│ ▸ SENTIMENT ▼      (2) │
└────────────────────────┘
```

- Section header: 11px uppercase, FG SECONDARY, count badge `(N)` in FG TERTIARY
- Category icons: KILLED. Replaced with chevron ▾/▸ for expansion state, and ▲/▼ for sentiment direction (single-char glyphs from IBM Plex Mono — they render in the typeface, no SVG)
- Ticker row: 13px ticker (FG PRIMARY, medium 500) on left + 11px tabular %change (green/red) on right + 9px subtitle below (FG SECONDARY), full-row hover and click target
- Selected: 2px amber left rule, BG TIER 2 (one elevation up); no border-radius
- Wall clock in header: 11px FG TERTIARY (matches the OS clock prominence — present but de-emphasized)

File: `src/components/watchlist/WatchlistColumn.tsx` + `WatchlistCategory.tsx` + `WatchlistItem.tsx`
- Delete `categoryAccents` entirely; replace with `categoryLabels` (just the label strings, no icons)
- Delete the focus-visible amber from Phase 8c global rule? NO — keep it; this revamp shifts ALL focus rings from #534AB7 to #F0A030, which the global rule will inherit automatically once palette flips

Open question (pass 3): the wall clock — does it earn its pixels in the watchlist header, given the top bar also shows time? Two clocks is noise.

### 3.4 `PriceHeader` — Row A (40px metric strip)

Current: 3-line wrap: ticker+price+change on line 1, day/52w/vol/avg on line 2, ER pill on line 1. Mixed sizes (17/20/13/9px tabular).

Target — single 40px row:

```
┌────────────────────────────────────────────────────────────────────────────────┐
│ NVDA  892.41  +12.34 +1.40%   Day 879.20-895.80   52W 412.05-925.50   Vol 32.4M / 28.1M   ER 6d │
└────────────────────────────────────────────────────────────────────────────────┘
```

- Ticker: 15px medium, FG PRIMARY
- Price: 19px medium tabular, FG PRIMARY
- Change ($ and %): 13px tabular, BULLISH or BEARISH
- Day range / 52W range / Vol: 11px tabular, FG SECONDARY; labels in 9px uppercase FG TERTIARY
- Vol format: `32.4M / 28.1M` instead of separate "Vol / Avg" cells (today's / 20-day average, slash separator is the relationship)
- ER pill: 9px uppercase tracked, amber 2px left rule, no background fill
- All separated by 16px negative space, no `·` bullets

File: `src/components/stock/PriceHeader.tsx`
- Drop the `text-md` / `text-lg` Tailwind tokens in favor of the new ramp
- Drop the `flex-wrap` — this row never wraps (if it overflows on narrow viewports, that's mobile, out of scope)
- Tooltips: keep all 4 `title=` attributes from Phase 8c

Open question (pass 1): the `+12.34 +1.40%` doubles the same information (dollar change ≈ %change × price). Bloomberg shows ONE, not both. Cut one?

### 3.5 `AnnotatedChart` — Row B (the dominant visual element)

Current: candle chart with overlaid pills/walls/gamma flip. SVG-based, level pills render at right edge with rounded backgrounds.

Target — candles + hairline overlays + 9px label glyphs (no pill backgrounds):

```
       ┌──────────────────────────────────────────────────── CW 920
       │       ╷                  ┃
       │       │     ╷    ╷╶╶╶╶╶╶ ┃ ┃ ╶╶╶╶╶╶╶╶╶╶╶╶╶╶╶╶╶╶╶╶  EM+ 910
       │   ╷╷  │  ╷╷ │ ╷╷ │       │ ┃
       │┃  │┃  │  │┃ │ │┃ │       │ ┃ ─────────────────────  GF 875  (amber dashed)
       │┃╷ │┃╷╶┃╶╶┃┃╶┃╶┃┃╷┃╷╶╶╶╶╶╶│╶┃ ─────────────────────  MP 880  (cyan dashed)
       │┃┃ │┃┃ ┃  ┃┃ ┃ ┃┃┃┃       │ ┃
       │   ╵   ╵  ╵╵ ╵ ╵╵╵╵       ╵ ╵ ╶╶╶╶╶╶╶╶╶╶╶╶╶╶╶╶╶╶╶╶  EM- 850
       │                                                     PW 850
       └─────────────────────────────────────────────────────────
        APR 18    APR 25    MAY 02    MAY 09    MAY 16
```

- Candles: 1px wicks, 2px bodies, BULLISH up / BEARISH down, NO fills or gradients
- Expected Move ±1σ: faint amber dashed horizontals (1px dash 4 gap 4)
- Call Wall: solid BEARISH horizontal 1px
- Put Wall: solid BULLISH horizontal 1px
- Max Pain: cyan dashed horizontal
- Gamma Flip: amber dashed horizontal
- Label glyphs at right edge: 9px uppercase, NO pill background, just the text in the level's color, 4px from the right edge
- Y-axis: hairline labels every $10, FG TERTIARY 9px, right-aligned, 12px gutter
- X-axis: 5-6 hairline date labels, FG TERTIARY 9px

File: `src/components/stock/AnnotatedChart.tsx`
- Pill component → LabelGlyph component (no rect, no fill, just `<text>`)
- All SVG `<title>` tooltips from Phase 8c are kept

Open question (pass 4): the chart fills the dominant visual mass. Is the level density (6 horizontals) readable, or do we hide all but the 2-3 nearest-to-spot by default with a toggle?

### 3.6 `OptionsMetricsRow` — Row C

Current: 5 `MetricCard`s in a grid, each a self-contained card with label/value/sublabel.

Target — 5 inline cells separated by 1px verticals, no card chrome:

```
┌─────────────────┬─────────────────┬─────────────────┬─────────────────┬─────────────────┐
│ IV RANK         │ VRP             │ 25Δ SKEW        │ P/C RATIO       │ MAX PAIN        │
│  72             │  +4.2pp         │  +3.8           │  0.94           │  880            │
│ rich            │ rich premium    │ downside paid   │ neutral         │ near spot       │
└─────────────────┴─────────────────┴─────────────────┴─────────────────┴─────────────────┘
```

- Label row: 9px uppercase tracked, FG SECONDARY
- Value row: 17px medium tabular, FG PRIMARY (BULLISH/BEARISH only if the metric is signed AND directional, e.g. VRP is +4.2pp shown FG PRIMARY since the sign IS the value)
- Sub-context row: 11px FG TERTIARY, lowercase, single line
- 6px vertical padding total, 12px horizontal
- No background, no border-radius, just the 1px right border between cells

File: `src/components/stock/OptionsMetricsRow.tsx` + `MetricCard.tsx`
- `MetricCard` deprecated for this row — replace with `MetricCell` (no Card chrome, plain bordered cell)
- The same `MetricCell` should also be used in `BsStats` for Black-Scholes — consolidates two patterns

Open question (pass 5): does the sub-context line ("rich", "rich premium", "neutral") earn its existence, or is it redundant given the user understands what VRP +4.2pp means? Cut it for power-users, keep it for self-education?

### 3.7 `ModelSignalsRow` — Row D

Current: 4 cards (LSTM, CatBoost, RF Regime, Vol Edge), each with a value, baseline_beaten warning border, interpretation, rationale, all tooltipped via Phase 8c.

Target — 4 inline cells, same MetricCell pattern, with failing-baseline cells getting a dashed bottom border instead of solid:

```
┌─────────────────┬─────────────────┬─────────────────┬─────────────────┐
│ LSTM VOL 7D     │ CATBOOST ER     │ REGIME          │ VOL EDGE        │
│  24.3%          │  ±5.2%          │  RISK-ON        │  LONG VOL       │
│ iv30 28% rich   │ iterating       │ vix<15, hy<350  │ lstm rich       │
└─────────────────┴─────────────────┴─────────────────┴─────────────────┘
                    └ amber dashed border-bottom (baseline_beaten: false)
```

- Same structure as Row C
- Failing-baseline cell: replace solid bottom border with 1px dashed amber (was warning-yellow background previously)
- Tooltips (Phase 8c compose() pattern) carry forward unchanged
- Rationale wraps to a single 11px FG TERTIARY line (cut at 28 chars + ellipsis if longer; tooltip shows full)

File: `src/components/stock/ModelSignalsRow.tsx`
- Delete the warning-border-bg styling; replace with single dashed amber bottom rule

Open question (pass 7): the rationale is currently a separately-rendered text block in some cards. Standardize to a single 28-char line for all 4 cells, with `title=` showing the full rationale?

### 3.8 `BlackScholesPanel` + `MonteCarlo` — Row E

Current: Black-Scholes payoff chart on top, then MetricCards for Cost/Max Gain/Max Loss/Greeks. Monte Carlo is a separate panel.

Target — side-by-side, Monte Carlo left half, Black-Scholes right half:

```
┌─────────────────────────────────────┬─────────────────────────────────────┐
│ MONTE CARLO  10000 paths · 7d       │ BLACK-SCHOLES  LONG STRADDLE · 30d  │
├─────────────────────────────────────┼─────────────────────────────────────┤
│  ▁▂▂▃▅▆█▇▆▅▃▂▁                     │           ╲         ╱               │
│  P10 845  P50 892  P90 945          │            ╲       ╱                │
│                                     │             ╲     ╱                 │
│ ┌───────┬───────┬───────┐           │              ╲___╱                  │
│ │ P25   │ P50   │ P75   │           │  BE 875  ╶╶╶╶┼╶╶╶╶  BE 909          │
│ │  863  │  892  │  921  │           │                                     │
│ └───────┴───────┴───────┘           ├─────────┬─────────┬─────────┬───────┤
│                                     │ COST    │ MAX GAIN│ MAX LOSS│ P(WIN)│
│                                     │  17.10  │   ─     │  17.10  │  42%  │
│                                     ├─────────┴─────────┼─────────┴───────┤
│                                     │ Δ/Γ  0.02 / 0.011 │ Θ/V  -0.18/0.62 │
│                                     └───────────────────┴─────────────────┘
└─────────────────────────────────────┴─────────────────────────────────────┘
```

- 1px vertical hairline separates the two halves
- Payoff curve: 1.6px solid line (FG PRIMARY), profit fill faint BULLISH at 8% opacity, loss fill faint BEARISH at 8% opacity, break-evens as dashed cyan verticals
- Histogram: same line treatment, 1px hairline outlines on each bar
- All stat cells use MetricCell pattern (Row C); two greek cells span more width because they show 2 numbers each

Files: `src/components/modeling/BlackScholesPanel.tsx` + `MonteCarloPanel.tsx`
- Use the shared MetricCell from §3.6
- Strategy picker (StrategyPicker) restyled: hairline buttons, amber selected state, NO rounded corners

Open question (pass 6): Black-Scholes Greeks today show only Δ/Γ and Θ/V paired. Each greek is its own concept — should we split into 4 separate cells?

---

## Step 4 — Migration order

```
Commit 1   DESIGN.md (the contract)
Commit 2   palette.js full replacement + tailwind.config.js extend
Commit 3   Global: index.css (font import, focus ring color, body bg)
Commit 4   Top bar (DashboardHeader)
Commit 5   Calendar strip (CalendarStrip)
Commit 6   Left rail (WatchlistColumn, WatchlistCategory, WatchlistItem)
Commit 7   Price header (Row A)
Commit 8   MetricCell consolidation (used by Rows C, D, E)
Commit 9   Annotated chart (Row B)
Commit 10  Options metrics row (Row C)
Commit 11  Model signals row (Row D) — also kills the warning-bg styling
Commit 12  Monte Carlo + Black-Scholes side-by-side (Row E)
Commit 13  Cleanup: delete dead tokens, delete deprecated MetricCard, lint
```

Each commit ships independently. The dashboard never enters a half-revamped state because the palette flip in commit 2 cascades through every component that imports from `lib/design.ts` — the result will be visually rough until commit 12 but functionally identical throughout.

Estimated effort: 4-6 hours of focused work, no new dependencies, IBM Plex Mono via Google Fonts CDN link tag (one line in `index.html`).

---

---

## Review pass additions

The following decisions were resolved inline during 7-pass design review. The remaining open questions (requiring user taste calls) are listed below.

### Pass 2 — States table (added)

Every panel gets these 4 states explicitly specified:

| Panel | Loading | Empty | Error | Hover |
|---|---|---|---|---|
| Top bar — indices | hairline blocks BG TIER 2, no animation, matching final widths | n/a (indices always exist) | "—" in FG TERTIARY (silent fallback, no red shouting) | n/a (non-interactive) |
| Top bar — clock | hairline block 60px wide | n/a | freeze last value | n/a |
| Calendar strip | 7-column hairline grid, BG TIER 2 blocks for day-headers + 2 ghost pill slots per column (Phase 8b shape, dark-recolored) | empty day = blank column, no placeholder text | row of "—" across the 7 columns + 9px FG TERTIARY label "calendar unavailable" at far left | n/a |
| Watchlist categories | ghost header rows (5 rows, hairline blocks, no chevron) | "Quiet market — no significant moves yet" already exists, FG SECONDARY 11px | bearish-color inline text (existing) | row background → BG TIER 2 on hover, 100ms opacity transition |
| Watchlist items | n/a (categories handle it) | n/a | n/a | row background → BG TIER 2, full-row click target |
| Price header | hairline blocks for ticker + price + change + range cells | n/a (always a ticker selected, or empty state lives one level up) | "DATA UNAVAILABLE" in FG TERTIARY, no red shouting (Bloomberg semantic) | n/a |
| Annotated chart | full chart rect filled BG TIER 1 with 1px dashed FG TERTIARY outline + 9px "loading" label centered | "Chart unavailable — no historical bars" 11px FG SECONDARY centered | same as empty | n/a |
| Options metrics row | 5 cells with hairline blocks at value position | "—" per cell with 9px FG TERTIARY sub-context "unavailable" | "—" same treatment, no red | n/a |
| Model signals row | same as Options metrics row | "Model not run yet" 11px FG SECONDARY per cell | same as empty | n/a |
| Monte Carlo + BS | full-panel hairline outline + centered 11px FG SECONDARY "Insufficient options data to model" | same as Phase 5 spec | bearish inline error message preserved | n/a |

**Skeleton animation:** static blocks, no shimmer. Bloomberg never animates loading. Decision: auto-decided per archetype.

### Pass 3 — Morning-open narrative (added)

The dashboard's primary use moment is morning market open. In that 30 seconds, the user wants — in order: (1) is market open / are there big events today (calendar + status pill), (2) what's moving in my watchlist (left rail), (3) what's the state of the ticker I care about most (main detail). The plan's composition (top bar → calendar → left rail → main detail) maps to this exact reading order. No tutorialization, no welcome screen, no onboarding overlay — Bloomberg assumes expertise.

Watchlist wall clock: dropped (duplicate of top-bar clock, decided per pass-3 redundancy).

### Pass 5 — Tailwind config wiring (added)

`tailwind.config.js` already imports from `palette.js` per Phase 8a. The full palette replacement in commit 2 propagates automatically — tailwind config touch needed only for: (a) updating `fontFamily.mono` to register IBM Plex Mono as the only family; (b) removing now-unused color keys from the `extend.colors` block; (c) updating `fontSize` token map to the new ramp (micro/tiny/body/medium/large/display). No build pipeline changes.

### Pass 6 — Accessibility additions

**Computed contrast ratios** (target: WCAG AA = 4.5:1 for normal text, 3:1 for large/UI):

| FG on BG TIER 0 (#0A0C12) | Ratio | Verdict |
|---|---|---|
| FG PRIMARY #E8E8E0 | 14.5:1 | AAA ✓ |
| FG SECONDARY #8A8A82 | 5.8:1 | AA ✓ |
| FG TERTIARY #5A5A52 | 2.9:1 | **FAIL AA for body text — restrict to decorative use (axis ticks, separator labels) only; never use for primary content** |
| BULLISH #4DD17C | 8.9:1 | AAA ✓ |
| BEARISH #E85C5C | 5.5:1 | AA ✓ |
| AMBER #F0A030 | 9.3:1 | AAA ✓ |
| CYAN #4FB8C8 | 8.1:1 | AAA ✓ |

Plan amendment: FG TERTIARY is officially "decorative tier" — never used for content the user must read; only for axis ticks, separator chrome, and similar.

**ARIA additions** (no behavior change, just labels):
- Top bar status pill: `aria-live="polite"` so screen readers announce market-open/closed transitions
- Index cells: `aria-label="SPX 5234.18, up 0.42 percent"` synthesizing the visual
- Watchlist categories: existing `<button aria-expanded>` preserved
- Watchlist items: existing `<button>` preserved; add `aria-label` synthesizing ticker + change + subtitle
- Chart: `<title>` already added in Phase 8c, kept

**Reduced-motion:** all 100ms opacity transitions wrapped in `@media (prefers-reduced-motion: no-preference)` so opt-out users get instant state changes.

### Pass 1 — Doubled change values (auto-decided)

`+12.34 +1.40%` shows both signed dollar AND signed percent. Bloomberg actually does this — both communicate slightly different information (dollar value matters for position sizing; percent matters for cross-ticker comparison). Decision: keep both, per Bloomberg precedent.

---

## Resolved decisions (from Pass 7)

1. **Wordmark in top bar — STRIPPED.** Top bar starts directly with the status dot. Pure Bloomberg posture, ~140px reclaimed for indices. Amend §3.1 wireframe: the line begins `● OPEN  15:42:11 ET     SPX 5234.18 +0.42  ...`
2. **Metric sub-context lines — KEPT.** All 5 cells in Row C and all 4 cells in Row D retain the 9px FG TERTIARY single-word context. Tooltips compose on top of that for the full definition. Self-education stays.
3. **Density philosophy — MAXIMALIST.** Cascades into three §3 amendments:
   - §3.5 Annotated chart: all 6 horizontals always visible (CW, PW, EM±, MP, GF), no auto-hide. Chart density is the point.
   - §3.8 Black-Scholes Greeks: SPLIT to 4 separate MetricCells — Δ, Γ, Θ, V each with own label + value + 9px sub-context ("position delta", "delta rate of change", "daily decay", "vol sensitivity"). Replaces current paired Δ/Γ + Θ/V. Affects `BlackScholesPanel.tsx` BsStats grid layout: `grid-cols-2 sm:grid-cols-3 md:grid-cols-6` becomes `md:grid-cols-8` (4 stats + 4 greeks). Tooltips compose two-line per cell instead of four-line per paired cell.
   - §3.7 Model signal rationale: each card writes the length its message needs (current behavior, no standardization). Tooltips remain the place for the full definition.

---

## Pass-by-pass scorecard

| Pass | Before | After | Notes |
|---|---|---|---|
| 1 — Information Architecture | 7/10 | 9/10 | Doubled-change resolved; wordmark + composition still pending |
| 2 — Interaction State Coverage | 4/10 | 9/10 | States table covers all 9 panels; skeleton animation decided (static) |
| 3 — User Journey & Emotional Arc | 6/10 | 8/10 | Morning-open narrative added; watchlist clock dropped |
| 4 — AI Slop Risk | 8/10 | 9/10 | Anti-slop guards explicit; chart density pending |
| 5 — Design System Alignment | 9/10 | 10/10 | Tailwind wiring documented; sub-context pending |
| 6 — Responsive & Accessibility | 6/10 | 9/10 | Contrast verified; FG TERTIARY restricted to decorative; ARIA + reduced-motion specified |
| 7 — Unresolved Decisions | — | 3 open | Listed above |

**Overall design completeness: 7.5/10 (pre-fix) → 9.0/10 (post-fix).** Plan is ready to implement once the three open Qs land.

---

## Approved Mockups

None — text-only path chosen. Mockups deferred until OpenAI API key is set up. If you change your mind, the brief in this conversation is reusable verbatim.
