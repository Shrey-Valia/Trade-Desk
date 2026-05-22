# Phase 8 Audit

## Summary

The dashboard is functionally complete and visually coherent at a 2-second glance, but multiple small inconsistencies accumulate into a "personal project" feel rather than a "designed product" feel. The three highest-impact items, all small effort:

1. **Hardcoded hex values bypass the design system** in `DashboardHeader.StatusPill` and `CalendarStrip.EVENT_STYLE` (8 hex pairs not in `lib/design.ts`). Bug magnet for future palette changes and a visible inconsistency now.
2. **First-load skeletons missing on DashboardHeader, CalendarStrip, and WatchlistColumn** — the three persistent surfaces that load before anything else. Layout jumps for ~1 second on every page open.
3. **No tooltips on jargon-heavy stat cards** (VRP, 25Δ Skew, P/C Ratio, IV Rank, max pain, γ flip). High educational value, ~30 min to add, nothing blocks it.

The ML layer's honest "warning border" semantics are already clean; this audit doesn't re-litigate those decisions.

---

## Findings by Surface

### 1. DashboardHeader (`components/layout/DashboardHeader.tsx`)

**A. Visual consistency**
- `StatusPill` palette (lines 32-36) hardcodes 4 hex pairs (`#EAF3DE/#1D5A3F`, `#EFEFEC/#3A3A36`, plus warning) — `bullishLight`/`warningLight` exist in `lib/design.ts` but the dark text colors (`#1D5A3F`, `#3A3A36`, `#633806`) are invented locally.
- Padding `px-3 py-1.5` (12px/6px) — every other top-level surface uses `px-4` (16px) horizontal. Header is the odd one out.
- `IndexCell` stacks three different font sizes inline on the same baseline: symbol `text-tiny` (9px) `font-medium`, price `text-xs2` (11px), pct `text-tiny` (9px). Reads as rhythm-less.

**B. Information hierarchy**
- StatusPill text size = `text-tiny` (9px). Market state arguably the most important info in the bar but it visually fades behind the 11px index prices.
- Index pct (9px) is smaller than index price (11px) — correct subordination, but the gap is too narrow.

**C. Loading / empty**
- No skeleton — `status` and `indices` falsy → renders bare `"—"` placeholders. Causes a visible content-shift when data lands ~50ms later.

**D. Interactive**
- Nothing in the header is clickable. Status pill could plausibly link to "next open/close" times but doesn't.

**E. Microcopy**
- "Options Dashboard" — generic. Acceptable but uninspired.
- Status labels ("Open" / "Closed" / "Pre-market" / "After-hours") from backend — clear.

**F. Edge cases**
- Markets closed now: pill correctly shows "CLOSED" with gray palette; indices show last-cached values.
- API failure: silent fallback to `"—"`, no error indicator.

---

### 2. CalendarStrip (`components/layout/CalendarStrip.tsx`)

**A. Visual consistency**
- `EVENT_STYLE` (lines 11-18) hardcodes 4 dark text hex values (`#3A3A36`, `#791F1F`, `#633806`, `colors.primaryDark` for OPEX). Same anti-pattern as DashboardHeader StatusPill.
- `DayHeader.day` uses inline `fontSize: 11` (line 103) — should be `text-xs2`.
- `EventPill.fontWeight: 600` (line 119) for quad witching — but spec says weights 400 and 500 only, "no 700". 600 is between but still off-spec.

**B. Information hierarchy**
- Day number (11px) and weekday (9px) are both small; today highlight (2px primary border + secondary bg) does most of the heavy lifting.
- All event pills look equally important within a column — a `high`-importance FOMC + Powell event doesn't visually outweigh a `low`-importance Jobless Claims.

**C. Loading / empty**
- "Loading calendar…" (line 26) is a single text line, no 7-column skeleton frame. Largest layout jump in the entire app — the strip jumps from ~24px to ~80px height when data lands.
- Empty day = blank column. Acceptable behavior but no visual cue distinguishing "no events" from "still loading".

**D. Interactive**
- Day columns aren't clickable. No drill-down to event details.
- EventPills have `title={event.title}` (line 121) — duplicates the visible label, so the tooltip is useless. Should expose `date · importance` instead.

**E. Microcopy**
- "ISM Mfg" / "ISM Svc" abbreviations may be opaque to beginners.
- "FOMC + SEP + Powell" — great label, communicates a lot in 5 chars.

**F. Edge cases**
- Today is Saturday → no day in the strip has `is_today=true`; the highlight just doesn't render. Correct behavior, no bug.
- Ticker-with-events column tint: works but no per-event mark distinguishing "this is your selected ticker's event" from the rest of that day's events.
- Long event titles get `truncate`d without an ellipsis indicator that there's more.

---

### 3. WatchlistColumn (`components/watchlist/WatchlistColumn.tsx` + `WatchlistCategory.tsx` + `WatchlistItem.tsx`)

**A. Visual consistency**
- Wall clock (line 47) uses `text-tiny` (9px) but the "Watchlist" label next to it uses `text-xs2` (11px) — wall clock smaller than the section label inverts the normal "primary > secondary" sizing.
- `WatchlistItem` ticker uses `font-medium` (good) and pct uses `text-xs2 tabular-nums` (good) — internally consistent.
- `WatchlistCategory.EMPTY_MESSAGES` (lines 15-21) has 3 custom messages plus "No names yet" placeholders for `sentiment_up`/`sentiment_down`. The two sentiment categories never get to use these because they receive `note` from backend instead, but if `note` is ever absent the user sees the worst fallback.

**B. Information hierarchy**
- WatchlistItem is well-balanced: bold ticker → colored pct → gray subtitle. Best-tuned hierarchy in the app.

**C. Loading / empty**
- "Loading…" (line 61) is a text line — no skeleton matching the 5-category accordion. Layout jumps.
- Markets-closed banner present and informative.
- API failure: bearish-colored inline text. Preserves layout.

**D. Interactive**
- `WatchlistItem` is a `<button>` → keyboard-accessible.
- Hover state: `hover:bg-bg-secondary` (line 21) — subtle, visible.
- Selected state: 2px primary left border + `bg-primary-light` — distinct.
- **No `focus-visible:` styling** — keyboard tab gets the browser default focus ring, which on Chrome is a blue square that clashes with the purple primary.

**E. Microcopy**
- Empty messages now context-aware ("Quiet market — no significant moves yet") — clear win from Phase 7.5.
- Subtitle examples ("Calls 2.4× puts", "+1.82% today") — dense but readable.

**F. Edge cases**
- Market closed: closedBanner shows correctly. ✓
- Sentiment U/D categories: italic gray "Sentiment unavailable on free tier" — honest.

---

### 4. PriceHeader (`components/stock/PriceHeader.tsx`)

**A. Visual consistency**
- Inline `style={{ fontSize: 17 }}` (ticker), `fontSize: 20` (price), `fontSize: 10` (second row) — these MATCH the design spec but are magic numbers, not named tokens. Tailwind config has `tiny`/`micro`/`xs2` (9/10/11px) — missing 12/13/17/20.
- Second-row labels use `uppercase mr-1` between label and value — tighter than other label-value pairs in the app (most use a space or `gap-1`).

**B. Information hierarchy**
- Price (20px) > ticker (17px) > change (default 13px from body) > second-row stats (10px) → textbook descending hierarchy. ✓

**C. Loading / empty**
- `PriceHeaderSkeleton` exists and approximates final layout — good.
- Error state (handled in `StockDetailView` line 35) replaces the entire panel with bearish text — destroys the header structure.

**D. Interactive**
- Nothing is interactive. ER badge could link to "earnings detail" but doesn't (that's feature work, not polish).

**E. Microcopy**
- "Day", "52w", "Vol", "Avg" — extremely terse. Beginner doesn't know "Avg" means 20-day-average volume.
- "ER 6d" badge — abbreviation requires context. Tooltip on hover would help.

**F. Edge cases**
- 52w range can include bad data (the SPY $69 outlier we observed in Phase 2) — no validation/clamping. Renders nonsense without comment.
- When markets closed: shows last-cached values with no staleness indicator at this surface (the WatchlistColumn banner is the only "stale" signal).

---

### 5. AnnotatedChart (`components/stock/AnnotatedChart.tsx`)

**A. Visual consistency**
- Internal layout constants (`PILL_H = 11`, `PILL_FONT = 8`, etc.) — file-local. Fine inside the SVG but means the chart's typographic system is disconnected from the rest of the app's tokens.
- Volume bars (line 136) use `colors.bullish` for up days, `colors.textTertiary` for down days at 0.4 opacity — down days are gray (not red) which is a deliberate choice but undocumented. Below-zero days look almost identical to up days at this opacity.
- Timeframe buttons `text-tiny` (9px) `px-2 py-0.5` — borderline-tappable on touch devices but probably fine on desktop.

**B. Information hierarchy**
- Price line (1.8px primary) dominates — correct.
- Annotation horizontals (0.7px, 0.85 opacity) — clearly secondary.
- Live-price marker on right is the same visual weight as level pills — could be more prominent to anchor the eye on "now".

**C. Loading / empty**
- `ChartSkeleton` exists, preserves SVG frame. ✓
- Empty `bars` array isn't explicitly handled: `data && data.bars.length > 0 && <ChartSvg ...>` → silently renders nothing. Should fall back to a "No bars available" message.

**D. Interactive**
- Timeframe buttons clickable, but **no `focus-visible:` ring**.
- Chart body isn't interactive — no hover-OHLC tooltip, no click-to-zoom. Same compromise as the rest of the dashboard.
- Pill labels have no hover state showing the underlying number (e.g. `★ 235C wall` doesn't reveal OI count on hover).

**E. Microcopy**
- "+1σ 252", "★ 235C wall", "γ flip 190" — dense jargon, no tooltips defining terms.
- "OI unavailable on free feed" caveat — honest and well-placed.
- Timeframe labels — standard, no issue.

**F. Edge cases**
- Markets closed: chart shows last available bars without a "stale" visual indicator.
- All annotations null (no chain): chart renders bars + volume only, no annotation lines/pills. Acceptable degradation.

---

### 6. ModelSignalsRow (`components/stock/ModelSignalsRow.tsx`)

**A. Visual consistency**
- 4 cards: LSTM and CatBoost use the `ScaffoldCard` primitive (good), but `RegimeCard` (line 130-145) and `VolEdgeCard` (line 186-198) inline their own card markup with the same shape. Duplicated structure across 3 implementations.
- `SkeletonCard` uses `gap-1` (line 227) but `ScaffoldCard` uses `gap-0.5` (line 209) — skeleton has a slightly different vertical rhythm than the loaded state, causing a 2-3px shift when data lands.
- Card value font 13px (set inline) — different from OptionsMetricsRow value font 12px (set in `MetricCard`). Two adjacent rows render values at different sizes.

**B. Information hierarchy**
- Consistent across the 4 cards: tiny uppercase label → 13px value → tiny tertiary sublabel. Good.

**C. Loading / empty**
- Per-card `SkeletonCard` exists ✓
- Empty data → explicit fallback `ScaffoldCard` with "—" + sublabel explaining why.

**D. Interactive**
- Cards have `title=` for tooltips (interpretation/rationale) — present.
- Tooltips are hover-only → mobile/keyboard users can't access the rationale.

**E. Microcopy**
- "LSTM · vol 7d" — never explained that this means "7-day forward predicted realized volatility (annualized %)". User has to infer from context.
- "iterating; revisit 60d" — honest, clear.
- "Rule-based, not ML" italic — clear and well-placed.

**F. Edge cases**
- Tickers not in training universe: LSTM shows "Insufficient data". ✓
- No upcoming earnings: CatBoost shows "No earnings ≤30d". ✓
- Vol Edge falls through to Neutral with explicit rationale when inputs missing. ✓

---

### 7. OptionsMetricsRow (`components/stock/OptionsMetricsRow.tsx` + `MetricCard.tsx`)

**A. Visual consistency**
- Uses `MetricCard` primitive (good), but value is 12px (line 16 of MetricCard) while ModelSignalsRow values are 13px. **Two stacked rows of cards render values at different sizes** — most visible inconsistency in the app right now.
- Skeleton inlined in `OptionsMetricsRow` (lines 18-23) duplicates `SkeletonCard` from `ModelSignalsRow`. Should share.
- VRP color (line 42): warning amber when positive, bullish green when negative — but "high VRP = options rich = favor selling premium" is a *bullish vol-strategy* signal. Color semantics are inverted from intuition (high VRP looks like a warning rather than an opportunity).

**B. Information hierarchy**
- Consistent within the row.
- IV Rank sublabel "0/60 days collected" is informative but easy to miss in 9px tertiary.

**C. Loading / empty**
- Inline skeleton (good intent, duplicated code).
- Error state: just text, doesn't preserve grid layout.
- When all 5 values are null (no chain at all): shows 5 cards each with "—" rather than one consolidated "Insufficient options data" message.

**D. Interactive**
- `MetricCard` primitive has no `title` prop — no tooltips on jargon-heavy metrics (VRP, 25Δ Skew, P/C, max pain).
- Not clickable.

**E. Microcopy**
- "IV Rank", "VRP", "25Δ Skew", "P/C Ratio", "Max Pain" — all technical, no affordance for explanation anywhere.

**F. Edge cases**
- All values null: 5 dashes look broken; consolidating to one "Insufficient options data" card would be more honest.
- Cards never visually fail differently — same border, same color regardless of data quality.

---

### 8. MonteCarloPanel + BlackScholesPanel (`components/modeling/*.tsx`)

**A. Visual consistency**
- `ModelingPanelSkeleton` inline `fontSize={10}` for "Computing…" — magic, but OK as a one-off.
- McFanChart probability pills: fixed-width 64×12 rectangles on right edge with 8px text (line 112). Different sizing approach than AnnotatedChart's pills (`Math.max(text.length * 4 + 5, 22) × 11`) → inconsistent.
- MC `RIGHT_PAD = 70` (line 14) vs BS `RIGHT_PAD = 6` (line 15) — asymmetric layout next to each other in the grid. The MC chart looks narrower than the BS chart.
- BS unlimited-edge text fontSize 8 — matches MC pills but different from AnnotatedChart pills.
- BS Greeks card values use Greek-letter labels ("Δ / Γ", "Θ / V") rendered as text — inconsistent with the rest of the dashboard's preference for word labels. Saves space but increases jargon load.

**B. Information hierarchy**
- MC title "Monte Carlo · 5d · 10,000 paths" — informative.
- BS title "Black-Scholes · Payoff" is generic — could be more contextual ("Long Straddle · NVDA · 4d to ER").
- McStats / BsStats use MetricCard (12px value) — feels small for a panel-bottom summary that the user reads as the conclusion.

**C. Loading / empty**
- `ModelingPanelSkeleton` good — preserves layout.
- "Insufficient options data to model" message — italic gray. Looks more like an empty state than an error. Could be more prominent given how much real estate it represents.

**D. Interactive**
- BS `<StrategyPicker>` is a default browser `<select>` (no custom styling) — visually breaks from the rest of the dashboard's flat-card aesthetic. Big enough that it's actually distracting on the BS panel.
- Neither chart is interactive (no hover-cursor crosshair on MC, no click-to-set-strike on BS). Same compromise as AnnotatedChart.
- No focus rings.

**E. Microcopy**
- MC stats labels clear in context.
- BS stats: "Credit"/"Debit" is excellent (changes label based on strategy net). "Max Gain"/"Max Loss" with "—" + tooltip on unlimited cases — well-done.
- Strategy picker labels ("Long Straddle (ATM)", "Bull Call Spread") — clear.

**F. Edge cases**
- Unlimited loss/gain handled via UnlimitedEdge in-chart text + null max in card — well-done.
- No live IV → both panels show "Insufficient options data to model" — clear.

---

## Cross-cutting findings

### CC-1. Two color systems coexist
Both `lib/design.ts` (TS const) and `tailwind.config.js` (Tailwind theme) export the same color palette. Components use a mix: some `colors.bullish` inline, some `text-bullish` Tailwind class. **8 hex values in production code are not in either system** (DashboardHeader StatusPill + CalendarStrip EVENT_STYLE). Future palette changes need to be made in 3 places.

### CC-2. Magic-number font sizes
Inline `style={{ fontSize: N }}` appears at sizes 8, 10, 11, 12, 13, 17, 20 across multiple files. Tailwind config defines `tiny: 9px`, `micro: 10px`, `xs2: 11px`. Sizes 12, 13, 17, 20 are unnamed → inline styles required. Sizes 12 vs 13 (one px) drive the most visible cross-row inconsistency between `OptionsMetricsRow` (12) and `ModelSignalsRow` (13).

### CC-3. Skeleton coverage uneven
| Surface | Skeleton |
|---|---|
| DashboardHeader | ❌ — shows "—" |
| CalendarStrip | ❌ — text-only "Loading calendar…" |
| WatchlistColumn | ❌ — text-only "Loading…" |
| PriceHeader | ✓ |
| AnnotatedChart | ✓ |
| ModelSignalsRow | ✓ (per-card) |
| OptionsMetricsRow | ✓ (inlined, duplicates ModelSignalsRow's SkeletonCard) |
| MC / BS panels | ✓ (shared ModelingPanelSkeleton) |

### CC-4. Tooltips inconsistent / often useless
- ModelSignalsRow cards: tooltips present, content useful.
- OptionsMetricsRow cards: no tooltips — `MetricCard` primitive lacks `title` prop.
- CalendarStrip event pills: `title` duplicates visible label (useless).
- AnnotatedChart pills: no tooltips.
- All chart annotations / metrics use jargon (VRP, IV Rank, γ flip, 25Δ Skew) without anywhere to read what they mean.

### CC-5. Number formatting inconsistencies
- SPY price: `$737.71` (currency) vs VIX: `17.26` (plain) — side-by-side, jarring.
- LSTM predicted RV: `36.2%` (one decimal + unit) vs IV30: `73.6%` (same format, consistent here).
- VRP: `+37.4` (no unit) vs %-display elsewhere — `points` vs `percent` ambiguity.
- P/C Ratio: `0.38` (no unit, no "ratio:" prefix) vs "1.5×" elsewhere.

### CC-6. No focus rings anywhere
Interactive elements (`WatchlistItem` buttons, timeframe buttons, `StrategyPicker`, even the future tooltip triggers) inherit browser-default focus styles. Keyboard nav works but is visually unpolished. Quick fix: global `*:focus-visible { outline: 2px solid var(--primary); outline-offset: 1px; }` in `index.css`.

### CC-7. Border radius off-spec
Tailwind `rounded` = 4px (used everywhere). Design spec (README §11) says 4px for pills/tags, 8px for small cards, 12px for large cards. **Every card in the dashboard is at 4px** — should be 8px per spec. Visually subtle but contributes to "blocky" feel.

### CC-8. Card structure duplicated 3 ways
`MetricCard` primitive, `ScaffoldCard` in ModelSignalsRow, plus inline divs in `RegimeCard` and `VolEdgeCard` (and OptionsMetricsRow's skeleton). All same shape: rounded border container with `text-tiny uppercase label`, value, optional sublabel. Three implementations → three places drift can creep in.

---

## Prioritized polish list

| # | Finding | Surface | Impact | Effort | Risk | Notes |
|---|---------|---------|--------|--------|------|-------|
| 1 | Hardcoded hex bypasses design tokens (8 values across DashboardHeader + CalendarStrip) | header / calendar | HIGH | SMALL | SAFE | Lines 32-36 of DashboardHeader, 11-18 of CalendarStrip. Move to `lib/design.ts` (add `statusPalette`, `eventPalette`). |
| 2 | Loading skeletons missing on DashboardHeader / CalendarStrip / WatchlistColumn | top-3 persistent surfaces | HIGH | MEDIUM | SAFE | Biggest first-load shift in the app. Add skeleton at the start of each render path. |
| 3 | VIX vs SPY/QQQ number formatting mismatch in DashboardHeader | DashboardHeader IndexCell | HIGH | SMALL | SAFE | Line 58: special-cases VIX. Pick "always formatPrice" or "always toFixed(2)". I'd vote toFixed(2) since VIX has no $ — render SPY/QQQ as plain numbers next to symbol. |
| 4 | No tooltips on jargon-heavy stat cards (VRP, IV Rank, 25Δ Skew, P/C, max pain, γ flip) | OptionsMetricsRow + chart pills | HIGH | MEDIUM | SAFE | Add `title` prop to MetricCard; document each metric in a constant. ~30 min. |
| 5 | OptionsMetricsRow uses 12px values, ModelSignalsRow uses 13px values (adjacent rows) | metric/model rows | HIGH | SMALL | SAFE | One-pixel font diff. Unify on 13px (more legible) by changing `MetricCard` value font size. |
| 6 | No focus rings on any interactive element | global | MEDIUM | SMALL | SAFE | One global CSS rule in `index.css`. Cleans up keyboard nav appearance. |
| 7 | CalendarStrip event tooltips duplicate visible label | CalendarStrip | MEDIUM | SMALL | SAFE | Line 121. Change `title` to `${weekday} · ${importance.toUpperCase()}` etc. |
| 8 | Skeleton primitive duplicated 3 ways (Skeleton, SkeletonCard in ModelSignals, inline in OptionsMetrics) | shared UI | MEDIUM | SMALL | SAFE | Lift `SkeletonCard` to `components/ui/`; both rows use it. |
| 9 | VRP color semantics inverted from intuition | OptionsMetricsRow | MEDIUM | SMALL | MODERATE | Line 42. Currently `warning` for positive VRP. Either swap to `bullish` (premium-rich = opportunity) or remove color and let neutral. Worth a quick decision before changing. |
| 10 | Border radius 4px everywhere (spec says 8px cards / 4px pills) | all cards | MEDIUM | SMALL | MODERATE | Add `rounded-md` (6px) or `rounded-lg` (8px) on card components. Visually subtle but adds polish. |
| 11 | Magic-number font sizes (12/13/17/20px inline) | PriceHeader / cards / chart | MEDIUM | MEDIUM | MODERATE | Extend Tailwind `fontSize` config with named tokens for 12/13/17/20. Replace inline `style={{fontSize:N}}` calls. |
| 12 | Two color systems (design.ts + tailwind config) drift over time | global | MEDIUM | MEDIUM | MODERATE | Pick one source. Recommendation: keep `lib/design.ts` for SVG/inline uses, generate Tailwind theme from it at build time, OR just delete one. |
| 13 | "Vol/Avg/52w" labels in PriceHeader unexplained | PriceHeader | LOW | SMALL | SAFE | Add `title=` tooltips: "20-day average volume", "52-week range", etc. |
| 14 | When all cards in MetricsRow/ModelRow are "—", surface single "Loading…" instead of grid of dashes | both rows | LOW | SMALL | SAFE | Check if every value is null/`—` → render single consolidated message. |
| 15 | Sentiment up/down empty `EMPTY_MESSAGES` are "No names yet" not context-aware | WatchlistCategory | LOW | SMALL | SAFE | Lines 19-20. Replace with "Sentiment trend unavailable" or similar — these never render in practice (backend `note` always present) but kill the placeholder. |
| 16 | DashboardHeader px-3 vs other surfaces px-4 | DashboardHeader | LOW | SMALL | SAFE | Line 15. Bump to `px-4` to match. |
| 17 | StrategyPicker is unstyled native `<select>` | BlackScholesPanel | LOW | MEDIUM | MODERATE | Custom dropdown breaks design break. Either style the native select via CSS or replace with a headless dropdown. |
| 18 | MC fan-chart probability pills fixed-width 64px may clip long labels | MonteCarloPanel | LOW | SMALL | SAFE | Line 112. Compute width like AnnotatedChart does. |
| 19 | Volume bars opacity 0.4 makes up/down nearly indistinguishable | AnnotatedChart | LOW | SMALL | SAFE | Bump to 0.6 and use bearish red (not gray) for down days. |
| 20 | Down-card asymmetry MC/BS RIGHT_PAD (70 vs 6) makes them look different widths | MC + BS panels | LOW | MEDIUM | MODERATE | Decide common right-edge spacing or accept the difference. |
| 21 | BS Greek symbols (Δ Γ Θ V) instead of word labels in card values | BlackScholesPanel | LOW | SMALL | SAFE | Either show "Delta/Gamma" or add a tooltip explaining the symbols. |

---

## Recommended Phase 8 sub-phases

### 8a. Tokens + cross-system reconciliation (~90 min)
Items: 1, 3, 5, 9, 11, 12
- Replace 8 hardcoded hex values with design-token references
- Reconcile VIX vs SPY/QQQ formatting in indices row
- Unify MetricCard/ScaffoldCard value font size at 13px
- Decide VRP color semantics
- Add named typography tokens for 12/13/17/20 sizes
- Pick a single source for color palette
- **Risk:** Moderate — touches multiple files but no logic changes. Visual diff will be small but pervasive.

### 8b. Loading + skeleton parity (~60 min)
Items: 2, 8, 14
- DashboardHeader skeleton (3 placeholder cells matching final layout)
- CalendarStrip 7-column skeleton (preserves height)
- WatchlistColumn 5-category list skeleton
- Lift SkeletonCard to shared `components/ui/SkeletonCard`
- "All cards dashed → single Loading message" consolidation
- **Risk:** Safe — additive. No existing behavior changes.

### 8c. Affordances + a11y (~60 min)
Items: 4, 6, 7, 13, 21
- Tooltips on all jargon metrics + chart annotations + PriceHeader labels (single `TOOLTIPS` dict in a shared file)
- Global `*:focus-visible` ring in `index.css`
- CalendarStrip event tooltips show date + importance, not the label
- BS Greek symbol tooltips
- **Risk:** Safe — additive.

### 8d. Pre-known deferred items (NOT in audit scope)
Mentioned once per audit constraint:
- Dark mode
- Mobile responsiveness
- Animation system (beyond skeleton pulse)
- Cold-cache pre-warming for instant ticker clicks
- Keyboard shortcuts

These are larger items each deserving their own sub-phase or full session. Don't bundle with 8a/8b/8c.

### 8e. Visual polish leftovers (~30 min, optional)
Items: 10, 15, 16, 18, 19, 20
- Border radius 4 → 6/8px on cards
- Sentiment empty-message strings
- DashboardHeader padding nudge
- MC pill width computation
- Volume bar contrast
- MC/BS right-padding decision

Could be folded into 8a if you want a single "visual" pass, or skipped entirely — none individually impact daily use.

---

## Out of scope for Phase 8 (feature work, not polish)

- **Item 17 (StrategyPicker custom dropdown)** — borders on feature work. Native select is functional. Defer to a later "form controls" pass if/when we add more form inputs.
- **Interactive chart (hover OHLC, click-strike on BS)** — feature work, not polish.
- **ER badge → earnings detail panel** — feature.
- **Per-ticker memo / annotation** — feature.
- **Multi-ticker comparison view** — feature.
- **Alpaca position sync** — feature.
- **Tooltip system needs to be hover OR click for mobile** — tied to the mobile-responsiveness deferred item.
- **52-week range data validation/clamping** — data-quality fix, not UI polish. Belongs in `routers/ticker.py`.
