# FABLE AUTONOMOUS SESSION — 2026-06-12

Branch: `fable-autonomous-session` (off main @ 0f4dfc0). All work here; small granular commits.

## How I explored

Ran backend (uvicorn :8000) + frontend (vite :5173) locally, drove the app in a headless
browser as a user: cold-open terminal, `/` symbol search, chain strike click → trade ticket →
BUY → position overlay + bottom strip → CLOSE → journal/analytics/watchlist/settings pages.
Opened and closed one real test trade (id 7) end-to-end, then deleted it; account state is
derived from the trades table, so balance/RP&L fully reverted (verified: bal 50,269.34 before
and after). Two deep code-mapping passes (frontend UX, backend API) supplemented hands-on use.

## Initial findings (user's perspective)

**What works well:** the core loop is genuinely good. Chain → ticket → BUY → live overlay +
bottom strip (position, theta scrubber, key levels, today, news) → CLOSE all worked first try
with live market data. Analytics page is rich. Journal calendar is clean. Settings are
thoughtful (tiers, DLL, chart appearance).

**Problems found, prioritized:**

1. **Clean build is broken**: `tsc -b --force` fails on main — `vite.config.ts` needs
   `@types/node` (node:path, __dirname). Anyone cloning fresh can't `npm run build`.
2. **Dead code**: `ChainPanel.tsx` (imported by nothing), `ChainTable.tsx` (imported only by
   ChainPanel), `TickerSearchBox.tsx` (retired in b859c44, imported by nothing),
   `TradeDeskToolbar.tsx` (retired toolbar, imported by nothing — only comment references).
   Verified via import-grep from every routed page.
3. **TradeList swallows fetch errors** — `useTrades()` error renders as "No trades logged
   yet" (a lie when the backend is down).
4. **Win definition mismatch** — backend `journal_analytics.py:309` counts win as
   `realized_pnl > 0`; DayModal:402 uses `>= 0`. A $0.00 scratch shows as a "win" in the day
   modal but not in analytics.
5. **Settings DLL override input not clamped** — copy says "Range: 1-10% of the tier's
   starting balance" but you can type anything.
6. **Settings copy bug** — "visual rework adds four customizable knobs" but only 3 controls
   exist in Chart Appearance.
7. **KEY LEVELS panel is cryptic** — EM↑/EM↓/CW/PW/MP/GF with no tooltips, and when no levels
   exist it's a wall of "—" with no explanation of when/why levels appear.
8. **Watchlist page right 2/3 is a placeholder** — "(Restyled full-screen watchlist is a
   later step in the revamp.)" Clicking a symbol sets the chart ticker but you stay on the
   watchlist page with no feedback; you have to manually go to CHART.
9. **Trade ticket has no in-flight state** — BUY/SELL fire mutations with no "Submitting…"
   feedback; on slow networks double-click risk.
10. **Times shown without timezone hint** — entry "13:57" is ET; machine was on PT. The app
    standardizes on ET (market time) which is right, but nothing says so outside the MKT pill.
11. **No keyboard shortcuts for timeframes** — only `/`, `Cmd+K`, `Escape` exist.
12. **Backend: malformed `legs_json` 500s** — `journal.py` analytics raises HTTP 500 ("no
    usable legs") for corrupt rows; should be a 4xx with a clear message.
13. **Position-size discipline gap** (feature): the ticket shows debit but never relates it
    to remaining DLL — the one number a combine trader sizes against.
14. **AnnotatedChart renders nothing for 0 bars** (no empty-state copy). Touching this file
    is delicate (fenced synthetic-candle effect) — only a render-path-level change, if any.
15. Accessibility: chain/ticket buttons lack aria-disabled; trade table headers lack scope;
    meter bars lack ARIA values.

## Plan (ordered, small commits)

- [x] Write this log
- [x] Fix clean build (@types/node)
- [x] Remove dead code (ChainPanel, ChainTable, TickerSearchBox, TradeDeskToolbar
      + JournalPanel subtree found later)
- [x] TradeList error state
- [x] DayModal win definition align with backend
- [x] Settings: clamp DLL override input ("four knobs" copy turned out to be accurate —
      4 knobs exist; explorer report was wrong, no change)
- [x] KEY LEVELS: tooltips + empty-state explanation
- [x] Trade ticket: in-flight (submitting) state on BUY/SELL
- [x] Trade ticket: position-size vs remaining-DLL hint (display-only)
- [x] Keyboard shortcuts: timeframe keys on the terminal
- [x] Watchlist: make the right panel useful (symbol preview + "Open on chart")
- [x] Backend: graceful 4xx for malformed legs + test
- [x] Accessibility pass on components I touched
- [x] ET timezone hint where times render
- [x] (added) Journal CSV export
- [x] (added) Responsive header fix at 1280px
- [x] (added) Analytics filtered-empty state
- [x] (added) Restore npm run lint (ESLint 9 flat config)

## Change log

(append-only; one entry per commit)

### 1. Session log created
- **What**: this file.
- **Why**: required deliverable; review map for the session.
- **Confidence**: sure.

### 2. `@types/node` devDep (9a27653) + gitignore tsc artifacts (dd7be0b)
- **What**: added @types/node; ignored `*.tsbuildinfo` + `vite.config.d.ts`.
- **Why**: `tsc -b --force` (and therefore `npm run build`) failed from a fresh checkout;
  building also littered untracked artifacts.
- **Confidence**: sure. New dep is dev-only and standard for vite configs.

### 3. Dead code removal (0703070, 2c6a87e)
- **What**: deleted ChainPanel, ChainTable, TickerSearchBox, TradeDeskToolbar; then the
  JournalPanel subtree (JournalPanel, PayoffPanel, ThetaScrubber). Updated two stale doc
  comments that still pointed at JournalPanel.
- **Why**: all verified unimported from any file (import-grep, then tsc). BottomStrip
  superseded JournalPanel including its theta scrubber.
- **Confidence**: sure on reachability (tsc-verified). The JournalPanel payoff-curve UI had
  no replacement — if the user wanted to revive the payoff curve someday, revert 2c6a87e
  (listed under reversible decisions).

### 4. Journal list error state (a65f5f8)
- **What**: TradeList renders "Couldn't load trades." + RETRY on query failure instead of
  the "No trades logged yet" empty state.
- **Why**: backend-down looked identical to an empty journal. Verified by killing the
  backend and screenshotting.
- **Confidence**: sure.

### 5. DayModal win definition (bd68fdd)
- **What**: day-modal win rate counts strictly-positive P&L only.
- **Why**: backend analytics uses `> 0`; the modal used `>= 0`, so a $0 scratch made the two
  surfaces disagree.
- **Confidence**: sure.

### 6. Settings DLL clamp (238565e)
- **What**: DLL override input commits on blur/Enter, clamped to the documented 1-10% band;
  garbage reverts. Verified in-browser (typed 99999 → committed 5000 on 50K tier), then
  reset to default.
- **Why**: the input wrote per keystroke, so typing "1500" passed the intermediate "1"
  through the setter (clamping it to the band minimum mid-typing).
- **Confidence**: sure. CORRECTION to my earlier framing: the store's setDllOverride
  already clamped (I found this later) — the real bug was per-keystroke commits fighting
  the clamp while typing, not a missing clamp. The blur-commit input fixes that and makes
  the normalization visible. Header DLL pill now updates on blur rather than per keystroke.

### 7. Key levels tooltips + empty explanation (122250c)
- **What**: EM/CW/PW/MP/GF/IV rows reuse lib/tooltips.ts definitions (+ OI-proxy note on the
  volume-derived four); all-empty column explains where levels come from.
- **Why**: six cryptic acronyms with dashes and zero explanation.
- **Confidence**: sure (display-only).

### 8. ET timestamp labels (bd09b53)
- **What**: "entry 13:57 ET" in open-position panel; tooltip on TODAY row clocks.
- **Why**: bare ET times are ambiguous off-Eastern; explorer machine was on PT.
- **Confidence**: sure.

### 9. Trade ticket: DLL risk hint (372035e) + submitting state (bd488df)
- **What**: "if bought, max loss $X · Y% of remaining DLL" line under the quantity row
  (amber ≥50%, red >100%, explicit DLL-exhausted line); BUY/SELL sub-labels read
  "submitting…" while the open mutation is in flight.
- **Why**: the one number a combine trader sizes against (remaining daily budget) was
  nowhere near the ticket; clicks gave no in-flight feedback.
- **Confidence**: sure on display logic (verified in-browser: 205P ×1 → "2% of remaining
  DLL"). Hint uses realized DLL usage only (header pill folds in open-position UPL; the
  ticket doesn't) — tooltip says so. Deliberately silent for SELL (a short's max loss
  isn't the premium).

### 10. Digit-key timeframe shortcuts (039ae8b)
- **What**: 1-6 switch the terminal chart timeframe; tooltips advertise the keys.
- **Why**: zero keyboard support for the most-touched control.
- **Confidence**: sure (verified incl. the input-focus guard).

### 11. Watchlist preview panel (1ac83c5)
- **What**: new WatchlistPreview fills the placeholder right panel — price/change,
  daily-close sparkline, day/52w range bars, volume, earnings, IV rank/VRP/P/C/skew, and
  OPEN ON CHART.
- **Why**: page was two-thirds placeholder; symbol clicks had no visible effect.
- **Confidence**: probably-right. Verified rendering + click-follow live (SPY → NVDA).
  Uses only existing hooks/endpoints (detail/metrics/bars), so no new backend surface.

### 12. Analytics 422 for corrupt legs + tests (b467d01)
- **What**: corrupted/empty/missing-field legs_json → 422 with a per-trade message
  (was 500). Router shields KeyError/TypeError/ValueError from build_legs_from_journal.
  New offline test file (4 tests). Full backend suite: 295 passed.
- **Why**: stored-data faults crashed as server errors; frontend shows error messages, so
  a real message beats "Internal Server Error".
- **Confidence**: sure.

### 13. Chain market-closed banner + th scopes (105fcf1)
- **What**: role=status strip in the chain when the market is closed; scope="col" on
  TradeList headers.
- **Why**: closed-market chain looked broken (dim cells, no-op clicks, explanation hidden
  in per-cell tooltips).
- **Confidence**: sure. Banner only shows when data exists; the no-0DTE case keeps its
  existing message.

### 14. Chart zero-bars empty state (6ae962e)
- **What**: explicit "No {tf} bars for {symbol} right now" when the payload has an empty
  array. Render-path only — chart mount + synthetic-candle effect untouched.
- **Confidence**: sure (kept far from fence #4).

### 15. Journal CSV export (3782222)
- **What**: EXPORT CSV in the journal toolbar — client-side file of the closed trades
  shown (honors paper/live filter); legs compacted per row; injection-defused quoting;
  verified by intercepting the blob.
- **Why**: traders move journals into Excel/Sheets; there was no way out of the app.
- **Confidence**: sure.

### 16. Header responsive fix (38795f8)
- **What**: pill values nowrap + shrink-0; RP&L/UP&L pills hidden below 1440px.
- **Why**: at 1280px the DLL value wrapped mid-text and MKT clipped off-screen.
- **Confidence**: sure (verified 1280 + 1600). Reversal note: if you want RP&L/UP&L
  visible at every width, remove the `hidden min-[1440px]:flex` classes — but something
  else then has to give at 1280.

### 17. Analytics filtered-empty state (8b98b26)
- **What**: TODAY/WEEK/paper-live with zero matches says "nothing matches this filter"
  instead of "place your first paper trade".
- **Confidence**: sure (verified live).

### 18. ESLint restored (ec8feb1) + lint fixes (0f936bc)
- **What**: flat eslint.config.js for the already-installed ESLint 9 stack; fixed the one
  real error (ternary-as-statement); removed a pointless disable pair. 0 errors,
  7 pre-existing warnings left (hook-deps patterns + one inside the fenced overlay effect
  — deliberately untouched).
- **Why**: `npm run lint` had been failing outright since the v9 upgrade.
- **Confidence**: sure on config; the relaxed rules (no-explicit-any off etc.) are
  my judgment call — tighten if you prefer.

### 19. ChartToolbar stale docstring (d28c228)
- **What**: comment claimed only 1D was wired; all six timeframes are real.

### 20. Chart appearance reset-to-defaults (6be23a9)
- **What**: APPEARANCE_DEFAULTS const + resetAppearance store action + a "reset to
  defaults" link in Settings that appears only when something differs.
- **Why**: no way back to factory values short of re-picking each knob.
- **Confidence**: sure (verified the full loop in-browser).

---

## Needs verification at market open

- ~~KEY LEVELS all "—" for SPY~~ — RESOLVED during the session: once the backend's chain
  cache warmed, all six levels populated (EM↑ $751.19 / EM↓ $732.33 / CW $745 / PW $735 /
  MP $740 / GF $595 at ~15:00 ET). The all-dashes state was Alpaca rate-limit/warm-up,
  not a pipeline bug. The new empty-state copy covers exactly this window.
- **Watchlist stale-snapshot banner** — does it auto-clear when markets reopen Monday?
- **DLL hint at the open** — verify the "% of remaining DLL" math against the header pill
  after a real losing day (I only saw dll_used = 0).
- **Market-closed chain banner** — added during market hours; confirm it renders (and the
  ticket's "market closed" sub-labels) after 16:00 ET.
- **Volume readout on watchlist preview** — Alpaca free-tier "today's volume" looked low
  vs the 20d average mid-session (1.6M vs 53M for SPY). If it's still ~30x off at the
  close, the backend's volume field (or the free feed) deserves a look — display code just
  renders what `/detail` returns.

## Decisions I made that the user may want to reverse

- **Removed the JournalPanel/PayoffPanel/ThetaScrubber subtree** (2c6a87e). It was
  unreachable, but the payoff-curve visualization has no equivalent in BottomStrip. Revert
  that commit to restore.
- **DLL input commits on blur instead of per keystroke** (238565e) — the header pill no
  longer live-updates while typing.
- **Day-modal win rate excludes $0 scratches** (bd68fdd) — matches ANALYTICS, but if you
  preferred scratches-count-as-wins, that was the old behavior.
- **RP&L/UP&L pills hidden below 1440px** (38795f8) — see change 16.
- **ESLint rule relaxations** (ec8feb1) — no-explicit-any and only-export-components off;
  re-enable if you want stricter linting.
- **Analytics 422 contract change** (b467d01) — anything that relied on the old 500 for
  corrupt legs (nothing in this repo did) sees 422 now.

## Things I noticed but did NOT touch (and why)

- **marketing/index.html + landing.css does not exist** on main or any worktree branch. The
  brief said to polish it; there is nothing to polish. Did not create one from scratch —
  copy/pricing/positioning are business decisions and inventing a whole page felt like scope
  the user should green-light. (Needs human decision.)
- **`POST /api/zerodte/open-leg` appears dead** (no frontend caller) — it lives in the fenced
  zerodte.py open path, so left untouched.
- **Retired pages + their unique children** (DashboardPage/MarketPage/NewsPage/SignalPage/
  ZeroDtePage, TopNavBar, DashboardHeader, TickerTape, SignalView tree, CalendarStrip,
  StockDetailView): App.tsx explicitly says they're kept on disk to cannibalize later, so NOT
  dead code by accident — left alone.
- **Watchlist stale-snapshot banner doesn't auto-refresh when market reopens** — market-
  dependent behavior I can't verify off-hours; logged for market open.
- **In-memory TTL cache is single-process** (backend) — noted in code already; fine for dev,
  architectural call for prod.
- **CORS hardcoded to localhost:5173** — correct for dev; deployment decision, not mine.
- **KEY LEVELS all "—" for SPY during a live session** — the models endpoint computed no
  levels mid-session. Needs verification at market open (could be data availability, could be
  a real bug in the levels pipeline).
- **RP&L pill vs balance is_paper inconsistency (needs human decision)** — the header RP&L
  pill counts paper trades only (`TradeDeskHeader.tsx` todayRpl skips `!is_paper`), but the
  backend's `_realized_sum_for_tier` (drives BAL/MLL/HWM) and `_dll_used_today_for_tier`
  (drives DLL) sum ALL closed trades on the tier, live-journaled ones included. So closing a
  LIVE trade moves BAL and DLL but not RP&L. Deciding which semantic is right (should
  real-money journal entries touch the simulated combine at all?) changes what feeds the
  fenced MLL/DLL engine, so I did not touch it. My read: live trades should probably be
  journal-only (excluded from combine balance), which means the backend sums need an
  `is_paper` filter — but that's a product decision.
- **Chain shows 11 strikes (width=5)** — RightChain's comment says a deliberate
  simplification pass reduced it from 16; there's spare vertical room below the ticket on
  tall screens, but I respected the recorded decision and left it.
- **`POST /api/zerodte/open-leg` dead endpoint** (also under fences): no frontend caller.
- **Horizontal-line drawing tool: inconclusive QA** — the toolbar button mounts, but I
  couldn't exercise a draw via synthetic browser events (lightweight-charts consumes its
  own coordinate/click stream, so dispatched MouseEvents don't reach its subscription).
  Needs a human mouse: click the ― tool, click the chart, confirm a line lands and
  persists. I did not change any drawing code.
- **Coachmark count** — Coachmark.tsx records a deliberate "two coachmarks max" Phase 1
  spec; I considered a third for the chain → ticket flow and skipped it (the empty ticket
  already says "Click a strike in the chain ↑").
- **Pre-existing lint warnings (7)** — hook-deps patterns (`?? []` recreated per render
  feeding useMemo deps) in BottomStrip/SymbolSearch/JournalPage/PositionsPage,
  a chartRef-in-cleanup warning in ChartDrawingLayer, and one unused eslint-disable inside
  the fenced overlay effect. All pre-existing behavior; fixing them is mechanical but
  touches hot paths, so I left them visible rather than silently churning code.
