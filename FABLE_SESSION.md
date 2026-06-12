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
- [ ] Fix clean build (@types/node)
- [ ] Remove dead code (ChainPanel, ChainTable, TickerSearchBox, TradeDeskToolbar)
- [ ] TradeList error state
- [ ] DayModal win definition align with backend
- [ ] Settings: clamp DLL override input; fix "four knobs" copy
- [ ] KEY LEVELS: tooltips + empty-state explanation
- [ ] Trade ticket: in-flight (submitting) state on BUY/SELL
- [ ] Trade ticket: position-size vs remaining-DLL hint (display-only)
- [ ] Keyboard shortcuts: timeframe keys on the terminal
- [ ] Watchlist: make the right panel useful (symbol preview + "Open on chart")
- [ ] Backend: graceful 4xx for malformed legs + test
- [ ] Accessibility pass on components I touched
- [ ] ET timezone hint where times render

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
- **Why**: store accepted any value while the copy promised a range.
- **Confidence**: sure. Note: header DLL pill now updates on blur rather than per keystroke.

### 7. Key levels tooltips + empty explanation (122250c)
- **What**: EM/CW/PW/MP/GF/IV rows reuse lib/tooltips.ts definitions (+ OI-proxy note on the
  volume-derived four); all-empty column explains where levels come from.
- **Why**: six cryptic acronyms with dashes and zero explanation.
- **Confidence**: sure (display-only).

### 8. ET timestamp labels (bd09b53)
- **What**: "entry 13:57 ET" in open-position panel; tooltip on TODAY row clocks.
- **Why**: bare ET times are ambiguous off-Eastern; explorer machine was on PT.
- **Confidence**: sure.

---

## Needs verification at market open

(running list)

## Decisions I made that the user may want to reverse

- **Removed the JournalPanel/PayoffPanel/ThetaScrubber subtree** (2c6a87e). It was
  unreachable, but the payoff-curve visualization has no equivalent in BottomStrip. Revert
  that commit to restore.
- **DLL input commits on blur instead of per keystroke** (238565e) — the header pill no
  longer live-updates while typing.
- **Day-modal win rate excludes $0 scratches** (bd68fdd) — matches ANALYTICS, but if you
  preferred scratches-count-as-wins, that was the old behavior.

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
