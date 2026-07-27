# Trade Desk

**Trade Desk is a 0DTE options trading terminal and prop firm.** Traders pay for an evaluation combine (50K / 100K / 150K tiers), prove their edge under prop-firm risk rules (trailing maximum loss, daily loss limit), and get funded to trade firm capital. The differentiator: option positions are drawn directly on the price chart, with breakeven lines that walk in real time as theta decays.

It's the Topstep model — but for options instead of futures, with visual execution as the wedge.

---

## What this is

A single-trader desktop web app:

- A chart-first execution surface with the option chain on the right, the breakeven of any active position painted on the price axis in magenta, and an entry marker placed on the bar the trade fired.
- A combine-tier account model — three fixed sizes (50K / 100K / 150K) with industry-standard trailing-drawdown math (Topstep / Apex convention), a daily loss limit display, and a high-water-mark that walks the MLL up monotonically as the account grows.
- A real journal: every paper open, every close, full leg-level state, P&L attribution, calendar view, tags, notes, mistake vocabulary, thesis log, screenshot URL field, planned-exit field. Two CSV exports: the flat trade ledger and a per-execution fills report.
- Live intraday timeframes (1m / 5m / 15m / 1h / 4h / 1D) backed by Alpaca bars.
- A curated 30-symbol universe of liquid 0DTE-tradeable names — ETFs (SPY/QQQ/IWM/DIA) plus mega-cap tech, crypto-adjacent, and high-beta retail single names. The chain browses ANY listed expiration (term-structure visibility); opening remains strictly 0DTE.

**Execution mechanics** (trader-audit waves, 2026-07): market/limit/stop/stop-limit entries with DAY/GTC, atomic multi-leg structures with signed net-premium limits, resting close-limits (fill AT your price, passive side), one-click strike **rolls** (`/api/zerodte/roll`), per-leg closes (with copy-follower cascade), OCO pairing, trailing stops, premium-multiple TP/SL, draggable + right-clickable chart brackets, and an arm-to-confirm fat-finger layer (price-away, notional, duplicate-order). The order monitor runs on a 5s cadence; working SELL entries require a genuine two-sided live NBBO at fill time.

**Risk & margin**: a buying-power model gates every open — defined-risk structures require their max loss, naked short sides carry a Reg-T-style requirement — on top of the prop-firm floors (trailing MLL, daily loss limit, scaling cap). Expiration day force-flattens 0DTE books ~10 minutes before the bell (half-day aware) with a live countdown in the position panel.

**Decision support**: portfolio Greeks with SPY-beta-weighted delta, POP/prob-ITM pre-trade AND live on open positions, buying-power requirement shown before you fire, ATM IV term structure (contango/backwardation), per-contract IV on the ladder, a self-upgrading IV Rank (percentile → true 252-day rank as history accrues), payoff risk graphs on the multi-leg builder, and a pre-trade "what-if clock" that decays the T+0 curve toward the bell. Server-side price alerts fire with no tab open.

## What this is not

The repo started as a personal-use options research dashboard. Several things from that v1 spec were retired during the pivot and are not part of the current product:

- Not a research dashboard with five ML model cards (LSTM / CatBoost / RF / MLP / ensemble). The ML deps are still in `pyproject.toml` for backend signal endpoints (`/api/models/{symbol}`, `/api/signal/{symbol}`) but no trained artifacts ship, no card row is mounted in the active UI.
- Not a Monte Carlo strategy lab UI. The `/api/mc/{symbol}` route is alive and the math in `calculations/monte_carlo.py` is real, but the `<MonteCarloPanel />` lives in `frontend/src/components/modeling/` and is not routed.
- Not a news-organized watchlist front page. A `/watchlist` page is routed and the categorizer still exists, but the product surface a trader uses is `/positions`.
- Not a Black-Scholes strategy picker UI. The endpoints and math ship; the panel is in `frontend/src/components/modeling/` and is not routed.

The retired v1 README is preserved at [`docs/legacy/ORIGINAL_SPEC.md`](docs/legacy/ORIGINAL_SPEC.md).

---

## Tech stack

**Frontend** (`frontend/package.json`)
- React 18 + TypeScript, Vite build, Tailwind CSS
- `lightweight-charts` 5 for the candle + overlay rendering
- `@tanstack/react-query` for data fetching and cache
- `zustand` for client state (active position, selected ticker, trade ticket, preferences)
- `zod` for runtime API response validation
- `react-router-dom` 7 for routing

No `shadcn/ui`, no `lucide-react`, no `d3` — the v1 spec listed them but the live build doesn't use them. Star icons in the search modal are inline SVG; nothing else needs an icon library.

**Backend** (`backend/pyproject.toml`)
- Python 3.11+, FastAPI, Uvicorn, SQLAlchemy 2.x, SQLite (single file)
- `alpaca-py` for stock bars + chains + option-contract availability
- `finnhub-python` for earnings calendar + indices snapshots
- `yfinance` for historical-earnings backfill (one-shot, not request-path)
- `fredapi` via `httpx` for risk-free-rate (DGS3MO)
- `apscheduler` for cron jobs (watchlist refresh, chain collection, catalog refresh)
- `pandas` + `numpy` + `scipy` + `pandas-market-calendars`

**Tests:** pytest, ~1,100 backend + ~210 frontend (vitest). Pure-math, journal CRUD, account-state math, order-monitor fills/exits, margin requirements, roll/close-leg/close-limit lifecycles, probability metrics, chain/expiry resolution, admin surface.

## Trading-engine configuration

The knobs an operator actually tunes (all env-overridable via pydantic-settings, `backend/config.py`):

| Setting | Default | What it does |
| --- | --- | --- |
| `order_monitor_interval_s` | `5.0` | Seconds between trigger passes (working fills, brackets, trailing/premium exits, close-limits, liquidation). 5s is the floor for the polled data plane. |
| `margin_enforcement_enabled` | `true` | Buying-power gate on every open: defined-risk = max loss; naked sides = Reg-T-style. Off = legacy (no capital check). |
| `margin_naked_pct` / `margin_naked_min_pct` | `0.20` / `0.10` | Naked-requirement rates: pct·spot − OTM, floored at min_pct·spot (calls) / min_pct·strike (puts), + short premium. |
| `expiry_closeout_minutes` | `10.0` | Force-flatten 0DTE books this many minutes before the bell (half-day aware); pulls working orders on dying contracts. `0` disables. |
| `working_sell_fill_requires_quote` | `true` | A working SELL entry needs a genuine two-sided live NBBO at fill time (anti-exploitation); rests through cold ticks. |
| `zero_dte_universe` | `SPY,QQQ,IWM` | The openable symbols. Browsing/search covers the curated 30. |
| `per_contract_fee` | `0.69` | Simulated commission + regulatory fee, per contract per side. |
| `max_spot_staleness_s` | `300` | Refuse opens against an underlying print older than this (halt/illiquidity proxy). |

---

## Project structure

```
Trade Dashboard/
├── README.md                       # this file
├── docs/
│   └── legacy/
│       └── ORIGINAL_SPEC.md        # archived v1 README
│
├── backend/
│   ├── pyproject.toml
│   ├── main.py                     # FastAPI app + APScheduler lifespan
│   ├── config.py                   # pydantic-settings, env-driven
│   ├── database.py                 # engine + UTCDateTime decorator
│   │                                # init_db: create_all + additive migrate
│   │
│   ├── routers/
│   │   ├── account.py              # /api/account/state, /switch
│   │   ├── analytics.py            # /api/analytics — cross-trade summaries
│   │   ├── bs.py                   # /api/bs/strategy/{sym}/{type}, /payoff
│   │   ├── calendar.py             # /api/calendar — 7-day event strip
│   │   ├── journal.py              # /api/journal/trades CRUD + analytics
│   │   ├── market.py               # /api/market/{status,indices,liquid_universe,zerodte_universe}
│   │   ├── mc.py                   # /api/mc/{sym} — GBM terminal distribution
│   │   ├── models.py               # /api/models/{sym} — model signals
│   │   ├── regime.py               # /api/regime — current regime label
│   │   ├── signal.py               # /api/signal/{sym} — composite verdict
│   │   ├── ticker.py               # /api/ticker/{sym}/{detail,chart,bars,metrics}
│   │   ├── ticker_search.py        # /api/ticker/search — curated 30-symbol search
│   │   ├── user_browse.py          # /api/user/stars CRUD,
│   │   │                            # /api/ticker/popular, /api/ticker/selection
│   │   ├── watchlist.py            # /api/watchlist — 5 buckets
│   │   └── zerodte.py              # /api/zerodte/chain[/table] + paper open/mark
│   │
│   ├── services/
│   │   ├── account_tiers.py        # Tier dataclass + MLL math (50K/100K/150K)
│   │   ├── alpaca_client.py        # bars, snapshots, chain, contract availability
│   │   ├── cache.py                # in-memory TTL cache
│   │   ├── chain_availability.py   # bulk 0DTE-availability checks (5min TTL)
│   │   ├── curated_universe.py     # 30-symbol curated list + POPULAR_TICKERS
│   │   ├── finnhub_client.py
│   │   ├── fred_client.py          # risk-free rate (DGS3MO)
│   │   ├── market_calendar.py      # NYSE schedule
│   │   ├── symbol_catalog.py       # adapter on top of curated_universe
│   │   ├── ticker_analytics.py     # dormant algorithmic-popular aggregator
│   │   ├── timeouts.py             # per-call SDK timeout wrapper
│   │   ├── yfinance_client.py
│   │   └── calendar_constants.py
│   │
│   ├── calculations/                # pure functions; no I/O
│   │   ├── black_scholes.py
│   │   ├── calendar_dates.py
│   │   ├── expected_move.py
│   │   ├── gamma_exposure.py        # max_pain, gex_by_strike, gamma_flip
│   │   ├── intraday_analytics.py    # live P&L + Greeks for open positions
│   │   ├── iv_metrics.py            # iv_rank, iv_percentile, vrp
│   │   ├── journal_analytics.py     # closed-trade aggregates
│   │   ├── journal_calendar.py
│   │   ├── monte_carlo.py
│   │   ├── pc_ratio.py
│   │   ├── position_analytics.py    # multi-leg payoff + breakevens
│   │   ├── realized_vol.py
│   │   ├── regime.py
│   │   ├── signal_composer.py
│   │   ├── skew.py
│   │   ├── strategies.py            # leg templates
│   │   └── vol_edge.py
│   │
│   ├── jobs/                        # APScheduler targets
│   │   ├── categories.py            # watchlist 5-bucket builder
│   │   ├── collect_options_chain.py # cron 16:30 ET mon-fri
│   │   ├── prewarm_hot_tickers.py   # 60s interval
│   │   ├── refresh_watchlist.py     # 60s interval
│   │   └── seed_trades.py           # opt-in demo seeder
│   │
│   ├── models/                      # SQLAlchemy
│   │   ├── account_state.py         # active_tier + per-tier HWM
│   │   ├── historical_earnings_event.py
│   │   ├── options_snapshot.py
│   │   ├── ticker_selection.py      # selection log for popular feed
│   │   ├── trade.py                 # one row per opened trade
│   │   ├── user_star.py             # starred symbols
│   │   └── watchlist_item.py
│   │
│   ├── data/
│   │   └── dashboard.db             # gitignored
│   │
│   └── tests/                       # ~280 tests
│
└── frontend/
    ├── package.json
    ├── vite.config.ts
    ├── tailwind.config.js
    ├── index.html
    │
    └── src/
        ├── App.tsx                  # 5 routes; everything else redirects
        ├── main.tsx                 # QueryClient + StrictMode
        │
        ├── pages/
        │   ├── PositionsPage.tsx    # /positions  (default)
        │   ├── JournalPage.tsx      # /journal
        │   ├── AnalyticsPage.tsx    # /analytics
        │   ├── WatchlistPage.tsx    # /watchlist
        │   └── SettingsPage.tsx     # /settings
        │
        ├── components/
        │   ├── layout/RailShell.tsx
        │   ├── positions/
        │   │   ├── TradeDeskHeader.tsx       # 64px top bar (see Features)
        │   │   ├── TradeDeskToolbar.tsx      # timeframe ladder + mode toggle
        │   │   ├── ChartToolbar.tsx
        │   │   ├── BottomStrip.tsx           # 3-column bottom panel
        │   │   ├── SymbolSearchModal.tsx     # cmd-K modal (Stars / Popular / Search)
        │   │   ├── TickerSearchBox.tsx       # legacy dropdown, unmounted
        │   │   ├── TradeTicket.tsx
        │   │   ├── chain/ChainPanel.tsx
        │   │   ├── chain/ChainTable.tsx
        │   │   ├── chain/RightChain.tsx
        │   │   ├── chain/OpenPositionsList.tsx
        │   │   └── journal/
        │   │       ├── JournalPanel.tsx
        │   │       ├── PayoffPanel.tsx
        │   │       ├── ThetaScrubber.tsx
        │   │       ├── TradeEntryModal.tsx
        │   │       └── TradeList.tsx
        │   ├── stock/
        │   │   ├── AnnotatedChart.tsx        # lightweight-charts host
        │   │   ├── ChartLegend.tsx
        │   │   ├── PriceHeader.tsx
        │   │   └── …
        │   └── modeling/                     # on disk, not routed
        │       ├── BlackScholesPanel.tsx
        │       ├── MonteCarloPanel.tsx
        │       └── StrategyPicker.tsx
        │
        ├── hooks/                            # one per resource
        ├── stores/                           # 7 zustand stores
        ├── types/                            # 16 zod schema modules
        └── lib/
            ├── api.ts                        # typed fetcher; schema-validates
            ├── palette.js                    # color tokens (see Design system)
            ├── design.ts
            ├── formatters.ts
            └── tooltips.ts
```

---

## Quick start

```bash
# Backend
cd backend
uv sync                            # or: pip install -e .
cp .env.example .env               # see Environment variables below
uv run uvicorn main:app --port 8000 --reload

# Frontend (in another shell)
cd frontend
npm install
npm run dev                        # http://localhost:5173
```

Open <http://localhost:5173>; the wildcard route redirects to `/positions`.

### Environment variables

```bash
ALPACA_API_KEY=...
ALPACA_API_SECRET=...
ALPACA_PAPER=true
ALPACA_OPTIONS_FEED=indicative     # opra if you upgrade

FINNHUB_API_KEY=...
FRED_API_KEY=...

DATABASE_URL=sqlite:///./data/dashboard.db
LOG_LEVEL=INFO
SEED_TRADES=0                      # set 1 to load demo journal entries

# --- security / session ---
APP_ENV=development                # set "production" to harden defaults
COOKIE_SECURE=                     # blank → follows APP_ENV (Secure in prod,
                                   #         open in dev); set true/false to force
SESSION_TTL_DAYS=14                # session + cookie lifetime (was 30)
```

> **Cookie & session hardening.** The `td_session` cookie is `HttpOnly` +
> `SameSite=Lax` always. Its `Secure` flag is **prod-safe by default**: leave
> `COOKIE_SECURE` blank and it follows `APP_ENV` — `Secure` in production (the
> cookie is then never sent over plain HTTP, closing a downgrade/sidejacking
> hole) and open in development so local HTTP dev still works. An explicit
> `COOKIE_SECURE=true|false` always wins (e.g. force `true` behind a
> TLS-terminating proxy). The session lifetime is `SESSION_TTL_DAYS`, shortened
> from 30 to **14** to bound the blast radius of a stolen token while staying
> long enough that a daily-driver trader isn't re-logging-in constantly; it
> drives both the `auth_sessions` row expiry and the cookie `Max-Age`.

### Tests

```bash
cd backend && uv run pytest -q
```

One test in `test_chain_availability` is `network`-marked because it
reaches live Alpaca data and is environment-dependent. To run the
deterministic subset (what CI runs), deselect it:

```bash
cd backend && uv run pytest -q -m "not network"
```

### CI

GitHub Actions (`.github/workflows/ci.yml`) runs on every push and pull
request:

- **backend** — Python 3.11, installs `-e ".[dev]"`, runs
  `pytest -m "not network"` from `backend/`.
- **frontend** — Node 20, `npm ci`, then `tsc --noEmit` (typecheck) and
  `npm run build` from `frontend/`.

---

## Architecture

```
                        ┌──────────────────────────────┐
   Browser              │   FastAPI                    │
   (React + lightweight-│                              │
    charts)             │   GET  /api/account/state    │
       ▲                │   POST /api/account/state/switch
       │ REST + react-  │                              │
       │ query polling  │   GET  /api/ticker/{sym}/…   │
       ▼                │   GET  /api/journal/trades   │
                        │   GET  /api/zerodte/chain    │
                        │   GET  /api/ticker/popular   │
                        │   POST /api/user/stars/{sym} │
                        │   …                          │
                        │                              │
                        │   services/                  │── Alpaca (bars, chains, contracts)
                        │     alpaca_client            │── Finnhub (earnings, indices)
                        │     chain_availability       │── FRED (DGS3MO)
                        │     curated_universe         │
                        │     account_tiers            │
                        │                              │
                        │   calculations/  (pure)      │
                        │     black_scholes / mc /     │
                        │     position_analytics /     │
                        │     gamma_exposure / …       │
                        │                              │
                        │   SQLAlchemy → SQLite        │
                        │     trades / account_state / │
                        │     watchlist_items /        │
                        │     user_stars / …           │
                        │                              │
                        │   APScheduler                │
                        │     refresh_watchlist  60s   │
                        │     prewarm_hot_tickers 60s  │
                        │     collect_options_chain    │
                        │       cron 16:30 ET M-F      │
                        │     symbol_catalog.refresh   │
                        │       cron 09:35 ET M-F      │
                        └──────────────────────────────┘
```

**Why this shape**

- Single FastAPI process keeps deploy and debug simple. SQLite is fine for a single-tenant desktop product.
- The frontend never holds long-lived market data — it polls react-query at 5s on hot endpoints, and react-query handles dedup, staleness, and background refetch.
- All "today" boundary math goes through ET (`America/New_York`), not UTC — closed trades, DLL reset, market sessions. This catches what would otherwise be off-by-one-day bugs around midnight UTC.
- Pure math lives in `calculations/`; nothing there touches the network or the DB. Services own I/O. Routers are thin Pydantic-typed adapters.

---

## Key features

### Combine tier system

Three fixed prop-firm-style combines, no customization (matches the real industry products: Topstep / Apex / Tradeify).

| Tier  | Starting balance | Trailing distance | Initial MLL | DLL  |
|-------|------------------|-------------------|-------------|------|
| 50K   | $50,000          | $2,000            | $48,000     | $1,500 |
| 100K  | $100,000         | $4,000            | $96,000     | $3,000 |
| 150K  | $150,000         | $4,500            | $145,500    | $4,500 |

- **MLL (Maximum Loss Limit)**: trails the account's high-water mark by the tier's trailing distance and is **capped at the starting balance** (Topstep rule). Implemented in `services/account_tiers.compute_mll`. The HWM is monotonic per tier — switching tiers preserves each tier's progress independently.
- **DLL (Daily Loss Limit)**: per-tier daily floor that resets at the **5pm-PT** trading-day boundary (the settlement clock the whole app uses). ~3% of starting balance, configurable per tier in Settings within a 1–10% band, with per-tier enforcement modes (`alert` / `liquidate` / `liquidate_block`) and an optional off toggle. Backend computes `dll_used` as the realized loss across trades closed in the current trading day; the frontend folds in any active position's negative UPL before painting the pill. **Enforced**: once realized day-loss exhausts the budget the account is day-locked and the open book is flattened (`services/order_monitor`).

Switching tiers preserves the HWM of the tier you're leaving and clears the active position so cross-tier P&L can't contaminate the new tier's pill.

### Persistent header (`TradeDeskHeader.tsx`)

64px top bar, always visible:

```
[50K COMBINE ▾]  [⌕ SPY · search ticker…  /]   SPY $756.16  +$1.98  (+0.26%)
                                          BAL · MLL · DLL · RP&L · UP&L · MKT
```

- **BAL**: realized P&L on the active tier + active-position UPL.
- **MLL**: trailing floor; turns warning amber, then bear-red as cushion shrinks, then shows "BREACH" badge when BAL < MLL.
- **DLL**: today's used loss / budget. Same color ladder: fg-primary < 50%, warning 50–90%, bear-red 90–100%, bright bear-red + "DLL HIT" badge > 100%.
- **RP&L**: realized P&L for today.
- **UP&L**: unrealized P&L on the currently-selected open position.
- **MKT**: open / closed banner with "until 09:30 ET" countdown.

### Visual 0DTE execution

When a paper trade is opened, the chart picks up three overlays:

1. An **entry marker** (arrow + label "ENTRY · Long call") anchored to the bar where the trade fired.
2. **Magenta breakeven price-line(s)** at the position's current breakeven(s). The line label shows the live UPL ("BE −$18.06") so the line *is* the P&L readout.
3. A theta scrubber under the chart that lets you simulate the position's value at a future DTE without changing market data.

The overlays survive timeframe switches (1m → 5m → 15m → 1h → 4h → 1D) by reading from refs in the bars-effect rather than tearing down on every series rebuild. They also survive pan and zoom by binding to price values, not screen pixels.

### Symbol search modal (`SymbolSearchModal.tsx`)

Opens via `/` or `⌘K` from anywhere. Three sections, top to bottom:

- **STARRED** — server-persisted favorites (only shown when non-empty).
- **POPULAR** — 8 curated tickers from `/api/ticker/popular`; each row carries a live "0DTE TODAY" amber badge when an Alpaca contract is listed for today.
- **SEARCH RESULTS** — appears under the other two when the user types; ranks substring matches over the 30-symbol curated universe (exact → prefix → substring → name-substring).

Each row has an inline star toggle (optimistic; flips on click without round-trip lag). Picking a row closes the modal and fires `POST /api/ticker/selection` — fire-and-forget logging that feeds a dormant algorithmic-popular aggregator at `services/ticker_analytics.get_popular_tickers`.

### Real intraday timeframes

`/api/ticker/{sym}/bars?timeframe=1m|5m|15m|1h|4h|1D` — backed directly by Alpaca's bars endpoint. Lookback windows are tuned per-timeframe to keep responses bounded.

### Trade journal + analytics

- `POST /api/journal/trades` opens a paper trade with arbitrary leg shapes (long call, long put, long straddle, etc. — templates in `calculations/strategies.py`).
- Each trade carries leg-level state, entry-underlying-price, tier, tags, mistake tags, confidence, thesis, planned exit, risk amount, screenshot URL, review note.
- `/api/journal/trades/{id}/analytics` returns live UPL, Greeks, breakevens-today, breakevens-at-expiration, max loss, max gain, payoff curve.
- The `/journal` page renders a calendar view (month / week / day) of closed trades; the `/analytics` page rolls them up across the active tier.

### Settings page

- **Combine tier** picker (with switch confirmation — preserves per-tier HWM).
- **Daily loss limit** per-tier override (1–10% of starting balance, "reset to default" link).
- **Default ticker** (the symbol the chart cold-opens to; restricted to the 0DTE-eligible allowlist).
- **Default contract quantity** for new opens.
- **Default chart timeframe**.
- **Market-structure annotations** toggle (EM±, walls, max-pain, gamma flip).
- **Chart appearance**: bullish/bearish colors, background-gradient toggle, grid-opacity slider.

Most settings apply live; default-ticker and default-timeframe take effect on next reload.

---

## Data layer

**Alpaca (free tier)** — primary data source.

- **Stock bars**: real OHLCV across the 1m / 5m / 15m / 1h / 4h / 1D ladder.
- **Option contracts**: used for the 0DTE-availability badge (one tiny call per symbol per 5min cache window, ~30 calls/day for the curated set).
- **Option chains**: indicative feed. IV and Greeks for ~60% of contracts; **zero open interest** across the chain. Per-contract daily volume is fetched separately and substituted for OI in the OI-dependent calcs (max-pain, walls, GEX). The chart response carries `oi_source: "volume_proxy" | "open_interest"` so the UI labels data quality honestly.
- **~15-minute SIP delay** on equity bars. Visible everywhere; the price readout doesn't claim live.

**Finnhub** — earnings calendar + indices snapshots. Per-article sentiment is paid-tier-only and not used.

**FRED** — risk-free rate via DGS3MO for Black-Scholes pricing.

**yfinance** — one-shot historical earnings backfill (`historical_earnings_event` table). Not on the request path.

---

## Core calculations

Pure functions under `backend/calculations/`. Each is unit-tested.

| File | What it does |
|---|---|
| `expected_move.py` | ATM-straddle expected move + bands, ATM-strike picker. |
| `gamma_exposure.py` | `max_pain`, `gex_by_strike` (dealer-short-calls / long-puts sign convention), `gamma_flip`. The chart router restricts the GEX input to strikes within ±20% of spot before calling `gamma_flip` — without the window the volume-as-OI proxy makes deep-OTM strikes dominate the cumulative walk. |
| `iv_metrics.py` | `iv_rank`, `iv_percentile`, `vrp`. |
| `realized_vol.py` | Annualized RV from log returns. |
| `skew.py` | 25-delta put–call IV skew. |
| `pc_ratio.py` | Today's put / call volume. |
| `monte_carlo.py` | GBM terminal distribution + percentiles (exposed via `/api/mc/{sym}`; not surfaced in the live UI). |
| `black_scholes.py` | Call/put pricing + Greeks (Δ/Γ/Θ/V). Used by the position-analytics path. |
| `position_analytics.py` | Multi-leg payoff curve + breakevens. Drives the magenta on-chart breakeven lines. |
| `intraday_analytics.py` | Live UPL + Greeks for an open position, accepting a DTE override for the theta scrubber. |
| `journal_analytics.py` | Closed-trade rollups. |
| `journal_calendar.py` | Month / week / day grid builders. |
| `regime.py` | Deterministic 3-label market-regime classifier. |
| `vol_edge.py` | "Overpriced / fair / underpriced" vol regime tag. |
| `signal_composer.py` | Combines model outputs into a composite verdict. |
| `strategies.py` | Leg templates (long_call / long_put / long_straddle / vertical / iron_condor / …). |

The `account_tiers.py` math (`compute_mll`, `compute_balance`, `update_hwm`, plus the DLL aggregator in `routers/account.py`) sits in `services/` because it touches per-tier state, not just market data.

---

## Design system

Dark-tiered **monochrome** (black & white chrome; color reserved for money — green gains / red losses). The earlier navy+amber and electric-cyan themes were retired. Tokens in [`frontend/src/lib/palette.js`](frontend/src/lib/palette.js) (with a TypeScript declaration at `palette.d.ts`) — the palette file is the source of truth for color.

**Surface tiers** (depth)
```
bgTier0  #131722   page background
bgTier1  #1A1F2D   panels
bgTier2  #222837   cards
bgTier3  #2A3142   active row / focused control
```

**Text tiers**
```
fgPrimary    #E8E8E0   primary numbers
fgSecondary  …        labels
fgTertiary   …        meta
fgDisabled   …        muted
```

**Status / accents**
```
bullish        #4DD17C    up bars, profitable P&L
bearish        #E85C5C    down bars, losing P&L
positionMagenta #D946EF   user-position overlay (entry marker + BE line)
accentAmber    #F0A030    active / selected only — never decoration
warning        #C97A3A    DLL / MLL approach
actionBuy      #2A8C4A
actionSell     #C8434A
```

Typography is **IBM Plex Mono** everywhere — money, percentages, time, symbols. Tabular numerals on every numeric field so columns line up across the page. The visual idiom is "Bloomberg / Topstep terminal" rather than "consumer chart app".

`DESIGN.md` at the repo root carries the longer-form rationale (component sizes, hairline conventions, etc.).

---

## Known limitations

These are the truthful gaps; they're not embarrassments but they shape what the product can claim.

- **Alpaca indicative feed**: ~15 min SIP delay on equity bars; option chain has IV + Greeks but no open interest. We substitute per-contract daily volume for OI in OI-dependent calcs and label `oi_source` in the response. Upgrading to Algo Trader Plus would flip this off automatically.
- **Indices unavailable**: SPX, NDX, RUT, VIX, DJX, OEX are cash-settled CBOE products with no Alpaca bars and no free-tier chain. They're filtered out of search + curated universe + popular slate; a defense-in-depth denylist in `services/symbol_catalog._INDEX_DENYLIST` catches them even if they ever drifted into the curated list.
- **30-symbol search universe**: the prior 13K-symbol live Alpaca catalog was retired because 0DTE liquidity drops off a cliff outside this set. Expanding will be revisited once we have selection data telling us which symbols are actually getting picked.
- **Drawing tools on the chart**: not implemented. A TradingView Lightweight Charts swap was attempted to inherit their drawing toolbar; the free TV widget doesn't expose price-axis coordinates to host code, so the swap was reverted. The on-disk artifact `screenshots/tradingview_phase1_attempt.png` is evidence of the exploration, not a live build.
- **No real OPRA**: paper trades only. The whole product is honest about being a paper terminal; profit targets, the funded stage, and the payout flow are all simulated on top of the indicative feed.
- **Simulated payments**: the combine purchase / activation / reset / monthly-renewal money is simulated. A Stripe webhook + checkout path exists on the backend (signature-verified, idempotent) but the default purchase flow is the free placeholder — real charging is not wired on the frontend.
- **No ML signals**: an earlier draft aspired to model-driven signals (LSTM vol forecast, GBM stacking). That was never wired up — no routes, no code imports, no trained artifacts shipped — so the heavyweight ML deps (`torch`, `catboost`, `scikit-learn`, `pyarrow`) that were declared for it have been removed. The pure-math options analytics (`calculations/`, on `numpy`/`scipy`) are the live signal layer.

> **Enforcement, multi-user, and payouts now SHIP** (they were listed as gaps in earlier drafts of this README): the trade-open path is gated against the MLL/DLL/scaling-cap/day-lock (`services/order_monitor` auto-liquidates at the floor; `routers/zerodte._require_tradeable`); auth + sessions are real (`routers/auth`, per-user scoping throughout); and the funded stage + payout request/review desk are live (`routers/combines`, `jobs/settle_combines`). See the [Rules & enforcement](#) sections above.

Historical verification artifacts for individual features live under [`docs/legacy/`](docs/legacy/).

---

## Roadmap

In rough order of priority for the full prop-firm product:

1. **Real OPRA pricing** — upgrade the Alpaca tier or wire ORATS for chains; flip the volume-as-OI proxy off when real OI lands.
2. **Real payments** — wire the existing Stripe checkout/webhook path into the frontend purchase flow so the (currently simulated) combine/activation/reset/renewal charges are real.
3. **Email infrastructure** — forgot-password reset + email verification (change-password already ships; a sender is the missing piece).
4. **Drawing tools on the chart** — horizontal levels, trendlines, ranges. Needs to live inside the lightweight-charts coordinate space, not a wrapper iframe.
5. **Expanded ticker universe** — driven by what `ticker_selections` actually shows users picking; the algorithmic-popular feed flips on when there's enough signal.
6. **Real-time stream over WS** — replace the 5s react-query polling on hot endpoints. Lower priority while we're on indicative.

> Profit targets, minimum trading days, DLL/MLL enforcement, the funded stage, the payout desk, and multi-user auth have all shipped and are no longer roadmap items.

---

## Attribution

- Price chart and overlay rendering: [TradingView Lightweight Charts](https://www.tradingview.com/lightweight-charts/) (Apache-2.0). The on-chart watermark is disabled in favor of this notice.
- Typography: [IBM Plex Mono](https://www.ibm.com/plex/) (SIL Open Font License).

---

*Not investment advice. Paper terminal; not connected to a live OPRA feed.*
