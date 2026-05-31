# Trade Desk audit

Read-only system audit, May 30 2026. Source of truth: HEAD `3cac389`.
Scope: bugs (broken behavior) + gaps (claimed vs. actual) + polish.
Framing: YC June 4 application. Each finding is rated for what it
means for a 60-second demo video, a partner conversation, and a
written submission.

No code was modified. All claims verified by code reading + TestClient
runs where possible.

---

## Method

- Read every file touched by the trade-open / chart / chain / ticket /
  header / settings / account paths.
- Ran `pytest` (216/216 green) and bespoke TestClient probes for tier
  math, market-clock guard, and ticker search.
- Inspected react-query keys + zustand stores for cache- and
  selection-coherence.
- Inspected backend external-call paths for timeout safety.
- Could NOT verify (documented at end): live-market behavior of chain
  ladder, BUY/SELL mutations against real Alpaca, live scrubber motion,
  and any color customization round-trip across a true reload (the
  zustand `persist` pattern is correct in code; not exercised in this
  audit beyond static inspection).

---

## Findings

### B-001  Single-leg position renders TWO magenta lines on the chart
- **Category** Bug
- **Severity** P1 (must fix before demo video)
- **Effort** XS (drop one branch, ~10 LoC)
- **Impact for YC** Directly contradicts the "moving breakeven" pitch.
  A user watching a video sees two BE lines on what the narration
  calls a single call and thinks the math is wrong. Partner asking
  "why are there two breakevens?" is a hard question if the answer is
  "one of them isn't a breakeven, it's a ghost."
- **File(s)** `frontend/src/components/stock/AnnotatedChart.tsx:431-452`
- **Description** The chart renders both `breakevensToday` AND
  `breakevensExpiration` (skipping only the expiration BE that is
  within $0.05 of a live BE). For a long_call with DTE>0 those values
  differ measurably:
  - `breakevens_today` = strike + current premium ≈ 100.61
  - `breakevens_expiration` = strike + entry premium = 105.00
  → one solid magenta line + one dotted magenta "BE✕" line. To a
  user, BOTH read as "breakeven." Backend math is correct (1 BE for
  single-leg, confirmed by direct call); the FRONTEND draws a second
  reference line called "expiration BE" alongside.
- **Reproduction** Open a long_call paper trade with DTE > 0. Look at
  the chart. Two magenta lines appear: one solid (today), one dotted
  ("BE✕"). User reports this as "two breakevens on a single-leg call."
- **Recommended fix** Either (a) drop the `breakevensExpiration`
  overlay entirely (cleanest — the today BE already moves toward
  expiration as theta burns, so showing both is redundant), or (b)
  rename the dotted line to "EXP" / "AT EXPIRY" and use a non-magenta
  hue (cyan? warning?) so a user does not read it as another BE.
- **Confidence** High. Verified backend math returns 1 BE for
  long_call/long_put/short_call; verified frontend renders both
  arrays.

### B-002  Double-click BUY/SELL can open two trades
- **Category** Bug
- **Severity** P1 (live-trading hazard)
- **Effort** S (add a `useRef` guard, 5 LoC; or block via
  mutation.isPending check inside the handler with a ref)
- **Impact for YC** Demo risk: a nervous demo'er hammering BUY will
  open a duplicate position. More importantly, this is a "table
  stakes" defense in any execution platform — a partner asking "what
  prevents accidental dupes" wants to hear "we guard the click." Today
  the answer is "we disable the button after react renders."
- **File(s)** `frontend/src/components/positions/TradeTicket.tsx:44-82`
- **Description** `pending = legMutation.isPending ||
  straddleMutation.isPending` and `canFire = ... && !pending`. The
  button receives `disabled={!canFire}`. React batches state updates,
  so between the first click's `mutate()` and the next render, a
  second synchronous click sees `pending=false` in the closure and
  fires a second mutation. Two trades open.
- **Reproduction** Click BUY twice within ~16ms (one frame). Two
  `POST /api/zerodte/open-leg` requests fire.
- **Recommended fix** Guard with a ref:
  ```ts
  const submittingRef = useRef(false);
  const fire = (action) => {
    if (submittingRef.current || !canFire) return;
    submittingRef.current = true;
    mutation.mutate(..., { onSettled: () => { submittingRef.current = false; }});
  };
  ```
- **Confidence** High. Pattern is reliable; not exercised in a real
  click but the code path is unambiguous.

### B-003  Toolbar timeframes 1m/5m/15m/1h/4h all show the same 1D bars
- **Category** Gap (presented as a bug from the user's perspective)
- **Severity** P1 ("timeframes def not right" — user already noticed)
- **Effort** L (real intraday bars requires Alpaca minute-bars
  endpoint integration + cache layer) or XS (kill the stubs from the
  visual toolbar).
- **Impact for YC** Demo video viewer clicks 5m, sees daily candles.
  Looks broken even though it's "stub" behavior. The honest fix for
  the video is to remove the stubs from the toolbar — but then the
  toolbar looks sparse and Topstep-comparable platforms have multiple
  timeframes. Either way, do not record video while these stubs are
  in.
- **File(s)** `frontend/src/components/positions/ChartToolbar.tsx:36-53`
- **Description** `TF_VISUAL = ["1m","5m","15m","1h","4h","1D"]` but
  `TF_REAL_MAP` routes every one of them to `"1D"`. The OHLC strip
  labels with the visual TF but pulls bars from the real TF, so
  clicking 5m shows "SPY · 5m" with daily-bar OHLC. Tooltip explains
  the fallback but a user does not hover. Additionally, the Settings
  page TimeframePicker offers `1D / 5D / 1M / 3M` — none of which the
  toolbar can represent, AND clicking any toolbar TF resets the chart
  from a multi-day to 1D (settings default of 5D loses its 4 extra
  days the moment user touches the toolbar).
- **Reproduction** Cold open. Notice chart shows ~50 daily candles
  (5D default). Click 5m. Chart now shows 1 daily candle. Click 1D.
  Same single candle.
- **Recommended fix** Short-term (P1): remove the intraday stubs from
  the toolbar; keep only 1D / 5D / 1M / 3M to match the real backend
  timeframes; have the toolbar wire to those properly. Long-term:
  build real minute-bar fetching, then re-add the intraday options.
- **Confidence** High. User already reported. Code path verified.

### B-004  Active position from one tier shows on the other tier's screen
- **Category** Bug
- **Severity** P1 (cross-tier contamination — directly undermines the
  tier story)
- **Effort** S (one filter clause + reset on switch)
- **Impact for YC** The 50K/100K/150K combine story is load-bearing
  in the "Topstep of options" pitch. If you switch tiers and a
  100K-tier open position still renders on the 50K combine's chart
  + bottom strip, the tier boundary is leaky. Partner could spot
  this by clicking the tier pill twice.
- **File(s)**
  - `frontend/src/hooks/useTrades.ts:14-19` (no tier filter)
  - `frontend/src/components/positions/TradeDeskHeader.tsx:185-220`
    (todayRpl filters by tier; UP&L does not)
  - `frontend/src/hooks/useAccountState.ts:26-35` (switchTier
    invalidates trades but doesn't reset activePosition)
- **Description**
  1. `useTrades()` fetches ALL trades, no tier filter. The
     `activeTrade = trades.find(t => t.id === activeTradeId)` lookup
     happily resolves to a trade whose `tier` does not match the
     current `account.active_tier`.
  2. Header's `todayRpl` filters `t.tier !== activeTier` (correct).
     But the UP&L cell uses `analyticsQuery.data?.unrealized_pnl`
     unconditionally — so a 100K-tier trade's UPL surfaces on the
     50K header.
  3. `useSwitchTier.onSuccess` does not clear `useActivePosition`. The
     tradeId persists across switches.
- **Reproduction** On 100K combine, open a trade (or set
  `tradeId: <existing 100K trade>`). Switch to 50K via the pill.
  Chart still shows the magenta entry triangle + BE line, OPEN
  POSITION column still populates, UP&L still shows. RP&L correctly
  drops to 0 (the only thing the filter caught).
- **Recommended fix** Two-pronged:
  - `useSwitchTier.onSuccess`: also clear `useActivePosition`.
  - Either (a) filter `useTrades` by active tier or (b) gate the
    `activeTrade` lookup in PositionsPage on `t.tier === activeTier`.
- **Confidence** High. Code paths confirmed.

### B-005  Close button + Account state — 5s lag after closing a trade
- **Category** Bug (UX feel)
- **Severity** P2
- **Effort** XS (one invalidation call)
- **Impact for YC** In a video, user closes a position and the header
  BAL/MLL/RP&L numbers stay frozen for up to 5 seconds before
  updating. Looks slow / broken. Easy to fix.
- **File(s)** `frontend/src/components/positions/BottomStrip.tsx:264-278`,
  `frontend/src/hooks/useAccountState.ts`
- **Description** The CLOSE button's mutation invalidates
  `["journal", "trades"]` but NOT `["account", "state"]`. The
  account-state hook polls every 5s; until the next poll, header
  numbers reflect the pre-close state. Same gap exists when
  opens fire (`useOpenZeroDte{Leg|Straddle}`).
- **Recommended fix** Add `queryClient.invalidateQueries({ queryKey:
  ["account", "state"] })` to the close mutation's onSuccess AND to
  both open mutations' onSuccess.
- **Confidence** High.

### B-006  TODAY column rows are not clickable
- **Category** Gap
- **Severity** P3
- **Effort** XS (wrap row in a button, dispatch setTradeId)
- **Impact for YC** Minor. A user might expect clicking a trade row
  to make it the active position (the way OpenPositionsList used to
  work in the legacy layout). Today they're inert `<div>`s.
- **File(s)** `frontend/src/components/positions/BottomStrip.tsx:918-955`
- **Confidence** High.

### B-007  Volume used as OI proxy on call wall / put wall / max pain
- **Category** Gap (data quality)
- **Severity** P1 (defensibility issue with a sophisticated investor)
- **Effort** L (real OI requires paid Alpaca tier or supplementary
  feed — IBKR options feed, Tradier, etc.)
- **Impact for YC** A partner who knows options will notice or ask.
  "Is that OI or volume?" — today the honest answer is "volume; OI
  isn't on the free Alpaca tier." That answer is FINE as long as you
  pre-empt it. If the pitch claims "options structure overlays" and a
  partner reads it as "real OI walls," that's a credibility hit.
- **File(s)** `backend/services/alpaca_client.py:355-368` (documented
  in the comment), `backend/routers/ticker.py` (computes walls from
  volume).
- **Description** The free Alpaca indicative feed does NOT carry
  `open_interest`. Call wall / put wall / max pain / gamma flip are
  computed from PER-CONTRACT VOLUME instead. Different number.
  Documented in code comments but not in the UI.
- **Recommended fix** Either (a) paid feed integration to get real
  OI, or (b) clearly label these "VOL-proxy" in the UI tooltips and
  in any YC submission text. The honest disclosure is short and
  professional.
- **Confidence** High. Documented in the code itself.

### G-001  Chart toolbar "candles ▾" / drawing tools / "indicators ▾" are visual stubs
- **Category** Gap
- **Severity** P1 (high discovery risk in a 60-second demo)
- **Effort** XS (hide them) or L (build them)
- **Impact for YC** Every one of these looks like a real button. A
  curious viewer hovering during the video sees nothing happen on
  click. In a partner walkthrough this is the first place they'd
  poke. The honest move is to hide them until at least one is real.
- **File(s)** `frontend/src/components/positions/ChartToolbar.tsx:150-195`
- **Description** Five inert buttons in the chart toolbar:
  - `CandleTypeStub` — "candles ▾" with no menu
  - `DrawingToolStubs` — three icons (/, —, ▭) with no draw behavior
  - `IndicatorsStub` — "indicators ▾" with no menu
  Each has a `title` attribute marking it a stub, but `title` only
  surfaces on hover. The redesign brief explicitly authorized stubs;
  they read as real in a recorded demo.
- **Recommended fix** Hide them until real for the YC video. The
  toolbar with just (timeframes | LEGEND | LEVELS↓) reads as
  professionally minimal rather than as a wall of inert UI.
- **Confidence** High.

### G-002  Search catalog is hardcoded (16 symbols); 0DTE flag is hardcoded to the universe
- **Category** Gap
- **Severity** P1 (matters once a partner types a real ticker)
- **Effort** M (replace catalog with a live universe; expand 0DTE
  check to actual expiry availability)
- **Impact for YC** Type "BABA" → empty result. Type "AAPL" → search
  hits, but the badge says "no 0DTE today" even though AAPL has daily
  expiries. SPX shows "no 0DTE today" too. The search is a 16-entry
  picker dressed as search.
- **File(s)** `backend/routers/ticker_search.py:33-50` (catalog
  hardcoded), `backend/routers/ticker_search.py:96-100` (has_0dte_today
  flag is `symbol in settings.zero_dte_universe`)
- **Description** As shipped, the search ranks against 16 tickers
  (SPY/QQQ/IWM + SPX/NDX/DIA + AAPL/MSFT/NVDA/TSLA/AMD/GOOGL/AMZN/META/
  NFLX/AVGO). 0DTE flag is True for SPY/QQQ/IWM only — false for
  AAPL/NVDA/SPX which DO have daily expiries in reality. Documented
  as a "static catalog" gap in `VISUAL_REWORK_REPORT.md` but not
  fixed.
- **Recommended fix**
  - Catalog: use a real symbol-name table (NASDAQ's bulk-download
    list is free, or finnhub's `/stock/symbol`).
  - 0DTE flag: call `get_chain_snapshot(sym)` and check `len([c for c
    in chain if c.expiry == today])` — same logic the chain table uses.
    Cache 5min.
- **Confidence** High.

### G-003  Chart drawing tools, indicators, candle-type — all listed in the toolbar but none work
- **Category** Gap
- **Severity** P1 (duplicate of G-001 framed for the punch list)
- **Effort** L (build each) or XS (hide)
- **Impact for YC** See G-001.

### G-004  "MOVING BREAKEVEN" hook never demonstrated live with a real recording
- **Category** Gap
- **Severity** P1 (this is THE pitch — needs a recording)
- **Effort** S (record on Monday at 09:31 ET with a real 0DTE straddle)
- **Impact for YC** The product's headline differentiator. Math works
  in tests; we have not produced any video evidence of the BE line
  visibly moving. For the application, this needs to be a recorded
  demo, not a still screenshot.
- **File(s)** N/A (live behavior; analytics path verified in unit
  tests `test_position_analytics.py`)
- **Recommended fix** Monday 09:31 ET: open a 1-contract SPY long
  straddle on the paper account. Screen-record the chart for ~30s as
  the underlying drifts. Both magenta BE lines should walk inward as
  theta burns. Alternatively, record off-market by scrubbing the
  theta scrubber and capturing the lines moving in response — that's
  controllable without market hours.
- **Confidence** High.

### G-005  Two-tone breakeven line is confusable with two real BEs (see B-001)
- See B-001.

### G-006  IV rank needs 60 trading days of history before it populates
- **Category** Gap (data freshness)
- **Severity** P2
- **Effort** N/A (time + scheduled job already running)
- **Impact for YC** KEY LEVELS panel shows IV row as `—` or
  `X/60 days collected` until the snapshot job has run for 60 days.
  In the YC submission window, IV rank will say nothing useful for
  most tickers. Acceptable IF you do not promise it; flag if any
  copy says "IV rank for every ticker."
- **File(s)** `backend/routers/ticker.py:62, 332-338`
- **Confidence** High.

### G-007  No daily-loss-limit (DLL) — "MLL only" is the actual scope today
- **Category** Gap
- **Severity** P2 (depending on how the YC application frames the
  combine model)
- **Effort** M (mirror MLL math, add a `daily_loss` calculation)
- **Impact for YC** Topstep enforces both MLL and DLL. The Trade Desk
  combine has only MLL. If the application says "Topstep mechanics"
  without qualification, the gap is visible. Easy to handle in copy:
  "We implement Topstep's trailing-drawdown MLL today; daily loss
  enforcement is on the roadmap."
- **File(s)** `backend/services/account_tiers.py` (no DLL field on
  Tier); `frontend/src/components/positions/TradeDeskHeader.tsx` (no
  DLL pill)
- **Confidence** High.

### G-008  No MLL enforcement on trade open
- **Category** Gap
- **Severity** P2 (depends on framing)
- **Effort** S (add a guard in `routers/zerodte.py` similar to
  `_require_market_open`)
- **Impact for YC** Today, balance can fall below MLL and trades keep
  opening. The pill shows "MLL BREACHED." This is "display only" by
  design per the original prompt. For the YC pitch you can say "MLL
  is monitored; enforcement is one config flag away" — but the user
  would not see enforcement in a live demo today. If a partner asks
  "what happens when I breach?" the answer is "in the funded version
  the account is paused; in combine the indicator turns red but you
  can keep going."
- **Confidence** High.

### G-009  No profit targets / no minimum trading days / no consistency rule / no payout flow
- **Category** Gap
- **Severity** P2
- **Effort** M (each rule is small; a coherent combine engine is more
  work)
- **Impact for YC** The "Topstep of options" comparison invites
  partners to check each Topstep rule against ours. Today we have
  ONLY: starting balance + trailing MLL. We have no profit targets
  (typical: 6% / 9% / 9% of starting), no minimum days (5–10), no
  consistency rule, no funded conversion. For the application this is
  fine if the framing is "Topstep mechanics for options, starting
  with the combine + MLL." Set expectations.
- **Confidence** High.

### G-010  Chart Appearance settings — verified wired, NOT verified end-to-end
- **Category** Gap (verification)
- **Severity** P3
- **Effort** S (just exercise it once and confirm)
- **Impact for YC** Static audit confirms the userSettings setters
  exist and AnnotatedChart subscribes. Did not exercise the color
  picker → chart update → reload-and-restore cycle in this audit.
- **Recommended fix** Walk it once before submission. Change bullish
  to teal, reload, confirm teal sticks.
- **Confidence** Medium (code path is right; not exercised).

### G-011  KEY LEVELS values fall to "—" when chain data is unavailable
- **Category** Gap (UX)
- **Severity** P3
- **Effort** Built-in (already handled; the inline strip hides empty
  items and falls back to "No levels for SYMBOL today")
- **Impact for YC** Acceptable for the empty state. Just verify that
  weekday SPY rendering shows the values, not dashes.
- **Confidence** High.

### P-001  Close button still uses pre-rework outlined style
- **Category** Polish
- **Severity** P2 (visible inconsistency on the screen the demo will
  focus on)
- **Effort** XS (swap to filled-pill treatment)
- **Impact for YC** The CLOSE button in the OPEN POSITION column has
  0 border-radius, hairline border, no fill — the exact style the
  rest of the toolbar moved AWAY from in Phase B. Sits next to the
  filled rounded BUY/SELL. Inconsistent.
- **File(s)** `frontend/src/components/positions/BottomStrip.tsx:449-477`
- **Recommended fix** Either give it the same filled-red treatment as
  the SELL button (smaller height — 32px is plenty), or migrate it to
  UIButton with `active`+bearish overrides.
- **Confidence** High.

### P-002  Coachmark uses amber border for an informational hint
- **Category** Polish
- **Severity** P3
- **Effort** XS (swap to warning color or cyan)
- **Impact for YC** Coachmark hints (the THETA SCRUBBER intro) use
  `border-amber` + `text-amber`. DESIGN.md says amber is for active/
  selected only. Coachmarks are guidance. Technically out of compliance
  with the discipline; visually defensible. Worth a 1-line swap.
- **File(s)** `frontend/src/components/positions/Coachmark.tsx:48-53`
- **Confidence** Medium (depends on whether you treat coachmarks as
  "selected RIGHT NOW").

### P-003  Toolbar's "LEVELS ↓" hint does nothing on click
- **Category** Polish
- **Severity** P3
- **Effort** XS (drop the hint, or scroll to KEY LEVELS on click)
- **Impact for YC** A small label saying "levels ↓" sits at the right
  edge of the toolbar; clicking it does nothing. Acceptable as
  signage, weird as an actionable affordance.
- **File(s)** `frontend/src/components/positions/ChartToolbar.tsx:229-238`
- **Confidence** High.

### P-004  Header's price readout vs. metric pills — visual asymmetry
- **Category** Polish (intentional per spec, noting for record)
- **Severity** P3
- **Effort** N/A
- **Impact for YC** The spec called for live price as a non-pill
  cluster. Some viewers may expect the price to also live in a
  bordered pill to match BAL/MLL/etc. Acceptable as-is.
- **Confidence** High (intentional design choice).

### P-005  Settings page "Reload to apply" footer is stale
- **Category** Polish
- **Severity** P3
- **Effort** XS
- **Impact for YC** Bottom of the Settings page reads "Reload the
  page to apply settings that affect cold-open behavior (default
  ticker, timeframe)." After the Chart Appearance section landed,
  several settings ALSO apply live without a reload — the copy is
  partially stale.
- **File(s)** `frontend/src/pages/SettingsPage.tsx:88-94`
- **Confidence** High.

### P-006  TopNavBar.tsx + TradeDeskToolbar.tsx + SymbolSearch.tsx + PaperAccountHeader.tsx are dead code
- **Category** Polish
- **Severity** P3
- **Effort** S (delete files + remove imports)
- **Impact for YC** None directly; cleanliness. The redesign
  intentionally kept them on disk for rollback, but commits 03d5f6d
  and onward are now stable. Worth a sweep before YC submission to
  shrink the diff a partner might browse on GitHub.
- **Confidence** High.

### P-007  MLL color logic is applied to the MLL cell, not BAL
- **Category** Polish (the spec text said BAL; the implementation
  colors MLL — both are defensible)
- **Severity** P3
- **Effort** N/A (working as built, possible spec mis-read)
- **Impact for YC** None — both choices convey "how close are you to
  the floor."
- **File(s)** `frontend/src/components/positions/TradeDeskHeader.tsx:209-218`
- **Confidence** High.

### P-008  Cross-toggle redundancy: LEGEND button + on-chart Legend button + KEY LEVELS toggle
- **Category** Polish
- **Severity** P3
- **Effort** S (consolidate)
- **Impact for YC** Three controls touch the same state in different
  panels. Acceptable; mildly confusing. Worth a future cleanup.
- **Confidence** High.

---

## Totals

### By severity
- P0: 0
- P1: 9  (B-001, B-002, B-003, B-004, B-007, G-001, G-002, G-003, G-004)
- P2: 5  (B-005, G-006, G-007, G-008, P-001)
- P3: 11 (B-006, G-009, G-010, G-011, P-002 through P-008)

### By category
- Bugs: 7 (B-001 .. B-007)
- Gaps: 11 (G-001 .. G-011)
- Polish: 8 (P-001 .. P-008)

### Effort (rough order-of-magnitude)
- XS: 11
- S: 8
- M: 4
- L: 4

### Estimated total — bring everything P0/P1 to ship-ready
~1.5 engineer-days, dominated by:
- Real intraday timeframes if you want to keep the toolbar stubs (L)
- Real OI feed if you want to claim "walls" honestly (L)
- Real search catalog + 0DTE check (M)
- Live demo recording of the moving-BE hook (S)
- Everything else is XS / S

---

## TOP 10 — do these before the YC submission

1. **B-001** (XS) Drop or rename the `breakevensExpiration` ghost
   line. Two magenta lines on a single-leg position will be the first
   thing a partner asks about.
2. **G-001 / G-003** (XS) Hide the stub buttons in the chart toolbar
   for the demo: candles ▾, drawing tools, indicators ▾. The toolbar
   reads tighter and you stop selling something that does not work.
3. **B-003** (XS) Drop the intraday timeframe buttons (1m / 5m /
   15m / 1h / 4h) until you have real intraday bars. Keep 1D as the
   only timeframe, or wire the toolbar to the real 5D / 1M / 3M
   options from Settings.
4. **B-002** (S) Ref-guard the BUY/SELL fire path. Trivial fix; a
   real "we protect against duplicate fills" answer.
5. **B-004** (S) Reset `useActivePosition` on tier switch AND filter
   the active-trade lookup by tier. Tier story stops leaking.
6. **G-004** (S) Monday 09:31 ET: record a 30-second screen-cap of
   the BE line walking on a SPY long straddle. This IS the demo
   video. Backup: record the scrubber-driven BE motion off-market.
7. **B-005** (XS) Invalidate `["account", "state"]` from the close +
   open mutations. Header numbers update instantly instead of 5s
   later.
8. **G-002** (M) Wire the search catalog to a real symbol list and
   the 0DTE check to actual chain availability. AAPL, NVDA, BABA all
   need to work or the search is theater.
9. **P-001** (XS) Migrate the CLOSE button to the filled rounded
   style. Sits next to BUY/SELL; should match.
10. **B-007** (L → or copy fix) Decide whether the YC submission
    needs real OI or whether you label "wall (volume proxy)" in the
    UI + the application copy. The honest disclosure is short.

---

## RECORDABLE FOR VIDEO — ranked

1. **Tier pill switch** (50K → 100K → 150K). BAL/MLL update live. The
   "Topstep of options" hook in 4 seconds.
2. **MLL trailing demo**: Open a winning paper trade, close it, watch
   MLL trail up in the header. Visually obvious.
3. **Theta scrubber drives on-chart breakevens** (after fixing
   B-001). The differentiator.
4. **Chain ladder click → trade ticket → BUY +1**. The trade-flow
   bread-and-butter. (Requires market hours OR a clean screenshot
   sequence with mock data.)
5. **KEY LEVELS toggle**: show on chart → market-structure overlays
   appear. Demonstrates "the chart can show you what matters."

Do NOT record:
- Any toolbar timeframe other than 1D until B-003 is addressed.
- Any drawing tool / candle-type / indicators click until G-001/G-003
  is addressed.
- Search results for tickers that aren't SPY/QQQ/IWM until G-002 is
  addressed.

---

## DEFENSIBLE FOR PARTNER CONVO

Pre-empt these topics. If the partner asks first, the moment is lost.

- **"Are those real options prices?"** → "Indicative quotes from the
  Alpaca free tier. Cells where indicative is unavailable use
  Black-Scholes against the ATM-implied IV — those are marked with a
  small `·m` glyph. Live-feed integration is a flip-the-flag away
  once we move off the free tier."
- **"Is that real open interest in your walls?"** → "Today it's
  per-contract volume as an OI proxy — the free Alpaca tier doesn't
  ship OI. The pitch carefully says 'options structure' rather than
  'OI'. Paid-feed OI is on the roadmap; the wall computation already
  accepts an OI input." (Fix or disclose; do not let them spot it.)
- **"What enforces the MLL?"** → "Today it's a live monitor and a
  display indicator. Hard enforcement on trade open is one config
  flag away — the math, persistence, and UI are all in place. Combine
  pass / fail logic is the next phase."
- **"Why are there two breakevens on a single call?"** (only if you
  ship without fixing B-001) → "The dotted line is the breakeven at
  expiration; the solid is the live theta-adjusted breakeven. They
  move toward each other as expiry approaches." Better to fix.
- **"What's actually live data here?"** → underlying price (yes),
  options indicative prices (yes), greeks (yes, computed),
  breakevens (yes), KEY LEVELS (yes, but vol-proxy), IV rank
  (60-day backfill required — `X/60 days` is the honest readout).

---

## COULD NOT VERIFY

These were not in scope for a read-only audit on a weekend with the
market closed.

- The chain ladder visual styling (§8 of the visual rework) — chain
  data was unavailable today; the CSS lives in `RightChain.tsx` but a
  live render Monday morning is needed to confirm the 20px rows,
  every-5 hairline grouping, and amber ring on selected rows.
- The Topstep-style BUY/SELL filled buttons firing real mutations
  against `POST /api/zerodte/open-leg` — backend path is solid
  (`216/216` tests pass; 409 guard fires correctly on closed market).
- The Chart Appearance color customization round-trip across a
  full page reload — code path is correct (`persist` middleware
  configured) but not exercised here.
- The live theta scrubber dragging the on-chart BE — `useTradeAnalytics`
  + `chartOverlay` wiring is verified statically; physical drag of
  the slider was not exercised.

All four require either market hours, a paper-trade open, or a
human in the loop. Plan for them on the live-demo recording day.

---

## CLOSING NOTES

The product holds up under audit better than the punch list suggests
— most P1 items are XS-effort renaming/hiding/guarding. The pitch
("Topstep of options" with the moving-BE hook) is technically real;
the gaps are in surface area (intraday timeframes, real search,
drawing tools) and in display honesty (volume-as-OI, two-magenta-lines
on a single-leg).

Three actions, in order, dominate the YC-readiness curve:

1. Fix B-001, B-002, B-003 and hide G-001/G-003. ~2 hours total.
   The product stops looking incomplete on first interaction.
2. Record a Monday-morning demo (G-004). ~10 minutes once the market
   opens.
3. Decide on the disclosure language for B-007 (volume as OI proxy)
   and G-002 (search catalog). 30 minutes of copywriting.

After those three, the product is YC-application defensible. The
remaining items are quality-of-life.
