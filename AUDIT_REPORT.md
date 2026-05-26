# Audit report — autonomous session (2026‑05‑26)

This run audited the codebase top‑to‑bottom against the operating rules
in the brief, made three bounded safe fixes, and documents everything
else as recommendations rather than changes. The five frozen targets
(`black_scholes.py`, `intraday_analytics.py`, `position_analytics.py`,
`routers/zerodte.py`, the market‑clock logic in `services/alpaca_client.py`
and `services/market_calendar.py`) are unchanged — SHA256s captured at
start and end match exactly.

Commits in this run (baseline + 3 fixes):

| Hash      | Title                                           |
|-----------|-------------------------------------------------|
| `2c42c23` | Baseline before autonomous audit run            |
| `a6caf34` | Audit fix 2a: scheduler timeouts + misfire      |
| `d4489b1` | Audit fix 2b: spacing consistency on chain header |
| `258787e` | Audit fix 2c: Settings panel — four wired prefs |

---

## 1. SUMMARY — top 5 findings

1. **Scheduler wedge cause: SDK calls with no per‑request timeout** —
   the `alpaca-py` clients don't accept a `timeout` parameter at init
   and `finnhub.Client` only honors a class‑level 10s default.
   `refresh_watchlist` had no wall‑clock budget, so one slow symbol
   could stretch a tick past the 60s interval and APScheduler would
   silently drop subsequent runs. **Fixed in 2a.**
2. **Substantial stranded dead code** — the entire Analysis dashboard
   (5 pages, 14 components, 6 hooks, 6 backend routers) is on disk and
   wired through `main.py` but unreachable from any live route. Roughly
   2,500 LOC frontend + 1,200 LOC backend ready for removal once
   reviewed. **Catalogued in §2.1; not removed per operating rules.**
3. **Stranded analytical value, worth resurfacing** — IV rank, VRP,
   25Δ skew, P/C ratio, max pain, the LSTM vol forecast, the CatBoost
   earnings model, the RF regime model and the Monte Carlo + payoff
   panels all still compute and serve over HTTP, but no live UI
   consumes them. This is your "spotting" layer ready to be plugged
   back in. **Catalogued in §2.2.**
4. **`BORDER STRONG` palette typo** — DESIGN.md specifies `#2A2E38` but
   the codebase consistently uses `#2A2D36` (one byte different).
   Trivial DESIGN.md update or palette correction. **§2.4.**
5. **Settings page is now wired** — four persisted preferences
   (default ticker, default contracts, default annotations on,
   default chart timeframe) each affect the app on next render.
   Previously a stub. **Fixed in 2c.**

---

## 2. AUDITED & FOUND

### 2.1 Dead / stranded code

The audit confirms a clean two‑tier separation between **alive code**
(reachable from `App.tsx`'s 5 routes) and **stranded code** (still on
disk, but no live import chain reaches it). Nothing was deleted; this
is the list a human review should approve.

#### 2.1.1 Pages — unrouted

`frontend/src/pages/` has these page modules unreferenced by `App.tsx`:

| Page                      | Confidence to remove | Notes |
|---------------------------|----------------------|-------|
| `DashboardPage.tsx`       | safe                 | App.tsx mentions it in a *comment* only |
| `MarketPage.tsx`          | safe                 | Comment‑only reference |
| `NewsPage.tsx`            | safe                 | Comment‑only reference |
| `SignalPage.tsx`          | safe                 | Comment‑only reference |
| `ZeroDtePage.tsx`         | needs‑review         | "Kept for rollback" per the in‑file note. Still references `fetchZeroDteChain` + `fetchZeroDteMark`; those backends are still alive but unused. |

#### 2.1.2 Components — transitively dead (only used by retired pages)

```
components/layout/
  CalendarStrip.tsx           safe   only DashboardPage
  DashboardHeader.tsx         safe   App.tsx comment only
  TopNavBar.tsx               safe   App.tsx comment only

components/tradingview/
  TickerTape.tsx              safe   App.tsx comment only
  TradingViewEmbed.tsx        safe   MarketPage / NewsPage only
  TradingViewWebComponent.tsx safe   TickerTape only

components/stock/
  StockDetailView.tsx         safe   DashboardPage / SignalView only
  PriceHeader.tsx             safe   StockDetailView only
  OptionsMetricsRow.tsx       safe   StockDetailView only
  ModelSignalsRow.tsx         safe   StockDetailView only

components/signal/  (entire directory)
  SignalView.tsx              safe   SignalPage only
  VerdictCard.tsx             safe   SignalView only
  SignalBreakdown.tsx         safe   SignalView only
  ThesisPanel.tsx             safe   SignalView only
  MockFlowBanner.tsx          safe   SignalView only

components/modeling/  (entire directory)
  BlackScholesPanel.tsx       safe   StockDetailView only
  MonteCarloPanel.tsx         safe   StockDetailView only
  StrategyPicker.tsx          safe   BlackScholesPanel only
  ModelingPanelSkeleton.tsx   safe   BS/MC panels only

components/positions/
  ModeToggle.tsx              safe   imports TopNavBar; never mounted
  BottomPanelPlaceholder.tsx  safe   never mounted ("coming soon" stub
                                     superseded by ChainPanel)
```

#### 2.1.3 Hooks — transitively dead

```
hooks/useCalendar.ts        safe   CalendarStrip only
hooks/useMonteCarlo.ts      safe   MonteCarloPanel only
hooks/useStrategyPayoff.ts  safe   BlackScholesPanel only
hooks/useModelSignals.ts    safe   ModelSignalsRow only
hooks/useSignal.ts          safe   SignalView only
hooks/useTickerMetrics.ts   safe   OptionsMetricsRow only
```

`hooks/useMarket.ts:useMarketIndices` — only consumed by
`components/layout/DashboardHeader.tsx`. The other export
`useMarketStatus` is live.

`hooks/useTickerDetail.ts` — **alive** (TradeDeskToolbar and
TradeEntryModal use it). Keep.

#### 2.1.4 Backend routers — only called by stranded frontend

All 12 routers are registered in `backend/main.py` lines 110‑121, but
the frontend's actual fetcher set is narrower. The following routers
have **zero live callers**:

| Router file              | Only called by         | LOC est. |
|--------------------------|------------------------|----------|
| `routers/calendar.py`    | CalendarStrip (dead)   | ~100     |
| `routers/bs.py`          | BlackScholesPanel (dead) | ~160   |
| `routers/mc.py`          | MonteCarloPanel (dead) | ~120     |
| `routers/models.py`      | ModelSignalsRow (dead) | ~600     |
| `routers/regime.py`      | nothing (no frontend caller) | ~80 |
| `routers/signal.py`      | SignalView (dead)      | ~300     |
| `routers/ticker.py` `/metrics` endpoint | OptionsMetricsRow (dead) | ~70 of 400 |

`routers/ticker.py` itself stays — `/detail`, `/bars`, `/chart` are
live. Only the `/metrics` route is dead.

#### 2.1.5 Comment‑only references in App.tsx (cosmetic)

`frontend/src/App.tsx:14‑21` — long comment block referencing
`DashboardPage / MarketPage / NewsPage / SignalPage`, `TopNavBar`,
`DashboardHeader`, `TickerTape`. Once the components are deleted the
comment should be trimmed.

---

### 2.2 Stranded‑value catalog (the "spotting" roadmap)

The retired Analysis dashboard computed a lot of high‑value analytics
that the new chart‑first product has stopped surfacing. The *math is
intact and the endpoints still respond*; only the UI consumer is gone.
Below is what's stranded and a concrete suggestion for re‑plumbing.

| Signal | Compute path | Backend status | Suggested resurface |
|---|---|---|---|
| **IV rank** | `calculations/iv_metrics.py:iv_percentile` (+ historical store) | live via `GET /api/ticker/{sym}/metrics` | Collapsible *Spotting* row above the chain, single 9px label + value. Honest about source (median ATM IV per day). |
| **VRP** (IV minus realized vol) | `calculations/iv_metrics.py:vrp` + `calculations/realized_vol.py` | live via same `/metrics` | Same Spotting row; pair with IV rank. |
| **25Δ skew** | `calculations/skew.py` | live via `/metrics` | Same row; useful for "is the market paying for downside?" |
| **P/C ratio** | `calculations/pc_ratio.py` (volumes from chain) | live via `/metrics` | Same row. |
| **Max pain** | `calculations/gamma_exposure.py:max_pain` | live via `/metrics` *and* as a chart annotation (currently dimmed) | Already on chart as MP line; keep. |
| **Call/put walls** | `calculations/gamma_exposure.py:largest_oi_strike` | live via `/api/ticker/{sym}/chart` annotations | Already on chart as CW/PW; keep. |
| **Gamma flip** | `calculations/gamma_exposure.py:gamma_flip` | live via chart annotations | Already on chart as GF; keep. |
| **Expected move band** | `calculations/expected_move.py` | live via chart annotations | Already on chart as EM±; keep. |
| **LSTM vol forecast** | `ml/lstm_vol.py` + `ml/train_lstm.py` | live via `/api/models/{sym}` (orphan) | Stretch: a tiny chip on the chart toolbar "LSTM σ +14%" when the model says next‑day vol is materially above realized. Defer until you have ground truth on whether the forecast is calibrated. |
| **CatBoost earnings model** | `ml/earnings_catboost.py` + `ml/train.py` | live via `/api/models/{sym}` | The Analytics page is the natural home — but only if a position is open on a name with earnings ≤ DTE. As a "context badge" rather than a chart overlay. |
| **RF regime** | `ml/baselines_trend.py` + `ml/ensemble.py` + `calculations/regime.py` | live via `/api/regime/{sym}` (zero callers anywhere) | Single‑word pill on the toolbar ("RISK‑ON / RISK‑OFF / NEUTRAL"). Don't overweight in the UI — these are forecasts, not facts. |
| **Vol Edge synthesis** | `calculations/vol_edge.py` + `calculations/signal_composer.py` | live via `/api/signal/{sym}` | This was the "verdict card" — overrated for 0DTE where decay dominates. Recommend retire, OR demote to a Settings‑gated experimental panel. |
| **Monte Carlo** | `calculations/monte_carlo.py` + `routers/mc.py` | live via `/api/mc/{sym}` | A modal/popover from a position's risk strip ("Show MC distribution") when the user wants probability bands. Don't make it default. |
| **Black‑Scholes payoff panel** | already on the journal panel via `compute_analytics` | live | Already wired into `/api/journal/trades/{id}/analytics`; the chart's BE overlay is the actionable distillation. Keep current setup, retire the standalone BS panel. |
| **Calendar (OPEX, FOMC, CPI, earnings strip)** | `calculations/calendar_dates.py` + `routers/calendar.py` | live | A thin pill row above the chart ("OPEX Fri · FOMC Wed · CPI Thu"). Cheap to add, high signal density. Worth doing next. |

Theme: most of these slot naturally into a **collapsible "Spotting"
row above the chain panel** that the user can hide. None of them belong
ON the chart itself except what's already there (the dimmed
EM/CW/PW/MP/GF lines).

---

### 2.3 Bugs & fragility

#### 2.3.1 [FIXED] Scheduler wedge — no per‑call timeouts

- **Where:** `services/alpaca_client.py` (frozen, audit only),
  `services/finnhub_client.py`, used by `jobs/refresh_watchlist.py`,
  `jobs/prewarm_hot_tickers.py`, `jobs/collect_options_chain.py`.
- **Severity:** HIGH (production stability).
- **Root cause:** `alpaca-py`'s `StockHistoricalDataClient`,
  `OptionHistoricalDataClient`, `TradingClient` accept no `timeout`
  parameter at construction; `finnhub.Client` exposes
  `DEFAULT_TIMEOUT = 10` but a single slow tick (10s × multiple
  symbols sequentially) still blows past the 60s scheduler interval.
  With `max_instances=1` and **no** `misfire_grace_time`, APScheduler
  silently stopped re‑firing.
- **Fix:** new `services/timeouts.py:run_with_timeout()`
  (ThreadPoolExecutor‑backed), wall‑clock budget in
  `refresh_watchlist`, per‑symbol timeout in `collect_options_chain`,
  `misfire_grace_time=30` on every scheduled job.
- See §3 — commit `a6caf34`.

#### 2.3.2 Other unguarded external calls (audit only)

- **`services/fred_client.py`** — already wraps `httpx.Client` with
  explicit `timeout=10/30/10s`. ✓
- **`services/yfinance_client.py`** — wraps every call in try/except
  per the docstring, but `yfinance` itself does not respect a global
  timeout; the calls happen via `pandas_datareader`‑style scraping.
  This file is only used by `scripts/backfill_earnings.py` (a manual
  one‑shot), not the scheduler — low priority.
- **`services/mock_flow.py`** — pure local computation, no I/O. ✓

#### 2.3.3 Stale‑cache risks (audit only)

- **`services/cache.py:TTLCache`** — single in‑memory dict, monotonic
  TTL. Safe; previously‑found rowid‑reuse bug in
  `routers/journal.py:get_trade_analytics` already includes
  `updated_at` + `entry_date` in the cache key (verified at lines
  271‑276). No analogous risk elsewhere — the other cache keys are
  all `(endpoint:symbol)` shaped and don't depend on database row
  identity.
- **`services/finnhub_client.py`** — caches news/earnings per symbol
  for 5 min. If the scheduler's `refresh_watchlist` skips a tick
  (now bounded to a single skip thanks to misfire_grace), the cache
  serves the prior payload up to 5 min, which is fine.
- **`services/alpaca_client.py:get_chain_snapshot`** — 5 min cache.
  During market hours that's longer than ideal for live trading, but
  acceptable for indicative pricing on this product.

#### 2.3.4 N+1 / sequential blocking patterns (audit only)

- **`jobs/refresh_watchlist.py`** still iterates symbols sequentially
  for both `company_news` and `get_option_chain_volumes`. Each call is
  blocking. With 15 symbols × 8s timeout, worst‑case a single tick can
  consume ~2 min of CPU time even after the timeout fix bounds
  scheduler stacking. **Recommendation:** convert these two loops to
  `asyncio.gather` + `asyncio.to_thread`, similar to how
  `prewarm_hot_tickers.py` does it. **Not done** — touching the job
  layer's concurrency model is beyond the "safe fix" gate.

- **`routers/ticker.py:get_ticker_chart`** still pulls both the chart
  bars and the full options chain in one request. The bars‑only
  fast path (`/bars`) was added previously, but the legacy `/chart`
  endpoint remains the slow one. Since only orphan code now calls the
  chain‑annotation endpoint internally (via prewarm), low priority.

#### 2.3.5 Race conditions (audit only)

- `stores/userSettings.ts` (new) uses zustand's `persist` middleware,
  which writes synchronously to localStorage on each `set()`. Safe.
- No other shared mutable state outside of zustand stores in the
  frontend.

---

### 2.4 Design vs DESIGN.md

The codebase is **substantially compliant** with DESIGN.md. Hex sweep
shows only canonical palette tokens. Tailwind class sweep shows
**no** `rounded-md/lg/xl/2xl/full`, **no** `shadow-*`, **no**
`font-bold/semibold/black`, **no** `gradient/bg-gradient`. Good.

| Issue | Where | Severity | Note |
|---|---|---|---|
| `BORDER STRONG` palette typo | DESIGN.md line 28 says `#2A2E38`; codebase uses `#2A2D36` | LOW | Likely an old palette commit; pick one and propagate. |
| `text-fg-tertiary` AA contrast (2.9:1) | DESIGN.md flags this as "decorative only", never body text. Spot‑check usage: `SettingsPage` help text is at 11px fg‑tertiary — DESIGN.md explicitly allows this for sub‑context lines but it's borderline. | LOW | Acceptable per the spec but worth eyeballing. |
| `LeftRail` icon labels at 9px fg‑secondary | Per DESIGN.md the micro/uppercase pattern is fine | OK | No action. |
| Hairline divider color consistency | All borders use the canonical `#1F222A` via Tailwind `border-hairline` class. ✓ | OK | No action. |

### 2.5 Data honesty

The codebase labels approximate / indicative data **consistently**:

- `routers/zerodte.py` chain table → `ChainTableOut.notice = "Paper · indicative pricing (approximate)"` + `indicative: true` flag
- `ChainTable.tsx` header → "indicative pricing" pill
- BS‑model fallback cells in the chain → dimmed text + `·m` marker
- `routers/ticker.py` chart annotations → `oi_source: "volume_proxy"` surfaces a footer when OI is unavailable
- `schemas/signal.py` + `routers/signal.py` → `is_mock` flag flows from `services/mock_flow.py`

| Risk | Where | Note |
|---|---|---|
| Watchlist staleness during long off‑hours not surfaced | `WatchlistColumn.tsx` shows a small "Markets closed — last snapshot HH:MM" banner when status is closed, but doesn't tell the user *how stale* the snapshot is | LOW. Add a "3 days ago" line if the snapshot age exceeds e.g. 24h. |
| Per‑contract IV not labeled as Alpaca‑provided vs back‑solved | The chain table reports a single `iv_used` for the whole window from the ATM solve; off‑ATM strikes are BS‑model‑priced against that single IV. Labeled at the cell level (the `·m` marker) but not at the IV header. | LOW. |

### 2.6 Code health

- **TODO/FIXME hits:** only two real ones —
  - `jobs/categories.py:164` — "TODO: Phase 3 — replace with proper
    historical‑baseline detection". This is the volume‑z‑score baseline
    for unusual options; the current placeholder is "vol > 1.5× yesterday".
    Live, low priority.
  - `components/positions/BottomPanelPlaceholder.tsx:26` — "coming
    soon" text in a dead component (see §2.1.2).
- **Duplicated patterns:** `_to_out(trade)` exists in both
  `routers/journal.py` and `routers/zerodte.py` (as `_trade_to_out`).
  The latter explicitly notes the duplication. Worth promoting to
  `models/trade.py` as a `Trade.to_out_dict()` method. **Recommended,
  not done.**
- **Type‑safety gaps:** none flagged by `tsc --noEmit` (clean).
  Python is typed throughout the routers/calculations; not all
  `services/*` use complete type hints but the gaps are at I/O
  boundaries where the SDK's own types are weakly typed.
- **Test coverage:** 196 backend tests, all pass. No frontend test
  framework wired (vite test or Vitest) — acceptable for a UI‑first
  prototype but a recommendation for the post‑MVP phase.

---

## 3. FIXED THIS RUN

| # | Change | Commit | Files |
|---|---|---|---|
| 2a | Scheduler timeouts + misfire | `a6caf34` | `+services/timeouts.py`, `~main.py`, `~jobs/refresh_watchlist.py`, `~jobs/collect_options_chain.py` |
| 2b | Spacing consistency (`px-4`→`px-3` on chain header) | `d4489b1` | `~components/positions/chain/ChainPanel.tsx` |
| 2c | Settings page wired (4 prefs) | `258787e` | `+stores/userSettings.ts`, `~pages/SettingsPage.tsx`, `~pages/PositionsPage.tsx`, `~components/positions/chain/ChainTable.tsx`, `~components/positions/TradeDeskToolbar.tsx` |

### 2a detail

**Before:** `refresh_watchlist` and `collect_options_chain` made
sequential blocking SDK calls with no per‑call deadline; a slow Alpaca
chain fetch could stall a tick past the 60s scheduler interval, and
APScheduler's defaults silently skipped re‑fires.

**After:**
- New `services/timeouts.py:run_with_timeout(fn, *a, timeout_s)` wraps
  SDK calls in a `ThreadPoolExecutor.submit().result(timeout=N)` so
  the scheduler thread is freed regardless of the SDK's internal state.
- `refresh_watchlist` now has a `_TICK_BUDGET_SECONDS = 45` wall‑clock
  budget, an 8s per‑call timeout, and a 15s timeout for the broader
  earnings calendar window. Partial data is persisted when the budget
  is exhausted (strictly better than letting the scheduler back up).
- `collect_options_chain` has a 20s per‑symbol timeout.
- All three jobs in `main.py` got `misfire_grace_time=30` so a missed
  slot fires once on recovery instead of being permanently dropped.

### 2b detail

Single‑line normalization: chain panel header `px-4` → `px-3` to match
the chart wrapper and other regions. The bigger UI polish items
referenced in the brief (sparse watchlist rows, dimmed chart
annotations, tight chain panel, rail icon offset, hairline dividers)
were already implemented in prior turns and are verified intact —
documented in the commit body so a reviewer doesn't go hunting.

### 2c detail

Settings page replaces the "coming soon" stub. Four preferences:

| Pref | Default | Wired to |
|---|---|---|
| Default ticker | SPY | `PositionsPage` cold‑open effect |
| Default contract qty | 1 | `ChainTable` cell click + `TradeDeskToolbar` straddle button |
| Annotations on by default | true | reuses existing `chartPrefs.showMarketAnnotations` (no duplicate store) |
| Default chart timeframe | 5D | `PositionsPage` initial `useState` |

UI follows DESIGN.md: hairline section rows, IBM Plex Mono on every
control, amber for active state, no rounded corners, no Save button —
changes persist immediately to `td:user-settings` in localStorage.

---

## 4. RECOMMENDED — NOT DONE

These are the items that fell outside the "safe fix" gate
(objective + bounded + verifiable by tsc/tests). Listed in roughly
descending value.

### 4.1 Remove the stranded Analysis dashboard

Approx. **2,500 frontend LOC + 1,200 backend LOC** of dead code is on
disk and registered. The full catalog is in §2.1. The sequence I'd
recommend:

1. **Confirm with the human** which orphan pages / hooks / routers can
   be deleted vs. cannibalized into the chart‑first product (see §2.2 —
   most have analytical value worth resurfacing in a different shape).
2. Delete in this order so each step builds cleanly:
   - Frontend: `BottomPanelPlaceholder.tsx`, `ModeToggle.tsx`,
     orphan hooks, orphan components/* (signal, modeling, layout/Top*,
     tradingview/), orphan pages.
   - Backend: `routers/regime.py` (zero callers anywhere) is the
     safest to drop first. Then `bs`/`mc`/`signal`/`models` once their
     frontend consumers are removed. `calendar` last (it's the
     cheapest to keep alive for a future calendar strip — see §4.2).
3. Trim App.tsx's explanatory comment.
4. Confirm `tsc --noEmit` and `pytest` both still pass at each step.

**Why not done in this run:** explicitly excluded by Operating Rule 6
("Do not delete code, even dead code, in this run — CATALOG it for
removal in the report. Deletion is a reviewed action, not an
unsupervised one").

### 4.2 Resurface 2–3 stranded signals into the chart‑first product

From §2.2, the highest‑value low‑risk pickups:

- **Calendar strip** — `calculations/calendar_dates.py` already
  computes OPEX / FOMC / CPI / earnings dates. A 24px row above the
  chart ("OPEX Fri 22d · FOMC Thu" in amber for "today/this week") is
  cheap and high signal.
- **IV rank + VRP + 25Δ skew + P/C** — collapsible "Spotting" strip
  above the chain (when a symbol is selected, before a position is
  open). 9px labels + tabular values, no decoration.
- **RF regime** — single pill on the toolbar, only when confidence is
  meaningfully not‑neutral.

**Why not done:** this is design work that should be reviewed live in
the UI; the right placement and density aren't decidable from code.

### 4.3 Concurrency in `refresh_watchlist`

§2.3.4 — convert the two sequential per‑symbol loops
(`company_news`, `get_option_chain_volumes`) to a bounded
`asyncio.gather` + `asyncio.to_thread` pattern, modeled on
`prewarm_hot_tickers`. Reduces wall time of a healthy tick from ~15s
to ~3s.

**Why not done:** touching the job's concurrency model is beyond the
"safe fix" line; the timeout fix in 2a already bounds the worst case.

### 4.4 Promote duplicated `_to_out` serializer

`routers/journal.py:_to_out` and `routers/zerodte.py:_trade_to_out`
return the same `TradeOut` shape from a `Trade` model. Promote to a
classmethod or module function under `schemas/journal.py`.

**Why not done:** small refactor, but `routers/zerodte.py` is on the
frozen list (the *entry mechanism* is frozen; the serializer arguably
isn't, but the rule says "if a fix seems to require touching them,
STOP and document").

### 4.5 Watchlist staleness indicator

§2.5 — when the watchlist snapshot age exceeds 24 h, the
"Markets closed — last snapshot HH:MM" banner should additionally
read e.g. "(3 days ago)". Cheap one‑line addition; left for review so
the exact threshold and copy is decided live.

### 4.6 DESIGN.md `BORDER STRONG` typo

§2.4 — DESIGN.md says `#2A2E38`, code uses `#2A2D36`. Choose one and
propagate. The code value renders fine; the doc value is one byte
off. **Not done** because deciding which is canonical is the human's
call.

### 4.7 `categories.py` historical baseline TODO

`jobs/categories.py:164` — the "1.5× yesterday volume" heuristic for
unusual_options should be replaced with a proper rolling baseline
once historical chain data exists in `models/options_snapshot.py`
(populated daily by `collect_options_chain.py`). Material accuracy
upgrade; defer until enough days of snapshots have accumulated.

### 4.8 Frontend test framework

No Vitest / Jest wired. Recommend adding before the codebase grows
much more, especially for the entry mechanism + chart overlay logic.

---

## 5. COULD NOT VERIFY

The audit was performed without a running UI or live‑trading
verification. The following items require human eyes/hands:

1. **Visual UI compliance** — that the watchlist rows actually look
   sparse, the chart annotations actually look dimmer, and the chain
   actually looks tight. I confirmed the code matches the spec
   (verified row heights, alpha values, padding tokens) but not the
   pixel result.
2. **Cold‑open behavior** — that the Settings `defaultTicker` /
   `defaultTimeframe` actually take effect on first reload of a new
   browser profile. Verified through code inspection only.
3. **Settings persistence after a reload** — localStorage write
   succeeds in code review; needs an in‑browser check.
4. **Live trading flow** — open a SPY straddle during market hours,
   confirm the UI shows the position drawn on the chart with the
   breakeven walking outward and the UPL going negative (long) or
   positive (short). The math is verified in‑process; the live wire
   needs a human.
5. **Scheduler recovery** — that, with `misfire_grace_time=30`, a
   pinned/slow tick recovers on the next 60s slot instead of being
   silently dropped. Needs a live server with monitorable logs over
   ~5 minutes; in‑process verification only proves the config is
   applied.
6. **Per‑call timeout behavior** — that
   `services/timeouts.run_with_timeout` actually fires `CallTimeout`
   on a stalled Alpaca call. Verified by unit reasoning; needs a real
   stall to confirm.
7. **Chain table for QQQ / IWM** — the allowlist allows SPY/QQQ/IWM
   but I've only seen SPY's chain populated in prior verification.
   Confirm QQQ and IWM 0DTE expiries are listed today.

---

## 6. DO FIRST WHEN YOU RETURN

A prioritized checklist to spend the first 15 minutes on:

1. **`uvicorn main:app --reload`** — confirm the lifespan returns in
   <2s (the asyncio + scheduler fixes from prior turns + 2a are now
   stacked). Watch the logs for any `CallTimeout` warnings — those
   are now expected behavior on slow ticks, not a regression.
2. **Open the dashboard, navigate to `/settings`** — change the
   default ticker to QQQ, save (auto‑persist), reload, confirm the
   chart cold‑opens to QQQ. Repeat for default timeframe.
3. **On `/positions`, click `+ BUY STRADDLE`** during market hours.
   Confirm the position appears, breakeven lines render in magenta,
   greeks/risk strip shows above the chart, UPL label rides on the BE
   line. (The whole purpose of this product working.)
4. **Eyeball the watchlist column** — no news subtitles, dense rows,
   green/red change pct on the right. Eyeball the chart — market‑
   structure annotation pills should be muted, not bold filled.
5. **Review the dead‑code catalog (§2.1)** and approve a deletion
   batch. Recommend starting with `BottomPanelPlaceholder` and
   `ModeToggle` (lowest risk), then the orphan pages, then the
   orphan backend routers.
6. **Read §2.2 (stranded‑value catalog)** and pick which 1–2 signals
   to resurface first. My recommendation: calendar strip + IV rank
   pill.
7. **DESIGN.md `BORDER STRONG`** — decide canonical value (#2A2E38
   vs #2A2D36) and update.

---

## Frozen‑file integrity

Snapshotted at session start, re‑hashed at finish:

```
b842f3b59c8ab3bcb14bcc98c92d30d31321f3f9bf5f929d4e41a8f48ef7d2d1  calculations/black_scholes.py
7e91c7798636785c7fd4005f23d49edf58030b081c7d3b71e701665cbccf4190  calculations/intraday_analytics.py
ab2cb9709681e960690c463f17cae0e2a5f9fc41b4c26dbb2686d27472331861  calculations/position_analytics.py
cde2512f45551ab431eb21d60863c839b2dba53ba78e4f08ecd6987ca8f361cf  routers/zerodte.py
747df313f078ca7e73356abf5629a0f93c6477278a2c048606a88a0221660733  services/alpaca_client.py
774a1de6129b76deb6fcadcf8aafafd5fb92d0345ca463a6e1e69266dbb21c96  services/market_calendar.py
```

(Compared at finish — see commit log "Final verify + frozen-file diff".)

---

## Files changed by section

```
2a (a6caf34):
  + backend/services/timeouts.py
  ~ backend/main.py
  ~ backend/jobs/refresh_watchlist.py
  ~ backend/jobs/collect_options_chain.py

2b (d4489b1):
  ~ frontend/src/components/positions/chain/ChainPanel.tsx

2c (258787e):
  + frontend/src/stores/userSettings.ts
  ~ frontend/src/pages/SettingsPage.tsx
  ~ frontend/src/pages/PositionsPage.tsx
  ~ frontend/src/components/positions/chain/ChainTable.tsx
  ~ frontend/src/components/positions/TradeDeskToolbar.tsx

audit (this report):
  + AUDIT_REPORT.md
```

196/196 backend tests pass at finish. `tsc --noEmit` clean at finish.
