# Trade Desk redesign — completion report

Autonomous session, 2026-05-28. Six landed phases, each committed independently and revertable in isolation. tsc clean throughout. 196/196 backend tests pass.

---

## 1. Summary

The Trade Desk POSITIONS view has been re-architected around a four-quadrant layout:

```
┌────┬───────────────────────────────────────────┬──────────────────────────────┐
│    │ TRADE DESK · SPY|QQQ|IWM · $755.36 +0.64% │ BAL $10,000 · DLL — · RP&L · │
│    │                                           │   UP&L · MKT OPEN/CLOSED    │
│ L  ├───────────────────────────────────────────┼──────────────────────────────┤
│ E  │ 1m 5m 15m 1h 4h [1D] · candles ▾  ▭ ─ /  │ OPTION CHAIN  SPY  0DTE     │
│ F  │ SPY · 1D · O 755.23 H 755.28 ... change   │ spot ATM IV  · indicative   │
│ T  ├───────────────────────────────────────────┤  CALL │ STRIKE │ PUT (16 rows) │
│    │                                           │  [ATM amber-highlighted]    │
│ R  │       CANDLES + position magenta          │                              │
│ A  │       (no market-structure overlay        ├──────────────────────────────┤
│ I  │        unless KEY LEVELS toggle ON)       │ TRADE TICKET                 │
│ L  │                                           │ STRIKE 755 STRADDLE · est.  │
│    │                                           │ QTY [−|1|+] [1][3][5][10]   │
│    │                                           │ [    BUY    ][   SELL    ]   │
│    ├───────────────────────────────────────────┴──────────────────────────────┤
│    │ OPEN POSITION │ THETA SCRUBBER │ KEY LEVELS │ TODAY                       │
│    │ ▲ SPY straddle│ today's sess.  │ EM↑/EM↓/CW │ 16:00 Long straddle SPY    │
│    │ UPL +$480     │ track + BE     │ PW/MP/GF + │  ...                       │
│    │ Δ Γ Θ ν       │ drift preview  │ IV · toggle│ view full journal →        │
│    │ CLOSE button  │ RESET          │            │                            │
└────┴───────────────┴────────────────┴────────────┴────────────────────────────┘
```

What landed:
- Persistent 56px account header (BAL / DLL / RP&L / UP&L / MKT).
- SPY/QQQ/IWM ticker switcher replacing the symbol search.
- TradingView-style chart toolbar (timeframes + candle type + drawing tool stubs + indicators) + OHLC strip.
- 452px right column: ~16-strike dense option chain on top, trade ticket on the bottom.
- 280px bottom strip: OPEN POSITION · THETA SCRUBBER · KEY LEVELS · TODAY.
- Chart cleaned by default — only the user's magenta position lines render. Market-structure overlays toggle in from KEY LEVELS.
- Amber discipline tightened — reserved for "active / selected right now." Errors → bearish-red. Warnings → new warning color `#C97A3A`. Three new grayscale stops added.

What didn't get touched (per the operating rules — frozen):
- `calculations/black_scholes.py`, `calculations/intraday_analytics.py`, `calculations/position_analytics.py`
- `routers/zerodte.py` and the 0DTE entry mechanism
- `services/alpaca_client.get_market_clock`, `services/market_calendar.is_market_open`
- All backend math.

Only the UI surface changed. Every mutation/query the redesign uses (`useOpenZeroDteStraddle`, `useOpenZeroDteLeg`, `useTradeAnalytics`, `useTickerChart`, `useTickerAnnotations`, `useTickerMetrics`, `useTrades`, `useMarketStatus`) is the same hook the legacy UI called.

---

## 2. Phase-by-phase

| # | Phase | Commit | Files |
|---|---|---|---|
| 0 | Baseline | `e8c3808` (pre-existing) | clean working tree confirmed |
| 1 | Color discipline + DESIGN.md | `f3c92a2` | `palette.js`, `tailwind.config.js`, `DESIGN.md`, `CalendarStrip.tsx`, `ChainPanel.tsx`, `ChainTable.tsx`, `MockFlowBanner.tsx`, `MetricCell.tsx`, `PriceHeader.tsx`, `VerdictCard.tsx` |
| 2 | Persistent account header + ticker switcher | `3087b81` | `TradeDeskHeader.tsx` (new), `PositionsPage.tsx` |
| 3 | Chart toolbar + OHLC strip | `a9f5210` | `ChartToolbar.tsx` (new), `chartPrefs.ts` (defaults flipped), `PositionsPage.tsx` |
| 4 | Relocate chain to upper-right column | `d114b3e` | `RightChain.tsx` (new), `PositionsPage.tsx` |
| 5 | Trade ticket with qty stepper + BUY/SELL | `a29916a` | `TradeTicket.tsx` (new), `tradeTicket.ts` store (new), `RightChain.tsx` (refactor), `PositionsPage.tsx` |
| 6 | Bottom strip (position / scrubber / key levels / today) | `ec38309` | `BottomStrip.tsx` (new), `PositionsPage.tsx` |
| 7 | Final pass + this report | (this commit) | `REDESIGN_REPORT.md`, `screenshots/` |

Each phase ran `tsc --noEmit` clean and `196 passed` for the backend test suite before commit.

### Phase 1 details

Five-stop foreground ramp, new background tier 3, new warning + position-magenta tokens, new fg-disabled.

```js
// palette.js — values changed/added
fgPrimary    "#E8E8E0"   (unchanged)
fgSecondary  "#C4C4BC"   (was #8A8A82 — bumped brighter for "normal labels")
fgTertiary2  "#8A8A82"   (NEW — was old fg-secondary value; "muted labels")
fgTertiary   "#5A5A52"   (unchanged — decorative)
fgDisabled   "#3F3F3A"   (NEW — disabled controls)
bgTier3      "#161A24"   (NEW — active control fill)
warning      "#C97A3A"   (NEW — alerts/advisories)
positionMagenta "#D946EF" (existing magenta surfaced as a token)
```

Amber migrations applied:
- Market-closed advisory: `text-amber` → `text-warning`
- "No 0DTE for SPY today" message: `text-amber` → `text-warning`
- ER badge (PriceHeader): amber border + text → warning
- MockFlowBanner ("demo notice"): amber → warning
- MetricCell failingBaseline dashed rule: amber → warning
- CalendarStrip FOMC / OPEX / quad-witching / high-importance economic pills: amber → warning
- VerdictCard directional verdicts: amber → bullish/bearish

What stayed amber (correctly active/selected):
- Active ticker button, active timeframe button, ATM row + strike, focused/hover states, today-column ring in CalendarStrip and JournalCalendar, watchlist-item selected state, chart-legend ON state, KEY LEVELS toggle when ON, wordmark cursor block, scrubber position marker.

DESIGN.md gained a "Color discipline" section under "Palette" documenting each color's single meaning + a "Market-structure pills" note for the outlined/quieter treatment on the chart.

### Phase 2 details

`TradeDeskHeader` (56px, `frontend/src/components/positions/TradeDeskHeader.tsx`) replaces `TradeDeskToolbar` as the page header. Layout: TradeDeskLogo (compact), three ticker buttons (SPY / QQQ / IWM), live price + change% (color-coded), then a right-aligned cluster of BAL / DLL / RP&L / UP&L stacked label-over-value, plus MKT pill.

Wiring:
- BAL = `STARTING_BALANCE + todayRpl + activeUPL` — same math as the retired PaperAccountHeader.
- DLL — no backend day-loss-limit endpoint exists yet. Rendered as `—` in fg-tertiary-2. See "Known issues" below.
- RP&L = sum of `realized_pnl` for today's closed paper trades.
- UP&L = active position's `unrealized_pnl` from `useTradeAnalytics`.
- MKT = `useMarketStatus`. "OPEN · until HH:MM ET" green or "CLOSED · until HH:MM ET" red (uses `next_close` / `next_open`).

The toolbar `TradeDeskToolbar.tsx` and `PaperAccountHeader.tsx` were dropped from `PositionsPage` imports. Both files stay on disk so a one-line revert restores them if needed.

### Phase 3 details

`ChartToolbar` (`frontend/src/components/positions/ChartToolbar.tsx`) — two-row stack:
- 36px toolbar: 1m / 5m / 15m / 1h / 4h / 1D buttons, separator, `candles ▾` stub, separator, three drawing-tool stubs (`／`, `—`, `▭`), right-side `indicators ▾`, `legend` toggle, `levels ↓` breadcrumb.
- 20px OHLC strip: `SYMBOL · TF | O H L C | change · pct`.

The intraday timeframes (1m/5m/15m/1h/4h) are visual-only — they highlight in the toolbar but route to the backend's `1D` bars (`TF_REAL_MAP`). Tooltip explains the fallback. Spec calls these stubs out; real intraday bar fetching is a later task.

`chartPrefs` defaults flipped: `showMarketAnnotations: false` and `showLegend: false`. The chart now opens clean; only the user's magenta position lines render until KEY LEVELS toggles overlays back on.

### Phase 4 details

`RightChain` (`frontend/src/components/positions/chain/RightChain.tsx`) sits in the upper-right column at 452px wide. Chain query asks for 8 strikes each side of ATM (17 rows total, 16 visible at 18px). Three-column grid `168px (call) | 88px (strike) | 168px (put)`. ATM row gets amber left-rule, bg-tier-1 fill, amber values. Auto-scrolls ATM into view on symbol switch. Disabled cells (market closed or no 0DTE) render with `text-fg-disabled` per the new discipline.

Click semantics in Phase 4 still fire mutations directly (preserves legacy "click chain → opens position" behavior); Phase 5 changes them to populate a ticket selection instead.

### Phase 5 details

New `tradeTicket` store (`frontend/src/stores/tradeTicket.ts`) holds `{ selection: { kind, side?, symbol, strike, price, expiry } | null, contracts: number }`. RightChain refactored to call `setSelection(...)` instead of mutating directly. Selected cells highlight amber + bg-tier-3.

`TradeTicket` (`frontend/src/components/positions/TradeTicket.tsx`, ~184px tall) renders four rows:
1. `TRADE TICKET` left + `selected from chain ↑` right
2. Summary: `STRIKE 755 STRADDLE · est. $96.00 debit · BE $755.96` (BE in magenta)
3. QTY: `−` / `1` / `+` stepper with `1` / `3` / `5` / `10` preset chips
4. Two 56px buttons: BUY (bullish-outlined + tinted bullish bg) and SELL (bearish-outlined + tinted bearish bg). Two-line labels.

BUY → `useOpenZeroDteStraddle.mutate({ action: "buy" })` or `useOpenZeroDteLeg.mutate({ side, action: "buy", ... })`. SELL → same with `action: "sell"`. On success, the store's selection clears. Both buttons disable + show contextual sub-label when no selection / market closed / mutation in flight. There is no buy/sell toggle anywhere in the UI now — direction is which button you press.

### Phase 6 details

`BottomStrip` (`frontend/src/components/positions/BottomStrip.tsx`, 280px tall, four equal columns).

**Col 1 — OPEN POSITION.** Reads the active trade + analytics. Renders symbol + strategy with magenta entry triangle, sub-line with strike(s) and entry time, hairline divider, large color-coded UPL, 2×2 greeks grid (Δ Γ Θ ν with Θ color-coded by sign), magenta BE range, MAX LOSS / MAX GAIN row, and a `CLOSE · realize ±$XX.XX` button that shows the live realizable P&L. Close mutation fires the same `updateTrade(id, { status: "closed", exit_underlying_price: spot, realized_pnl: upl })` path the legacy `OpenPositionsList` used. Empty state copies "No open position. Pick a strike in the chain ↑."

**Col 2 — THETA SCRUBBER.** Hours mode for 0DTE (entry → 4pm ET), days mode otherwise. Custom amber-filled track + draggable thumb (hidden `<input type=range>` is the underlying control). 60px BE drift preview SVG: two faint magenta paths interpolating linearly from `breakevens_today` to `breakevens_expiration` over 30 sample points. Caption `BEs widen toward expiry as theta burns` + `RESET` button. Empty state when no active trade.

**Col 3 — KEY LEVELS.** Two-column list of EM↑/EM↓/CW/PW/MP/GF from `useTickerAnnotations`. Hairline divider. IV rank from `useTickerMetrics` (e.g., `28 · low`). Bottom row: "show on chart" + toggle switch wired to `chartPrefs.showMarketAnnotations`. Default OFF — flipping ON re-enables the existing in-chart annotation overlay machinery.

**Col 4 — TODAY.** Column header shows today's net P&L color-coded. Body lists today's trades (open + closed today). Open positions get a magenta left-rule. Active trade row gets bg-tier-2. Bottom: `view full journal →` link to `/journal`.

`PositionRiskStrip` was removed from `PositionsPage` — its content is fully subsumed by col 1 OPEN POSITION. The component file stays on disk for rollback.

---

## 3. Screenshots

Four PNGs saved under `screenshots/` at the project root, viewport 1600×1000.

| File | What it shows |
|---|---|
| `screenshots/01_empty_state.png` | Cold open. SPY active, no position, market closed. The persistent header + chart toolbar + OHLC strip + chain + ticket placeholder + bottom strip all render. Chain is read-only (cells dimmed via `text-fg-disabled`). BUY/SELL buttons say "market closed" on the sub-line. |
| `screenshots/02_qqq.png` | After clicking QQQ in the header. Live price + change update; KEY LEVELS column label updates to QQQ. Demonstrates the SPY/QQQ/IWM ticker switcher. |
| `screenshots/03_levels_on_chart.png` | "show on chart" toggle ON in KEY LEVELS (col 3) — the toggle switch shows amber. Demonstrates the off-by-default + opt-in re-enable of market-structure overlays. |
| `screenshots/04_with_position.png` | With an open SPY straddle activated. OPEN POSITION column (col 1) populates with UPL +$480, Δ/Γ/Θ/ν, MAX LOSS/GAIN, magenta CLOSE button. UP&L in the header shows +$480 (bullish-green). Magenta entry marker + position lines render on the chart. Bottom strip's scrubber column shows the BE drift preview. |

Screenshot 01 is also the **market-closed** state (the MKT pill reads "CLOSED · UNTIL 09:30 ET" and trade ticket buttons are disabled). Screenshot 04 covers the **with-position** state. Together they exercise the three states the spec called out (empty / with-position / market-closed).

---

## 4. Known issues

1. **DLL value renders as `—`.** No backend day-loss-limit service exists yet; the spec told me to render placeholders for any account metric without a backing source. The header cell is wired and will populate the moment a `day_loss_limit` field appears on a future `/api/account/state` endpoint. The label position + column width are already correct.
2. **Chain placeholder may briefly show prior symbol data on switch.** `useChainTable` carries `placeholderData: (prev) => prev`, so flipping from SPY → QQQ keeps the SPY strike list visible until QQQ's chain query resolves. The screenshot `02_qqq.png` caught this in a frame — the header price says QQQ $736 but the chain header label still reads `SPY 0DTE` until the new query lands. Functional but cosmetically jarring on a slow network.
3. **`tsc -b` from `npm run build` still errors on `vite.config.ts`.** Pre-existing (commit `3d001ac` baseline reproduces it) — `@types/node` is not in devDependencies so `node:path` and `__dirname` flag in the `tsconfig.node.json` project. Not introduced by the redesign. `npx tsc --noEmit` (the main project) passes clean throughout. `npx vite build` (the actual prod bundle) produces a 593kB JS that builds in 2s.
4. **Drawing tool buttons + "candles ▾" / "indicators ▾" are stubs.** Visual placeholders only; clicking does nothing yet. Real drawing-tool / chart-type / indicator wiring is out of scope per the operating rules ("stubs are fine for now, real drawing tool integration is a later phase").
5. **Intraday timeframes (1m / 5m / 15m / 1h / 4h) fall back to daily bars.** Backend serves daily granularity; clicking these highlights the visual button but the chart stays on 1D candles. Tooltip explains. Real intraday bar fetching is a separate task that touches the backend `/chart` route.

Small decisions made (spec was silent, picked the simplest consistent option):
- BUY/SELL button labels use the literal `BUY` / `SELL` on line 1 + `long {kind} · ${cost} debit` on line 2 in monospace 14px. No box shadow, no animation; consistent with the rest of the dashboard's flat 1px treatment.
- QTY stepper presets: 1 / 3 / 5 / 10 (the spec listed those values). Active chip wears amber outline + bg-tier-3 like every other "active" surface.
- BE drift preview: 30 sample points, linear interpolation between `breakevens_today` and `breakevens_expiration`. Spec said "purely illustrative ... feed a few sample timepoints, draw lines between" — 30 reads as a smooth curve at the column's render width without re-calling the analytics endpoint per sample. Two magenta paths at 0.55 stroke-opacity.
- Scrubber thumb: 12px amber circle on a 4px rounded track. Hidden range input drives keyboard accessibility.
- OPEN POSITION's contract count shows the max contracts across legs (for a straddle, two legs at 1 contract each = "1 contract" not "2"). Avoids a confusing 1+1=2 readout on a 1-contract straddle.

---

## 5. Could not verify

These need the user (live data + interaction):
- **Live trading.** Today is 2026-05-28, market closed. Every BUY/SELL path is disabled in the current screenshot. The wiring is the same as the legacy toolbar's `+ BUY STRADDLE` button (`useOpenZeroDteStraddle.mutate({ symbol, action, contracts })`) and the legacy chain-cell open (`useOpenZeroDteLeg.mutate({ symbol, side, action, strike, entry_price, contracts })`) — both hooks are unchanged. First trade Friday 9:30 ET should verify the BUY click → opens long position, SELL click → opens short, and the ticket clears on success.
- **The moving-breakeven hook driving the chart.** The `AnnotatedChart` `position` overlay code is unchanged; it reads `breakevensToday` / `breakevensExpiration` from `useTradeAnalytics` exactly as before. The screenshot `04_with_position.png` shows the magenta entry triangle rendering; what I can't verify is whether the BE lines walk as the scrubber drags. That's a frame-rate / re-render concern that needs eyes on a real session.
- **Drawing tools.** Stubs only — they're visual placeholders that need a real drawing-tool library wired in (TradingView's own drawing primitives aren't free; lightweight-charts has a `Plugin` API that needs custom geometry code). Out of scope per the operating rules.
- **Chart-type switcher ("candles ▾")** and **indicators dropdown ("indicators ▾")** — stubs.
- **The KEY LEVELS "show on chart" toggle's visual effect.** Screenshot `03_levels_on_chart.png` shows the toggle in the ON position, but the chain happened to be in a 500 error state during that capture, so the annotation lines didn't draw. The toggle wiring is correct (`chartPrefs.toggleMarketAnnotations` → existing `useEffect` in `AnnotatedChart` adds/removes price lines). Worth retesting on a clean chain query.
- **Market-open behavior on the trade ticket** — the empty-state placeholder ("Click a strike in the chain ↑") and the "market closed" sub-label transition both need a live market session to verify the disabled→enabled flip.

---

## 6. Do first when back

1. **Open the dashboard at `localhost:5173/positions` first thing Friday at 9:30 ET.** Smoke-test the layout while market is open — confirm the chain is interactive, ATM row scrolls into view, click a strike, see selection populate in the trade ticket below, see the BUY/SELL sub-labels switch to "long straddle · $XX debit" / "short straddle · $XX credit," fire a BUY of 1 straddle, watch OPEN POSITION populate in col 1 and UP&L animate in the header.
2. **Verify the close button.** After step 1's open, watch the CLOSE button in OPEN POSITION show "CLOSE · realize ±$XX.XX" with the live realizable. Click it — should book the trade and clear col 1 back to empty state.
3. **Drag the THETA SCRUBBER.** Confirm the BE drift preview's two magenta lines render, the on-chart BE lines walk outward as the thumb moves right, and RESET returns to NOW.
4. **Toggle KEY LEVELS "show on chart."** Confirm the EM±/CW/PW/MP/GF lines appear as faint right-edge labels on the chart when ON, and disappear when OFF. (Default is OFF.)
5. **Browse to `/journal`, `/analytics`, `/watchlist`, `/settings` once.** Those pages were not touched in this redesign — the existing chrome stays. Confirm they still render.
6. **Decide whether to wire DLL.** Two options: (a) add a `day_loss_limit` setting to userSettings + a guard in the open-trade router that rejects new opens when `RP&L + UP&L < -DLL`, or (b) deferred. If (a), the header cell will pick it up automatically.
7. **Revisit "small decisions made" above** if any of them feel wrong — they were judgment calls where the spec was silent.
8. If everything looks good, retire (delete) the now-unused files: `TradeDeskToolbar.tsx`, `PaperAccountHeader.tsx`, `PositionRiskStrip.tsx`, `ChainPanel.tsx`. Kept on disk for the duration of the review so individual phase reverts work without re-creating them.

---

## Verification summary

```
$ git log --oneline -7
ec38309 Phase 6: bottom management strip (position / scrubber / key levels / today)
a29916a Phase 5: trade ticket with quantity stepper + BUY/SELL buttons
d114b3e Phase 4: relocate chain to upper-right column
a9f5210 Phase 3: chart toolbar + OHLC strip
3087b81 Phase 2: persistent account header + ticker switcher
f3c92a2 Phase 1: color discipline + new grayscale/warning stops
e8c3808 Audit report: autonomous session findings + roadmap

$ cd frontend && npx tsc --noEmit
(clean)

$ cd backend && uv run python -m pytest tests/ -q
196 passed, 1 warning in 6.12s

$ cd frontend && npx vite build
✓ 474 modules transformed.
dist/index.html                   0.74 kB │ gzip:   0.40 kB
dist/assets/index-9iKb65Td.css   21.45 kB │ gzip:   4.99 kB
dist/assets/index-BDqSmcPR.js   593.30 kB │ gzip: 176.37 kB
✓ built in 2.16s
```

Each phase is independently revertable via `git revert <hash>` — the dependency direction is monotonic (Phase 6 references components from Phases 4-5, but the reverse never happens). If a phase needs to come back out, revert in reverse order.
