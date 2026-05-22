# Design System

## Intent

This is the contract every visual change in this dashboard calibrates against. The product is a single-user, single-screen, single-session options trading workspace. The aesthetic is the Bloomberg Terminal archetype: graphite-black surface, IBM Plex Mono everywhere, hairline 1px borders, amber + cyan accents, zero decorative chrome. The currency is information per square inch.

The dashboard does not have a marketing surface. It does not have an onboarding flow. It does not explain itself. Every pixel earns informational value or it gets cut.

`palette.js` is the runtime source of truth for color. `tailwind.config.js` imports from `palette.js`. This file (`DESIGN.md`) is the source of truth for everything else — type ramp, density, chrome, anti-patterns, contrast requirements. If `palette.js` and this file disagree, this file wins and `palette.js` should be updated to match.

---

## Palette

### Canonical tokens (use these in new code)

```
BG TIER 0 (deepest)        #0A0C12   graphite black, slight blue tint; body background
BG TIER 1 (panel)          #0E1118   one tier up; main detail panel
BG TIER 2 (elevated)       #11141C   two tiers up; selected ticker row, active tab, hover

FG PRIMARY                 #E8E8E0   warm off-white; default text, values
FG SECONDARY               #8A8A82   labels, axis ticks, sub-context
FG TERTIARY                #5A5A52   decorative tier only; axis ticks and separator chrome (see contrast table)

BORDER (hairline)          #1F222A   1px borders everywhere
BORDER STRONG              #2A2E38   selected/focused panel boundaries

BULLISH (price moves)      #4DD17C   never pure green; ONLY for positive %change / candle up
BEARISH (price moves)      #E85C5C   never pure red; ONLY for negative %change / candle down

ACCENT AMBER               #F0A030   selected state, alert/warning, focus rings, OPEX, FOMC
ACCENT CYAN                #4FB8C8   neutral level markers, expandable affordances, link state
```

### Legacy tokens (mapped during migration)

These names still exist in `palette.js` so unmigrated components keep building. They map to functional equivalents in the dark palette. Do not introduce these in new code — use the canonical names above. Commits 4-13 progressively migrate components away.

```
primary           → ACCENT AMBER   (was purple)
primaryLight      → tinted-amber background variant
primaryDark       → ACCENT AMBER
bullishLight      → tinted-green dark background variant
bullishDark       → BULLISH
bearishLight      → tinted-red dark background variant
warning           → ACCENT AMBER
warningLight      → tinted-amber dark background variant
warningDark       → ACCENT AMBER
info              → ACCENT CYAN
infoLight         → tinted-cyan dark background variant
hot               → ACCENT AMBER
fomcText          → BEARISH
bg                → BG TIER 0
bgSecondary       → BG TIER 1
neutralBg         → BG TIER 2
neutralDark       → FG PRIMARY
textPrimary       → FG PRIMARY
textSecondary     → FG SECONDARY
textTertiary      → FG TERTIARY
border            → BORDER
```

### Semantic carve-outs

- **BULLISH / BEARISH are reserved for price semantics only.** Use them for: %change on price headers, candle bodies on the chart, watchlist row %change, P&L coloring in modeling panels. Do NOT use them for: warning states, error messages, success confirmations, status indicators. Those use AMBER (warning/active) or FG SECONDARY (neutral).
- **AMBER is the selected/active/warning accent.** Use for: selected ticker row, today's calendar column, focus rings, OPEX events, FOMC events, baseline-failure indicators on model signals.
- **CYAN is the neutral/expandable accent.** Use for: max pain level marker, chart break-evens, earnings event pills, links.

---

## Type

```
Font family                "IBM Plex Mono", ui-monospace, SFMono-Regular, monospace
                           Loaded via Google Fonts in index.html
                           No proportional fallback below ui-monospace

Size ramp
  micro      9px / 12px    Uppercase labels, axis ticks, sub-context lines
  tiny      11px / 14px    Pill bodies, indices, row metadata
  body      13px / 18px    Default body text, ticker rows, watchlist items
  medium    15px / 20px    Ticker symbol in price header
  large     17px / 22px    Metric card values (IV Rank 72, VRP +4.2pp)
  display   19px / 24px    Current price in price header

Weights
  regular   400            Body, labels, secondary
  medium    500            Values, selected state, primary text in price header

KILLED weights: 600, 700, semibold, bold, black. Bloomberg never goes heavy.

Tracking
  default                  0
  uppercase labels         0.08em
  tabular numbers          font-variant-numeric: tabular-nums (always on for ALL numbers)

Line height
  display + large + medium tight 1.2
  body and below           1.35
  uppercase labels         1.0 (single line, no descent)
```

---

## Density

```
Panel padding             4px vertical / 6px horizontal   metric cells
Row padding               4-6px                            watchlist rows, calendar events
Section padding           8px                              outermost panel level
Inter-panel gutter        0 (1px hairline border IS the gutter)
Outer page margin         0 (no centered max-width container)

NEVER permitted in new code
  12px+ padding           ❌
  24px+ padding           ❌ (slop indicator)
  gap-4 / space-y-4       ❌ — hairline border is the separator
  rounded                 ❌ — use rounded-none default
  rounded-md              ❌
  rounded-lg              ❌
```

---

## Chrome

```
Borders               1px solid #1F222A, hairline only
Border radius         0 default; 2px allowed on pills/badges; nothing higher
Shadows               none. Period.
Backdrop blur         none
Gradients             none
Transitions           opacity 100ms ease-out only (used for hover); no transform/scale animations
Cursor                default; pointer only on actual buttons + ticker rows
Focus ring            2px solid #F0A030, offset 1px (amber, replaces the legacy purple)
```

---

## Accessibility

### Verified contrast ratios (all FG colors on BG TIER 0 #0A0C12)

| Token | Hex | Ratio | Verdict |
|---|---|---|---|
| FG PRIMARY | `#E8E8E0` | 14.5:1 | AAA ✓ |
| FG SECONDARY | `#8A8A82` | 5.8:1 | AA ✓ |
| FG TERTIARY | `#5A5A52` | 2.9:1 | **FAIL AA for body text — decorative use only** |
| BULLISH | `#4DD17C` | 8.9:1 | AAA ✓ |
| BEARISH | `#E85C5C` | 5.5:1 | AA ✓ |
| AMBER | `#F0A030` | 9.3:1 | AAA ✓ |
| CYAN | `#4FB8C8` | 8.1:1 | AAA ✓ |

**FG TERTIARY restriction:** Never used for content the user must read. Allowed for: axis tick labels, separator chrome, prefix glyphs, disabled state, decorative count badges. Forbidden for: any text the user has to comprehend to understand the dashboard's state.

### ARIA + motion

- Market status pill: `aria-live="polite"` — screen readers announce open/closed transitions.
- Index cells: `aria-label` synthesizes the visual ("SPX 5234.18, up 0.42 percent").
- Watchlist categories: `<button aria-expanded>` (already present, preserved).
- Watchlist items: `<button>` with `aria-label` synthesizing ticker + change + subtitle.
- Chart: SVG `<title>` already added in Phase 8c, preserved.
- All 100ms opacity transitions wrapped in `@media (prefers-reduced-motion: no-preference)` — opt-out users get instant state changes.

---

## Anti-patterns (hard reject)

If you see these in a PR, the answer is no:

- Centered hero or splash screen
- 3-column feature grid (icon + bold title + 2-line description, repeated)
- Icons in colored circles as section decoration
- Purple, violet, or indigo anywhere
- Decorative blobs, gradients, wavy SVG dividers
- Box shadows (any size, any color)
- Border radius above 2px
- Font weights above 500
- Emoji as design elements
- system-ui or `-apple-system` as primary font (IBM Plex Mono only)
- Whitespace generosity (16px+ padding outside the outermost panel)
- Pastel backgrounds (light bullish/bearish/warning bg fills)
- Headers in serif or proportional sans

---

## Migration commits

The dark-theme revamp ships across 13 commits. Components stay on legacy tokens until their commit lands; the legacy map above keeps them building in between.

```
1   DESIGN.md (this file)
2   palette.js full replacement + tailwind.config.js extend
3   Global: index.css (font import linkage, focus ring color, body bg)
4   Top bar (DashboardHeader)
5   Calendar strip (CalendarStrip)
6   Left rail (WatchlistColumn, WatchlistCategory, WatchlistItem)
7   Price header (Row A)
8   MetricCell consolidation (used by Rows C, D, E)
9   Annotated chart (Row B)
10  Options metrics row (Row C)
11  Model signals row (Row D) — kills warning-bg styling
12  Monte Carlo + Black-Scholes side-by-side (Row E)
13  Cleanup: delete legacy tokens, delete deprecated MetricCard, lint
```

After commit 13, every legacy token in `palette.js` and every `MetricCard` import should be deleted. The legacy map in this file becomes historical reference and can be moved to a CHANGELOG entry.
