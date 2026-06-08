# Trade Desk — Design System

A 0DTE options trading terminal and prop firm. Traders prove their edge through a paid evaluation **combine** (50K / 100K / 150K tiers), then get **funded** to trade the firm's capital. Modeled on Topstep — but for options.

The product's differentiator is **visual execution**: option positions are drawn directly on the chart, with **breakeven lines that walk in real time as theta decays**. Traders *see* the trade instead of calculating it. The aesthetic is the Bloomberg-terminal archetype — dark-navy ground, IBM Plex Mono everywhere, 1px hairlines, amber + cyan accents, zero decorative chrome. The currency is information per square inch.

---

## Sources

This system was reverse-engineered from the product codebase. If you have access, explore these to build with higher fidelity:

- **GitHub — `Shrey-Valia/Trade-Desk`** (`https://github.com/Shrey-Valia/Trade-Desk`)
  - `DESIGN.md` — the design contract (palette discipline, type ramp, density, anti-patterns, contrast).
  - `frontend/src/lib/palette.js` — runtime source of truth for color (the dark-navy revamp).
  - `frontend/src/components/positions/*` — the terminal surface (header, chain, trade ticket, theta scrubber, payoff panel, position cards).
  - `frontend/src/components/branding/*` — `TradeDeskMark` (TD monogram) and `TradeDeskLogo` (wordmark with blinking cursor).
  - `screenshots/` — rendered terminal states (with-position, BE lines, tier dropdown).

> Note: the product README in that repo describes an earlier personal-dashboard framing. The **prop-firm** product framing (combine / funded / payout / MLL) and the **dark-navy** palette in `palette.js` are the current source of truth and what this design system encodes.

---

## CONTENT FUNDAMENTALS

**Voice: direct, technical, trader-to-trader. No marketing fluff.** The product is for serious traders; the tone is for serious traders. Copy reads like a desk colleague, not a brochure.

### Casing & grammar
- **Labels are UPPERCASE** at 9–11px with `0.08em` tracking: `BAL`, `MLL`, `DLL`, `RP&L`, `UP&L`, `MKT`, `OPTION CHAIN`, `OPEN POSITION`, `KEY LEVELS`, `THETA SCRUBBER`, `TODAY`.
- **Values and prose are sentence-case or mixed**: `Click a strike in the chain ↑`, `market closed`, `selected from chain ↑`, `BEs widen toward expiry as theta burns`.
- Lowercase is used deliberately for soft/secondary states (`market closed`, `until 09:30 et`, `live`, `reset`) — it reads quieter than the uppercase labels.
- Abbreviate relentlessly: `exp`, `spot`, `ATM`, `IV`, `DTE`, `T+1d`, `est.`, `BE`, `+$132.93 debit`, `2.4× puts`.

### Vocabulary — use the words real prop traders use
`combine` · `evaluation` · `funded` · `payout` · `drawdown` · `MLL` (max-loss limit) · `DLL` (daily loss limit) · `trail` / `trailing` · `consistency` · `breach` · `0DTE` · `straddle` · `theta` · `breakeven (BE)` · `realize` · `paper`.

### Never use
`platform` · `solution` · `revolutionizing` · `democratizing` · `AI-powered` · `seamless` · `unlock` · `empower`. No exclamation marks. No emoji as design elements.

### Number formatting
- Money: `$50,132.93`, signed with a true minus glyph `−` not hyphen: `−$250.00`, `+$132.93`.
- Percent: `+0.31%`, `(0.42 percent)` only inside aria-labels.
- Time: 24-hour ET — `until 09:30 et`, `entry 09:30`, `16:00`.
- Tabular figures **always on** for any number, so columns align.

### Microcopy examples (verbatim from product)
- `50K COMBINE ▾` (tier switcher)
- `BE +$132.93` (breakeven pill on chart, magenta)
- `ENTRY · Long call` (entry marker)
- `CLOSE · REALIZE +$132.93` (close button)
- `BEs widen toward expiry as theta burns` (scrubber hint)
- `No 0DTE for SPY` / `Same-day expiry not listed — try a different 0DTE-eligible symbol.` (warning, amber)
- `indicative pricing` (data-quality tag, tertiary)
- Coachmark: `Drag right to fast-forward time — watch the breakeven move on the chart as theta decays.`

---

## VISUAL FOUNDATIONS

### Color & discipline
The palette is small; the discipline of **how** each color is used is strict.
- **Ground is dark navy, never pure black.** Four elevation tiers: `#131722` body → `#1A1F2D` panel → `#222837` raised/hover → `#2A3142` active fill.
- **Amber `#F0A030` = ACTIVE / SELECTED, RIGHT NOW.** The one selected ticker, the active timeframe, the ATM chain row, focus rings, the brand mark, the wordmark cursor, today's calendar column, key CTAs. **Nothing else gets amber.** Errors are not amber. Category labels are not amber.
- **Warning `#C97A3A` = advisories**, distinct from errors and from active: "market closed", "no 0DTE today", ER badge, FOMC/OPEX pills, failing-baseline rules.
- **Bullish `#4DD17C` / Bearish `#E85C5C` = price semantics ONLY**: %change, candle bodies, P&L, errors (bearish). Never for success/warning/status.
- **Cyan `#4FB8C8` = neutral/quiet**: max-pain markers, others' breakevens, earnings pills, links, expandable affordances.
- **Magenta `#D946EF` = the trader's OWN open position**: entry triangle, BE lines, BE labels, BE drift preview. Used nowhere else.
- **BUY/SELL fills `#2A8C4A` / `#C8434A`** are a separate "action affordance" axis — deliberately NOT bullish/bearish, so order buttons don't read as P&L. Professional fills, not candy.

### Typography
- **IBM Plex Mono everywhere** — numbers, labels, headings. No proportional fallback below `ui-monospace`.
- **Two weights only: 400 and 500.** Weights ≥600 are forbidden — Bloomberg never goes heavy.
- Size ramp: micro 9 / tiny 11 / body 13 / medium 15 / large 17 / display 19px. Line-height 1.2 at display–medium, ~1.35 below; uppercase labels are single-line.
- Uppercase labels get `0.08em` tracking. `tabular-nums` is always on for numeric data.

### Backgrounds, surfaces & cards
- **No imagery, no gradients, no patterns, no textures.** Surfaces are flat fills differentiated only by the 4-tier elevation ramp.
- A "card" (metric pill) = `bg-tier-2` fill + `1px tier-3` border + 4px radius, ~110×44, label (10px uppercase) over value (15px). That is the entire card vocabulary.
- **Panels are square (0 radius).** The 1px hairline border IS the gutter between panels — there is no inter-panel gap and no centered max-width container. The page is edge-to-edge.

### Borders, radii, shadows
- **Borders: 1px hairlines only** (`#2F3545`; `#3A4258` when strong/focused). Never thick frames.
- **Radii: 0 default** (panels, tables, chart). 2px on pills/badges. 4px on buttons / metric pills / inputs. **Never larger than 4px.**
- **Shadows: none. Backdrop blur: none. Gradients: none.** Period.

### Motion
- **Opacity / color transitions only, ~100ms ease-out.** Used for hover and state changes.
- **No transform/scale animations.** The one signature motion is the wordmark cursor's ~1.2s blink. The theta-scrubber's BE-line walk is data-driven, not a CSS animation.
- All transitions wrapped in `prefers-reduced-motion: no-preference`; opt-out users get instant state changes.

### Hover / press / active states
- **Hover**: step the surface up one tier (`tier-1 → tier-2`, `tier-2 → tier-3`) and/or lift text `secondary → primary`. No shadow, no movement.
- **Active / selected**: amber border + the lifted (`tier-3`) background. Selected preset chips: amber border + amber text on `tier-3`.
- **Press (BUY/SELL)**: darker action fill (`-active` token). No shrink/scale.
- **Disabled**: drop to `tier-1` fill, `fg-disabled` text, `cursor: not-allowed`.

### Transparency & blur
- Used only for faint tinted fills behind badges/rows (e.g. amber tint behind the active row, ~12–14% alpha) and the soft fills under payoff curves (`bullish`/`bearish` at ~15% alpha). No backdrop blur anywhere.

### Layout rules
- Fixed left icon rail (48px) · fixed top header (64px) · chart toolbar (36px). Everything else is a hairline-bordered panel grid.
- Density is the product: 4px vertical / 6px horizontal cell padding; 4–6px rows; 8px outermost panel padding. 12px+ padding outside the outer panel is a slop indicator and is rejected.

### Anti-patterns (hard reject)
Centered hero / splash · 3-column icon-feature grids · icons in colored circles · purple/violet/indigo (magenta is reserved for positions, not decoration) · decorative blobs or wavy dividers · any box-shadow · radius >4px · font-weight >500 · emoji as design elements · `system-ui`/`-apple-system` as primary font · pastel backgrounds · serif or proportional headers.

---

## ICONOGRAPHY

- **Custom monoline SVG set**, not an icon library. Each icon is **20×20, stroke 1.5px, round caps/joins, `currentColor`** so it inherits the rail's active-amber / inactive-secondary color. They live in `assets/icons/` (`chart`, `journal`, `analytics`, `watchlist`, `zerodte`, `settings`) and are also exported as the React `Icon` component.
- The product ships with **Lucide React** as a general-purpose fallback set (per `package.json`) — when you need an icon outside the six rail glyphs, use **Lucide** (matching 1.5–2px stroke, no fill) and keep it monoline. Flagged substitution: any non-rail glyph in mocks should be Lucide, kept stroke-only.
- **Unicode glyphs are used as functional icons** in dense UI: `▾` (dropdown), `↑ ↔ →` (directional hints / BE range), `▲` (entry triangle / long marker), `−` `+` (steppers), `·` (separator), `★` (wall marker), `∞` / `−∞` (unlimited gain/loss). Prefer these over importing an icon for a single glyph.
- **No emoji.** No multicolor or filled icon styles. Brand marks (`assets/td-mark.svg`, `assets/td-wordmark.svg`) are the only "logo" assets.

---

## INDEX / MANIFEST

**Root**
- `styles.css` — global entry point (consumers link this). `@import` manifest only.
- `readme.md` — this guide.
- `SKILL.md` — Agent-Skill front-matter wrapper.

**`tokens/`** — `fonts.css` · `colors.css` · `typography.css` · `spacing.css` · `base.css`

**`assets/`** — `td-mark.svg` · `td-wordmark.svg` · `icons/*.svg`

**`guidelines/`** — foundation specimen cards (Design System tab): colors, type, spacing, brand.

**`components/`** — reusable React primitives (see each directory's `.prompt.md`):
- `core/` — `Button`, `MetricPill`, `Badge`, `TierPill`
- `forms/` — `Stepper`, `PresetChips`, `ActionButton` (BUY/SELL)
- `data/` — `ChainRow`, `Icon`

**`ui_kits/terminal/`** — high-fidelity recreation of the trading terminal: `index.html` (interactive click-through) + screen JSX.

**`ui_kits/combine/`** — the Combine Evaluation Dashboard: a risk-first evaluation tracker (MLL/drawdown hero, profit-target progress, pass-requirement checklist, daily breakdown). `index.html` toggles ACTIVE / PASSED / FAILED states and 50K / 100K / 150K tiers.

**`ui_kits/funded/`** — the Funded Account view (post-pass home): risk-first MLL hero carried over, payout-eligibility checklist (cumulative green days, $150 floor, 40% consistency, weekly window), transparent 50/50 split breakdown, and withdrawal history. `index.html` toggles LOCKED / ELIGIBLE and tiers. Reuses `ui_kits/combine/combine.css` for chrome continuity.

**`ui_kits/payout/`** — the Payout Request flow: eligibility confirmation, the eligible-payout amount, partial-amount request (field + slider + Max), mock payout method, "what happens next" state machine, and a post-request confirmation state. `index.html` toggles the request form / submitted states.

**`ui_kits/journal/`** — the Trade Journal: a dense, filterable/sortable closed-trade ledger (date-range + outcome/strategy/symbol filters) with expandable per-trade detail — legs, entry greeks, trader notes, self-applied tags (planned / FOMO / revenge / broke rules), and an intratrade P&L sparkline. A ledger *and* a learning tool.

**`ui_kits/analytics/`** — the Analytics screen: metric hero (net P&L, win rate, profit factor, avg win/loss, expectancy), a prominent equity curve with the largest-drawdown window shaded, performance breakdowns (by strategy / symbol / time-of-day / day-of-week / streaks / hold), and a risk & discipline panel that ties loss-sizing back to the MLL trail.

**`ui_kits/data/trades.js`** — the shared deterministic closed-trade ledger (14 trades) + aggregation helpers that **both** the journal and analytics derive from, so the two screens never disagree.

See **`check_design_system`** output for the live component/namespace list.
