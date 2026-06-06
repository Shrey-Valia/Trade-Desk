> **Archived v1 spec.** This document describes the original product vision — a personal-use options research dashboard with ML signals, Monte Carlo, news watchlist, and a calendar strip. The product has since pivoted to a 0DTE options prop firm with visual execution. See the current [`README.md`](../../README.md) for what's actually shipped today. This file is kept for historical context and to source any motivating math/specs that survived the pivot.

---

# Options Trading Dashboard

A personal-use options trading dashboard with a news-organized watchlist, real-time options metrics, ML-driven signals, Monte Carlo simulation, Black-Scholes payoff modeling, and a trading calendar. Built for $0/month using free API tiers.

---

## Table of Contents

1. [Vision](#vision)
2. [Tech Stack](#tech-stack)
3. [Project Structure](#project-structure)
4. [Quick Start](#quick-start)
5. [Environment Variables](#environment-variables)
6. [Architecture](#architecture)
7. [Features (Detailed Specs)](#features-detailed-specs)
8. [Data Layer](#data-layer)
9. [ML Models](#ml-models)
10. [Core Calculations](#core-calculations)
11. [Visual Design System](#visual-design-system)
12. [Implementation Phases](#implementation-phases)
13. [Testing](#testing)
14. [Known Limitations](#known-limitations)
15. [Roadmap](#roadmap)
16. [Glossary](#glossary)

---

## Vision

This dashboard surfaces what serious options traders need to see — but can't easily get without paying $200–600/month across SpotGamma, Tastytrade, Unusual Whales, and Bloomberg.

**Core principles:**

- **News drives the watchlist.** Instead of curating a static ticker list, the watchlist surfaces names because something is happening to them (earnings, unusual options flow, breaking news, sentiment shifts).
- **The chart shows what options traders actually care about.** Expected move bands, max pain, dealer gamma flip levels, call/put walls — directly annotated on the chart.
- **Quantified model outputs replace gut feel.** LSTM forecasts realized vol. CatBoost predicts earnings moves. Random Forest classifies regime. MLP biases trend direction. An ensemble combines them into a single edge score.
- **Probability and payoff in one screen.** Monte Carlo simulates where the stock could go; Black-Scholes prices the exact trade you'd put on.
- **Calendar contextualizes everything.** Every metric on the screen exists because of upcoming events — earnings, Fed meetings, CPI prints.

**Non-goals:**

- Not building a SaaS or product to sell. Personal-use only.
- Not building a low-latency execution platform. Swing/positional options trading, not scalping.
- Not building an order book / L2 visualization (that's Bookmap's territory and requires expensive data).

---

## Tech Stack

### Frontend

- **React 18** + **TypeScript** — component model, type safety
- **Vite** — fast dev server and build
- **Tailwind CSS** — styling
- **shadcn/ui** — component primitives (buttons, cards, dropdowns)
- **D3.js** — for custom annotated charts (or fallback to Recharts for simpler ones)
- **Zustand** — lightweight state management
- **TanStack Query** (React Query) — data fetching, caching, revalidation
- **Lucide React** — icons

### Backend

- **Python 3.11+**
- **FastAPI** — REST API + WebSocket support
- **Uvicorn** — ASGI server
- **SQLAlchemy** — ORM for SQLite
- **SQLite** — local storage (file-based, zero-config)
- **Pandas** + **NumPy** — data manipulation
- **APScheduler** — cron-style scheduled tasks (refresh data, retrain models)

### ML Stack

- **scikit-learn** — Random Forest, MLP, preprocessing
- **CatBoost** — gradient boosting (earnings moves)
- **PyTorch** — LSTM (vol forecasting)
- **Joblib** — model persistence

### Data Sources (all free tiers)

- **Alpaca** — stocks + options chains (indicative feed on free tier)
- **Finnhub** — news, earnings calendar, social sentiment
- **FRED** — economic calendar, FOMC dates, macro releases
- **Reddit** (optional) — retail sentiment

---

## Project Structure

The tree below reflects what's actually shipped through Phase 3. Files
prefixed with `# planned` exist in the spec but haven't been built yet.

```
options-dashboard/
├── README.md
├── .env.example
├── .gitignore
│
├── backend/
│   ├── pyproject.toml              # uv-managed deps + dev extras
│   ├── main.py                     # FastAPI app + APScheduler lifespan
│   ├── config.py                   # pydantic-settings; hardcoded universe
│   ├── database.py                 # engine + UTCDateTime TypeDecorator
│   │
│   ├── routers/
│   │   ├── watchlist.py            # GET /api/watchlist
│   │   └── ticker.py               # /api/ticker/{symbol}/{detail,chart,metrics}
│   │   # planned: calendar.py, news.py, models.py, monte_carlo.py, black_scholes.py
│   │
│   ├── services/
│   │   ├── alpaca_client.py        # snapshots, year bars, chain snapshot, get_bars(timeframe)
│   │   ├── finnhub_client.py       # company_news, earnings_calendar, next_earnings_for
│   │   ├── cache.py                # in-memory TTL cache (caches successes AND misses)
│   │   └── market_calendar.py      # NYSE schedule via pandas_market_calendars
│   │   # planned: fred_client.py, reddit_client.py
│   │
│   ├── calculations/               # all pure functions; ContractRow-based
│   │   ├── types.py                # ContractRow dataclass
│   │   ├── iv_metrics.py           # iv_rank, iv_percentile, vrp
│   │   ├── realized_vol.py
│   │   ├── expected_move.py        # straddle, bands, ATM picker
│   │   ├── gamma_exposure.py       # max_pain, gex_by_strike, gamma_flip, largest_oi_strike
│   │   ├── skew.py                 # 25Δ skew
│   │   └── pc_ratio.py
│   │   # planned: monte_carlo.py, black_scholes.py
│   │
│   ├── jobs/
│   │   ├── refresh_watchlist.py    # every 60s during market hours
│   │   ├── categories.py           # pure category builders (5 categories)
│   │   └── collect_options_chain.py # cron 16:30 ET Mon-Fri (NYSE-gated)
│   │   # planned: refresh_news.py, refresh_calendar.py, retrain_models.py
│   │
│   ├── models/                     # SQLAlchemy models
│   │   ├── watchlist_item.py
│   │   └── options_snapshot.py
│   │   # planned: news_item.py, calendar_event.py, model_signal.py
│   │
│   ├── schemas/                    # Pydantic response models
│   │   ├── watchlist.py
│   │   └── ticker.py               # TickerDetailOut, ChartResponse, MetricsResponse
│   │
│   └── tests/
│       └── test_calculations.py    # 21 tests, pure-function coverage
│
├── frontend/
│   ├── package.json
│   ├── vite.config.ts              # /api proxied to localhost:8000
│   ├── tailwind.config.js
│   ├── postcss.config.js
│   ├── tsconfig.json
│   ├── index.html
│   │
│   └── src/
│       ├── main.tsx                # QueryClient + StrictMode
│       ├── App.tsx
│       ├── index.css
│       │
│       ├── components/
│       │   ├── watchlist/
│       │   │   ├── WatchlistColumn.tsx
│       │   │   ├── WatchlistCategory.tsx
│       │   │   └── WatchlistItem.tsx
│       │   │
│       │   └── stock/
│       │       ├── StockDetailView.tsx        # right-panel wrapper + hydration gate
│       │       ├── PriceHeader.tsx
│       │       ├── AnnotatedChart.tsx         # pure SVG, no charting library
│       │       ├── OptionsMetricsRow.tsx
│       │       └── MetricCard.tsx             # reusable stat card
│       │   # planned: layout/{Header,CalendarStrip}, ModelSignalsRow, NewsForTicker,
│       │   #          modeling/{MonteCarloPanel,BlackScholesPanel,StrategyPicker}
│       │
│       ├── hooks/
│       │   ├── useWatchlist.ts
│       │   ├── useTickerDetail.ts
│       │   ├── useTickerChart.ts
│       │   └── useTickerMetrics.ts
│       │   # planned: useCalendar.ts, useWebSocket.ts
│       │
│       ├── stores/
│       │   └── selectedTicker.ts              # Zustand + persist + hydration hook
│       │
│       ├── lib/
│       │   ├── api.ts
│       │   ├── formatters.ts                  # Intl-based currency/percent/volume
│       │   └── design.ts
│       │
│       └── types/                             # zod schemas + inferred TS types
│           ├── watchlist.ts
│           ├── ticker.ts
│           ├── chart.ts
│           └── metrics.ts
│
└── data/                       # gitignored
    └── dashboard.db            # SQLite (watchlist_items + options_snapshots)
    # planned: historical_chains/, models/
```

---

## Quick Start

### Prerequisites

- Python 3.11+
- Node.js 20+
- An Alpaca account (you have this already)
- Finnhub API key (free)
- FRED API key (free)

### Install

```bash
# Clone and enter
git clone <your-repo> options-dashboard
cd options-dashboard

# Backend
cd backend
pip install -e .
cp .env.example .env
# fill in API keys in .env

# Frontend
cd ../frontend
npm install
```

### Run

```bash
# Terminal 1 — backend
cd backend
uvicorn main:app --reload --port 8000

# Terminal 2 — frontend
cd frontend
npm run dev

# Open browser at http://localhost:5173
```

---

## Environment Variables

Copy `.env.example` to `.env` and fill in:

```bash
# Alpaca
ALPACA_API_KEY=your_key_here
ALPACA_API_SECRET=your_secret_here
ALPACA_PAPER=true                # use paper trading endpoints
ALPACA_OPTIONS_FEED=indicative   # free tier; "opra" if you upgrade

# Finnhub
FINNHUB_API_KEY=your_key_here

# FRED
FRED_API_KEY=your_key_here

# Optional
REDDIT_CLIENT_ID=
REDDIT_CLIENT_SECRET=
REDDIT_USER_AGENT=options-dashboard/0.1

# App config
DATABASE_URL=sqlite:///./data/dashboard.db
LOG_LEVEL=INFO
```

---

## Architecture

```
                    ┌───────────────────────────┐
                    │   FastAPI Backend         │
                    │                           │
   Browser ◄─REST──►│   /api/watchlist          │
   (React)          │   /api/ticker/{symbol}    │
        ▲           │   /api/calendar           │
        │           │   /api/mc/{symbol}        │
        └──WS───────►   /api/bs/{strategy}      │
                    │                           │
                    │   ┌───────────────────┐   │
                    │   │  Service layer    │   │
                    │   │  - Alpaca         │───┼──► Alpaca API
                    │   │  - Finnhub        │───┼──► Finnhub API
                    │   │  - FRED           │───┼──► FRED API
                    │   └───────────────────┘   │
                    │                           │
                    │   ┌───────────────────┐   │
                    │   │  Calculations     │   │
                    │   │  - IV metrics     │   │
                    │   │  - Gamma exposure │   │
                    │   │  - Monte Carlo    │   │
                    │   │  - Black-Scholes  │   │
                    │   └───────────────────┘   │
                    │                           │
                    │   ┌───────────────────┐   │
                    │   │  ML inference     │   │
                    │   │  (load + predict) │   │
                    │   └───────────────────┘   │
                    │                           │
                    │   ┌───────────────────┐   │
                    │   │  SQLite           │   │
                    │   │  - cache          │   │
                    │   │  - history        │   │
                    │   │  - models         │   │
                    │   └───────────────────┘   │
                    └───────────────────────────┘

   Scheduled jobs (APScheduler in same process):
   - refresh_watchlist:    every 60s during market hours
   - refresh_news:         every 30s during market hours
   - refresh_calendar:     daily at 6am ET
   - collect_chains:       daily at 4:30pm ET (after close)
   - retrain_models:       weekly Sunday
```

**Why this architecture:**

- Single Python process for backend simplifies deployment and debugging
- WebSockets push real-time updates to frontend without polling
- SQLite is the right choice for personal use — zero config, single file
- Scheduled jobs collect historical chain data daily, which builds your own dataset over time for ML training

---

## Features (Detailed Specs)

### 1. News-Organized Watchlist

**Purpose:** Surface 10–20 tickers worth attention today, organized by *why* they're interesting rather than as a static list.

**Categories (as actually shipped):**

1. **🔥 Hot Now** — names with elevated news volume + price movement
   - Trigger: ≥3 Finnhub `company_news` items in the last hour OR absolute day-change ≥ 2%
   - Subtitle: most recent headline truncated to 5 words; falls back to `±X.XX% today` when no headline
   - Sort: news count desc, then |change| desc

2. **📅 Earnings ≤5d** — universe tickers reporting in the next 5 calendar days (ET)
   - Source: cached Finnhub `earnings_calendar` (fetched 30 days forward; the same payload also serves the price-header ER badge)
   - Display: ticker, day-of-week + BMO/AMC suffix (e.g. "Wed AMC")
   - Sort: by date ascending

3. **⚡ Unusual Options — call/put imbalance proxy** *(Phase 1 simplification)*
   - Trigger: today's call vs put volume ratio ≥ 1.5 with min total volume ≥ 1000
   - Subtitle: `Calls 2.4× puts` or `Puts 3.1× calls`
   - Sort: by ratio descending
   - **Why a proxy:** the canonical "≥3× 20-day average" detection needs historical chain volume that we only started collecting via `collect_options_chain` going forward. The imbalance proxy populates the category meaningfully today and gets replaced once we have ~20 days of `options_snapshots` history. Marked with `# TODO: Phase 3` in `jobs/categories.py`.

4. **📈 Sentiment Up** / **📉 Sentiment Down** — *placeholder, free-tier limitation*
   - Both categories return empty arrays plus a `notes` entry: `"Sentiment unavailable on free tier"`
   - Finnhub's `stock_social_sentiment` and `news_sentiment` endpoints are paid-tier only (403 on free key); free-tier `company_news` returns articles without per-article sentiment scores. To be wired to Stocktwits or another free source in a later phase.

**Data flow:**

- `jobs/refresh_watchlist.py` runs every 60s during NYSE hours (`pandas_market_calendars` gate; skips holidays + half-days)
- Per-ticker fetches isolated in try/except — one bad ticker can't kill the cycle
- Finnhub calls spaced 0.3s apart inside `services/finnhub_client.py` to avoid bursting the 60-calls/min limit
- Computed categories upserted into `watchlist_items` table (full delete + insert)
- Frontend `useWatchlist` polls `/api/watchlist` every 30s (TanStack Query). WebSocket push is Phase 8.

**UI layout:**

- Left sidebar, 168px wide
- Each category has a colored header icon + label
- Items show: ticker (bold), subtitle (small, gray), % change (right-aligned, green/red)
- Currently selected ticker has a 2px left border in primary color and a slightly darker background

**API contract:**

```typescript
GET /api/watchlist
Response: {
  hot_now: WatchlistItem[],
  earnings: WatchlistItem[],
  unusual_options: WatchlistItem[],
  sentiment_up: WatchlistItem[],
  sentiment_down: WatchlistItem[],
  updated_at: string
}

interface WatchlistItem {
  symbol: string;
  price: number;
  change_pct: number;
  subtitle: string;
  metadata: {
    news_count?: number;
    earnings_date?: string;
    iv30_percentile?: number;
    options_volume_ratio?: number;
    sentiment_score?: number;
  }
}
```

---

### 2. Stock Detail View

**Purpose:** When the user clicks a watchlist item, the main panel shows everything about that ticker.

**Components (top to bottom):**

1. **Price Header**
   - Ticker (large, 17px)
   - Price (extra large, 20px)
   - Change in $ and % (color-coded green/red)
   - ER badge if earnings in ≤14 days
   - Second row (small, 10px): Day range, 52w range, Volume vs avg

2. **Annotated Chart** (see §3)

3. **Model Signals Row** (see §4)

4. **Options Metrics Row** (see §5)

5. **Monte Carlo + Black-Scholes side-by-side** (see §6, §7)

6. **News for ticker** (filtered to selected symbol)

**Selection state:** Stored in Zustand `selectedTicker` store. Default: first item from Hot Now category, or last selected (persisted in localStorage).

---

### 3. Annotated Chart

**Purpose:** Show price with the levels options traders actually care about overlaid directly on the chart.

**Layout:**

- SVG-based custom chart (D3)
- Price line as polyline (purple, 1.8px)
- Volume bars at bottom (small, color-coded green for up days)

**Annotations (each is a horizontal line + labeled pill):**

| Annotation | Color | Line Style | Source |
|---|---|---|---|
| +1σ expected move | Purple `#534AB7` | Dashed | ATM straddle price |
| -1σ expected move | Purple `#534AB7` | Dashed | ATM straddle price |
| Call wall (largest call OI strike) | Green `#1D9E75` | Solid | Options chain OI |
| Put wall (largest put OI strike) | Red `#E24B4A` | Solid | Options chain OI |
| Max pain | Amber `#BA7517` | Dashed | Computed (see §10) |
| Gamma flip | Amber `#BA7517` | Dashed | Computed (see §10) |
| Current price | Purple | Solid marker | Live quote |
| Earnings date | Amber pill | Vertical marker | Finnhub calendar |

**Pill labels** sit on the right or left edge of each line with the level's value (e.g., "★ 140C wall", "max pain 137 · γ flip").

**Timeframe selector:** 1D / 5D / 1M / 3M (top-right of chart)

**API contract:**

```typescript
GET /api/ticker/{symbol}/chart?timeframe=5D
Response: {
  bars: { t: string; o: number; h: number; l: number; c: number; v: number }[],
  annotations: {
    expected_move_upper: number;
    expected_move_lower: number;
    call_wall: { strike: number; oi: number };
    put_wall: { strike: number; oi: number };
    max_pain: number;
    gamma_flip: number;
    earnings_date?: string;
  }
}
```

---

### 4. Model Signals Row

**Purpose:** Five quantified outputs from ML models, displayed as compact cards in a horizontal strip.

| Card | Model | Output | Interpretation |
|---|---|---|---|
| **LSTM · vol 7d** | LSTM | Predicted realized vol % over next 7 days | Compare to IV; if IV >> predicted RV, premium is rich |
| **CatBoost · ER** | CatBoost | Predicted earnings move ±% | Compare to implied move; if predicted > implied, straddle cheap |
| **RF · regime** | Random Forest | Regime label (Risk-on, Defensive, Vol Spike, Crisis) + confidence % | Context for whether to sell vol or buy it |
| **MLP · trend 5d** | MLP | Probability up over next 5 days | Directional bias |
| **Ensemble edge** | MLP combiner | Z-score combining all four | +2.0σ or higher = strong setup |

**UI:** Each card shows model name (uppercase, 9px), main value (13px, 500 weight), interpretation/sub-label (9px, color-coded by direction).

**Inference cadence:** Models run inference every 5 minutes during market hours and on-demand when a ticker is selected. Outputs cached in SQLite.

**API contract:**

```typescript
GET /api/models/{symbol}
Response: {
  lstm_vol_forecast: { value: number; iv_compare: number; interpretation: string };
  catboost_er_move: { value: number; implied_compare: number; interpretation: string };
  rf_regime: { label: string; confidence: number };
  mlp_trend: { prob_up: number; interpretation: string };
  ensemble_edge: { z_score: number; interpretation: string };
  updated_at: string;
}
```

---

### 5. Options Metrics Row

**Purpose:** At-a-glance options health check, all current values.

| Metric | Definition |
|---|---|
| IV Rank | Where current IV30 sits in last 52-week range (0–100) |
| VRP | IV30 minus 30-day realized vol (positive = premium rich) |
| 25Δ skew | OTM put IV minus OTM call IV at 25-delta |
| P/C Ratio | Today's put volume / call volume |
| Max Pain | Strike where most options expire worthless |

**UI:** Same compact card layout as Model Signals Row but more compact (12px main value).

**API contract:**

```typescript
GET /api/ticker/{symbol}/metrics
Response: {
  iv_rank: number;
  vrp: number;
  skew_25d: number;
  pc_ratio: number;
  max_pain: number;
}
```

---

### 6. Monte Carlo Simulation Panel

**Purpose:** Simulate where the stock could be at a future date (typically next earnings or weekly expiry) and compute probabilities of touching key levels.

**Math:** Geometric Brownian Motion (GBM)

```
S(t+dt) = S(t) * exp((μ - σ²/2) * dt + σ * √dt * Z)
where Z ~ N(0,1)
```

Use IV from term structure as `σ`, set `μ = 0` (no drift assumption), `dt = 1/252` (daily).

**Default config:**

- 10,000 paths
- Horizon: days until next earnings, or 7 days if no earnings in next 30 days
- IV input: front-month ATM IV

**Visualization:**

- Fan chart: gray spaghetti lines for ~25 sample paths
- Shaded cones: 50% (darker) and 80% (lighter) probability bands
- Horizontal level lines for: ±1σ expected move, call wall, max pain, put wall
- Probability pills on right edge: P(touch) for each level

**Stats displayed below:**

- Mean expected close
- 95% range
- P(close > call wall strike)
- P(close > +1σ)
- P(close < -1σ)

**API contract:**

```typescript
GET /api/mc/{symbol}?horizon_days=6&n_paths=10000
Response: {
  mean_close: number;
  std_close: number;
  ci_95: [number, number];
  prob_touch: { [level: string]: number };
  prob_close_above: { [strike: number]: number };
  sample_paths: number[][];  // 25 paths for visualization
}
```

---

### 7. Black-Scholes Payoff Panel

**Purpose:** Show the payoff of a specific options strategy — both at expiration and at the current moment.

**Math:** Black-Scholes-Merton formula for call/put pricing.

```
Call: C = S * N(d1) - K * e^(-r*T) * N(d2)
Put:  P = K * e^(-r*T) * N(-d2) - S * N(-d1)

d1 = (ln(S/K) + (r + σ²/2)*T) / (σ * √T)
d2 = d1 - σ * √T
```

**Default strategy:** 140/145 call debit spread on NVDA (for the example). Configurable via strategy picker.

**Visualization:**

- X-axis: underlying price at expiration ($130 to $155)
- Y-axis: P&L per contract
- **Solid line:** payoff at expiration (kinked at strikes)
- **Dashed line:** current value per Black-Scholes (smooth S-curve)
- Filled regions: green where profitable, red where losing
- Vertical line at current spot
- Markers at: max loss, breakeven, max gain

**Greeks displayed:** Delta, Gamma, Theta, Vega (combined for the strategy)

**Strategy types to support:**

- Long call
- Long put
- Short call (covered)
- Short put (cash-secured)
- Call debit spread (bull call spread)
- Put debit spread (bear put spread)
- Call credit spread (bear call spread)
- Put credit spread (bull put spread)
- Iron condor
- Long straddle
- Long strangle
- Calendar spread

**API contract:**

```typescript
POST /api/bs/payoff
Request: {
  symbol: string;
  legs: { strike: number; type: 'call' | 'put'; side: 'long' | 'short'; quantity: number; expiry: string }[];
  iv_override?: number;
  rate?: number;
}
Response: {
  payoff_at_expiry: { price: number; pnl: number }[];
  current_value: { price: number; pnl: number }[];
  cost_debit_credit: number;
  max_gain: number;
  max_loss: number;
  breakevens: number[];
  greeks: { delta: number; gamma: number; theta: number; vega: number };
}
```

---

### 8. Trading Calendar

**Purpose:** Horizontal strip of the upcoming 7 trading days with key events on each day.

**Event types and sources:**

| Event Type | Source | Color Code |
|---|---|---|
| Earnings | Finnhub | Gray with ticker |
| FOMC meetings / minutes | FRED + manual schedule | Red (FCEBEB bg, 791F1F text) |
| Fed speakers (Powell, etc.) | Manual or Finnhub | Gray |
| CPI / PPI / NFP / GDP | FRED release calendar | Amber (FAEEDA bg, 633806 text) |
| OPEX (3rd Friday) | Computed | Purple (EEEDFE bg, 3C3489 text) |
| Quad witching | Computed | Purple, bold |
| Market holidays | Manual | Hatched/disabled |

**UI:**

- 7-column grid, each column is one trading day
- Today highlighted with 2px left border + secondary bg
- Days where the currently-selected ticker has an event (e.g., NVDA ER) get a subtle purple tint
- Each event is a small colored pill with abbreviated label

**API contract:**

```typescript
GET /api/calendar?start=2026-05-14&end=2026-05-22
Response: {
  days: {
    date: string;
    is_today: boolean;
    events: {
      type: 'earnings' | 'fomc' | 'fed_speak' | 'economic' | 'opex' | 'holiday';
      title: string;        // "NVDA ER" or "CPI 8:30"
      ticker?: string;
      time?: string;
      importance: 'low' | 'medium' | 'high';
    }[]
  }[]
}
```

---

### 9. News Feed

**Purpose:** Show recent news for the selected ticker, AI-tagged for direction.

**Tags:**

- `BULLISH` — green background, dark green text
- `BEARISH` — red background, dark red text
- `ANALYST` — blue background (analyst upgrades/downgrades)
- `MACRO` — gray (macro-related but ticker-relevant)
- `EARNINGS` — amber (earnings-related)

**Source:** Finnhub company news endpoint, filtered to last 24h, tagged via Finnhub's built-in sentiment score (positive >0.2 = bullish, negative <-0.2 = bearish, neutral = macro/info).

**UI:** List of 3–5 most recent items, each showing tag + timestamp + source + headline.

**API contract:**

```typescript
GET /api/news/{symbol}?limit=5
Response: {
  items: {
    tag: 'BULLISH' | 'BEARISH' | 'ANALYST' | 'MACRO' | 'EARNINGS';
    timestamp: string;
    source: string;
    headline: string;
    url: string;
    sentiment_score: number;
  }[]
}
```

---

## Data Layer

### Alpaca

**Used for:** stocks (quotes, bars), options chains, greeks

**Key endpoints (alpaca-py SDK):**

```python
from alpaca.data.historical.stock import StockHistoricalDataClient
from alpaca.data.historical.option import OptionHistoricalDataClient
from alpaca.data.live.stock import StockDataStream
from alpaca.data.requests import (
    StockLatestQuoteRequest, StockBarsRequest,
    OptionChainRequest, OptionSnapshotRequest
)
from alpaca.data.timeframe import TimeFrame

# Stocks
stock_client = StockHistoricalDataClient(api_key, secret_key)
bars = stock_client.get_stock_bars(StockBarsRequest(
    symbol_or_symbols="NVDA",
    timeframe=TimeFrame.Day,
    start=datetime(2024, 1, 1)
))

# Options chain
option_client = OptionHistoricalDataClient(api_key, secret_key)
chain = option_client.get_option_chain(OptionChainRequest(
    underlying_symbol="NVDA",
    feed="indicative"  # free tier
))
```

**Rate limits:** Free tier ~200 requests/min on stocks. Options TBD but generous for personal use.

**Caching strategy:**

- Latest quotes: cache for 5 seconds
- Options chain snapshots: cache for 30 seconds (indicative feed updates aren't truly real-time anyway)
- Daily bars: cache permanently in SQLite

---

### Finnhub

**Used for:** news, earnings calendar, social sentiment

**Key endpoints:**

```python
import finnhub

client = finnhub.Client(api_key=FINNHUB_API_KEY)

# Company news
news = client.company_news("NVDA", _from="2026-05-13", to="2026-05-14")

# Earnings calendar
earnings = client.earnings_calendar(_from="2026-05-14", to="2026-05-22", symbol="", international=False)

# Social sentiment
sentiment = client.stock_social_sentiment("NVDA")
```

**Rate limit:** 60 calls/min on free tier. Aggressive caching required.

---

### FRED

**Used for:** Fed funds rate, FOMC dates, CPI/PPI/NFP/GDP release schedule

**Key endpoints:**

```python
from fredapi import Fred
fred = Fred(api_key=FRED_API_KEY)

# Get latest CPI
cpi = fred.get_series("CPIAUCSL")

# Release dates (use FRED's release calendar)
# https://api.stlouisfed.org/fred/releases/dates
```

**Rate limit:** very generous, basically unlimited for personal use.

---

### SQLite Schema

```sql
-- Watchlist items (computed daily)
CREATE TABLE watchlist_items (
    id INTEGER PRIMARY KEY,
    category TEXT NOT NULL,           -- 'hot_now', 'earnings', etc.
    symbol TEXT NOT NULL,
    subtitle TEXT,
    metadata_json TEXT,                -- flexible per category
    created_at TIMESTAMP,
    INDEX (category, symbol)
);

-- Options chain snapshots (collected daily for ML training)
CREATE TABLE options_snapshots (
    id INTEGER PRIMARY KEY,
    symbol TEXT NOT NULL,
    snapshot_date DATE NOT NULL,
    strike REAL,
    expiry DATE,
    option_type TEXT,                  -- 'call' or 'put'
    bid REAL,
    ask REAL,
    last REAL,
    volume INTEGER,
    open_interest INTEGER,
    iv REAL,
    delta REAL,
    gamma REAL,
    theta REAL,
    vega REAL,
    INDEX (symbol, snapshot_date)
);

-- News items
CREATE TABLE news_items (
    id INTEGER PRIMARY KEY,
    symbol TEXT,
    timestamp TIMESTAMP,
    source TEXT,
    headline TEXT,
    url TEXT,
    sentiment_score REAL,
    tag TEXT,
    INDEX (symbol, timestamp DESC)
);

-- Calendar events
CREATE TABLE calendar_events (
    id INTEGER PRIMARY KEY,
    date DATE NOT NULL,
    event_type TEXT,
    title TEXT,
    ticker TEXT,
    importance TEXT,
    metadata_json TEXT,
    INDEX (date)
);

-- Model signals (cached predictions)
CREATE TABLE model_signals (
    id INTEGER PRIMARY KEY,
    symbol TEXT NOT NULL,
    model_name TEXT NOT NULL,
    prediction_json TEXT,
    created_at TIMESTAMP,
    INDEX (symbol, model_name, created_at DESC)
);
```

---

## ML Models

**Overall principles:**

- **Train locally** on your laptop. CatBoost and Random Forest fit easily on CPU. LSTM may want a GPU but Google Colab free tier works.
- **Walk-forward validation, not random K-fold.** Financial data has temporal structure; random splits leak future information.
- **Point-in-time discipline.** Features used to predict day T must only contain information available at the close of day T-1. Look-ahead bias is the #1 killer.
- **Realistic transaction costs in backtests.** Bid-ask spreads matter on options.

### 9.1 LSTM Volatility Forecast

**Goal:** Predict realized volatility (annualized) over the next 7 trading days.

**Features (each lookback day):**

- Log return
- Intraday range (high - low) / close
- Volume Z-score (vs 20-day avg)
- VIX level
- VIX 5-day change
- IV30 of the underlying
- Day-of-week (cyclical encoding)

**Architecture:**

```python
import torch
import torch.nn as nn

class VolLSTM(nn.Module):
    def __init__(self, input_size=7, hidden_size=64, num_layers=2, output_size=1):
        super().__init__()
        self.lstm = nn.LSTM(input_size, hidden_size, num_layers,
                            batch_first=True, dropout=0.2)
        self.fc = nn.Linear(hidden_size, output_size)

    def forward(self, x):
        out, _ = self.lstm(x)
        out = self.fc(out[:, -1, :])
        return out
```

**Target:** future 7-day realized vol = `np.sqrt(252) * returns[t+1:t+8].std()`

**Training:**

- Lookback window: 30 days
- Loss: MSE
- Optimizer: Adam, lr=0.001
- Batch size: 32
- Epochs: 50 with early stopping (patience=5)
- Walk-forward CV: train on 2 years, validate on next 6 months, slide forward

**Output:** predicted RV%, displayed in dashboard cell.

---

### 9.2 CatBoost Earnings Move Forecast

**Goal:** Predict the absolute % move on the day of earnings.

**Features (point-in-time, day before earnings):**

- IV30 / IV60 / IV90
- IV percentile (52w)
- Skew (25d put IV - 25d call IV)
- Implied move from straddle (the market's bet)
- Last 8 earnings: realized move size, surprise % vs estimate
- Last 4 quarters: revenue growth %, EPS growth %
- Sector ETF 5-day return
- VIX level
- Days since last guidance change
- Analyst dispersion (std of estimates)

**Training:**

```python
from catboost import CatBoostRegressor

model = CatBoostRegressor(
    iterations=500,
    learning_rate=0.05,
    depth=6,
    loss_function='MAE',
    early_stopping_rounds=30,
    verbose=50
)
model.fit(X_train, y_train, eval_set=(X_val, y_val))
```

**Target:** absolute % move on earnings day.

**Walk-forward CV:** train on all earnings prior to date T, predict T, slide forward.

**Output:** predicted ±% move, compared to implied move.

---

### 9.3 Random Forest Regime Classifier

**Goal:** Classify current market regime into one of: `risk_on`, `defensive`, `vol_spike`, `crisis`, `mean_reverting_chop`.

**Labels (semi-supervised, derived from market data):**

- `risk_on`: SPY up 20-day, VIX < 15, breadth > 60%
- `defensive`: defensives outperforming cyclicals, XLU > XLY
- `vol_spike`: VIX up >30% in 5 days
- `crisis`: VIX > 30 AND SPY down > 5% in 5 days
- `mean_reverting_chop`: 20-day range bound, VIX 15–20

**Features:**

- SPY 20-day return
- VIX level + 5-day change
- Sector ETF relative strength (top 3 vs bottom 3)
- HYG/LQD ratio (credit spread proxy)
- DXY level + 20-day change
- 10y-2y Treasury spread
- McClellan oscillator (breadth)
- VVIX / VIX ratio (vol of vol)

**Training:**

```python
from sklearn.ensemble import RandomForestClassifier

model = RandomForestClassifier(
    n_estimators=200,
    max_depth=10,
    class_weight='balanced',
    random_state=42
)
model.fit(X_train, y_train)
```

**Output:** regime label + confidence (proba), used for context across the dashboard.

---

### 9.4 MLP Trend Direction

**Goal:** Probability that the underlying closes higher in 5 trading days.

**Features:**

- 5-day, 10-day, 20-day, 50-day momentum
- RSI(14)
- MACD signal
- Volume Z-score
- News sentiment 5-day average
- Sector momentum
- Beta to SPY
- Distance from 50-day MA (Z-score)

**Architecture:**

```python
from sklearn.neural_network import MLPClassifier

model = MLPClassifier(
    hidden_layer_sizes=(64, 32),
    activation='relu',
    solver='adam',
    learning_rate_init=0.001,
    max_iter=500,
    early_stopping=True
)
model.fit(X_train, y_train)
```

**Target:** binary, 1 if close 5 days later is higher than today's close.

**Output:** P(up), displayed as % in dashboard.

---

### 9.5 Ensemble Edge Score

**Goal:** Combine all four sub-models into a single z-score indicating overall setup quality.

**Approach:** Weighted combination where weights are learned via a small MLP on top of the four sub-model outputs.

```python
# Features = outputs from sub-models
# Target = forward 5-day return (or risk-adjusted return)

from sklearn.neural_network import MLPRegressor

ensemble = MLPRegressor(
    hidden_layer_sizes=(8,),
    activation='relu',
    max_iter=200
)
ensemble.fit(X_sub_model_outputs, y_forward_returns)

# At inference, output prediction → standardize to z-score over historical distribution
```

**Output:** edge z-score. +2σ or higher displayed as "strong setup."

---

## Core Calculations

### IV Rank

```python
def iv_rank(current_iv30, iv30_history_52w):
    """0-100 score for where current IV sits in 52w range."""
    return 100 * (current_iv30 - iv30_history_52w.min()) / \
           (iv30_history_52w.max() - iv30_history_52w.min())
```

### Vol Risk Premium (VRP)

```python
def vrp(current_iv30, realized_vol_30d):
    """IV minus RV. Positive = premium rich."""
    return current_iv30 - realized_vol_30d
```

### Realized Volatility

```python
def realized_vol(returns, window=30, annualize=True):
    """Annualized realized vol from log returns."""
    rv = returns.rolling(window).std()
    if annualize:
        rv *= np.sqrt(252)
    return rv * 100  # percent
```

### Expected Move (1σ)

```python
# calculations/expected_move.py
STRADDLE_TO_SIGMA = 0.85

def expected_move(atm_call_price, atm_put_price) -> float:
    return (atm_call_price + atm_put_price) * STRADDLE_TO_SIGMA

def expected_move_bands(spot, em) -> tuple[float, float]:
    return spot + em, spot - em

def atm_straddle_price(chain, spot, expiry) -> tuple[float, float] | None:
    # Picks strike closest to spot for `expiry`; mid = (bid+ask)/2,
    # falls back to last, then bid-or-ask. Returns None if either side
    # of the ATM pair is missing or unpriced.
```

### Max Pain

```python
# calculations/gamma_exposure.py
def max_pain(chain) -> float | None:
    """Strike that minimizes total option-holder intrinsic value.
    Filters to rows where open_interest > 0; returns None on empty chain."""
    rows = [c for c in chain if c.open_interest and c.open_interest > 0]
    strikes = sorted({c.strike for c in rows})
    best_k, best_pain = None, float("inf")
    for k in strikes:
        pain = sum(
            r.open_interest * max(k - r.strike, 0) if r.type == "call"
            else r.open_interest * max(r.strike - k, 0)
            for r in rows
        )
        if pain < best_pain:
            best_k, best_pain = k, pain
    return best_k
```

### Dealer Gamma Exposure (GEX) by strike

```python
# calculations/gamma_exposure.py
def gex_by_strike(chain, spot) -> dict[float, float]:
    """Sign convention: dealers short calls (-1), long puts (+1).
    Skips rows missing open_interest or gamma."""
    out = {}
    for c in chain:
        if c.open_interest is None or c.gamma is None:
            continue
        sign = -1 if c.type == "call" else +1
        contribution = sign * c.open_interest * 100 * c.gamma * (spot ** 2) * 0.01
        out[c.strike] = out.get(c.strike, 0.0) + contribution
    return out
```

### Gamma Flip Level

```python
# calculations/gamma_exposure.py
def gamma_flip(gex_dict) -> float | None:
    """Lowest strike where cumulative GEX (ascending) crosses ≥ 0."""
    if not gex_dict:
        return None
    cumulative = 0.0
    for k in sorted(gex_dict.keys()):
        cumulative += gex_dict[k]
        if cumulative >= 0:
            return k
    return None
```

**±20% spot-window guard (router level).** When using volume as the
open-interest proxy (free-tier indicative feed has no OI — see Known
Free-Tier Limitations), deep-OTM strikes with tiny actual liquidity but
non-trivial volume-proxy values dominate the cumulative-GEX walk and
produce absurd flip levels. The chart router restricts the GEX input to
strikes within `[0.8 * spot, 1.2 * spot]` before calling `gamma_flip`:

```python
# routers/ticker.py — _compute_annotations
gex_window = [c for c in chain if 0.8 * spot <= c.strike <= 1.2 * spot]
gex = gex_by_strike(gex_window, spot)
a.gamma_flip = gamma_flip(gex) if gex else None
```

`max_pain` and the OI walls remain full-chain — those legitimately want
the entire population.

### 25-Delta Skew

```python
# calculations/skew.py
def skew_25d(chain, expiry) -> float | None:
    """mean(put IV @ Δ ∈ [-0.30, -0.20]) − mean(call IV @ Δ ∈ [0.20, 0.30])
    for the given expiry. Returns None if either side is empty."""
    same = [c for c in chain if c.expiry == expiry]
    put_ivs = [c.iv for c in same if c.type == "put"
               and c.delta is not None and -0.30 <= c.delta <= -0.20
               and c.iv is not None]
    call_ivs = [c.iv for c in same if c.type == "call"
                and c.delta is not None and 0.20 <= c.delta <= 0.30
                and c.iv is not None]
    if not put_ivs or not call_ivs:
        return None
    return sum(put_ivs)/len(put_ivs) - sum(call_ivs)/len(call_ivs)
```

### Realized Volatility

```python
# calculations/realized_vol.py
def realized_vol(closes, window=30) -> float | None:
    """Annualized RV from log returns. Returns None when fewer than
    window+1 closes are supplied."""
```

### IV Rank + Percentile

```python
# calculations/iv_metrics.py
def iv_rank(current, history) -> float | None:
    """Canonical (max-min)/100 score. Returns None when history has
    < 2 distinct points or max == min. Used once we have ≥252 days."""

def iv_percentile(current, history) -> float | None:
    """Phase 3 proxy: % of historical readings strictly below current.
    Same 0-100 scale as iv_rank — same field name in the API."""

def vrp(current_iv30, realized_vol_30d) -> float:
    """IV30 - RV30. Positive = premium rich."""
```

### P/C Ratio

```python
# calculations/pc_ratio.py
def pc_ratio(call_volume, put_volume) -> float | None:
    """put_volume / call_volume. None when call_volume == 0."""
```

### Monte Carlo (GBM)

```python
def monte_carlo_paths(S0, mu, sigma, T, n_steps, n_paths, seed=None):
    """
    S0: starting price
    mu: annualized drift (use 0 for risk-neutral)
    sigma: annualized vol (use IV)
    T: time horizon in years
    n_steps: number of steps
    n_paths: number of paths
    Returns: array shape (n_paths, n_steps+1)
    """
    rng = np.random.default_rng(seed)
    dt = T / n_steps
    Z = rng.standard_normal((n_paths, n_steps))
    paths = np.zeros((n_paths, n_steps + 1))
    paths[:, 0] = S0
    for t in range(n_steps):
        paths[:, t+1] = paths[:, t] * np.exp(
            (mu - 0.5 * sigma**2) * dt + sigma * np.sqrt(dt) * Z[:, t]
        )
    return paths
```

### Black-Scholes Pricing

```python
from scipy.stats import norm

def bs_price(S, K, T, r, sigma, option_type='call'):
    """Black-Scholes-Merton option price."""
    d1 = (np.log(S/K) + (r + 0.5*sigma**2)*T) / (sigma*np.sqrt(T))
    d2 = d1 - sigma*np.sqrt(T)
    if option_type == 'call':
        return S * norm.cdf(d1) - K * np.exp(-r*T) * norm.cdf(d2)
    else:
        return K * np.exp(-r*T) * norm.cdf(-d2) - S * norm.cdf(-d1)

def bs_greeks(S, K, T, r, sigma, option_type='call'):
    """Returns delta, gamma, theta, vega."""
    d1 = (np.log(S/K) + (r + 0.5*sigma**2)*T) / (sigma*np.sqrt(T))
    d2 = d1 - sigma*np.sqrt(T)
    pdf_d1 = norm.pdf(d1)
    gamma = pdf_d1 / (S * sigma * np.sqrt(T))
    vega = S * pdf_d1 * np.sqrt(T) * 0.01  # per 1% IV change
    if option_type == 'call':
        delta = norm.cdf(d1)
        theta = (-S*pdf_d1*sigma/(2*np.sqrt(T)) - r*K*np.exp(-r*T)*norm.cdf(d2)) / 365
    else:
        delta = norm.cdf(d1) - 1
        theta = (-S*pdf_d1*sigma/(2*np.sqrt(T)) + r*K*np.exp(-r*T)*norm.cdf(-d2)) / 365
    return {'delta': delta, 'gamma': gamma, 'theta': theta, 'vega': vega}
```

---

## Visual Design System

### Colors

```ts
// design.ts
export const colors = {
  // Primary / accent
  primary: '#534AB7',           // purple
  primaryLight: '#EEEDFE',
  primaryDark: '#3C3489',

  // Status
  bullish: '#1D9E75',           // teal/green
  bullishLight: '#EAF3DE',
  bearish: '#E24B4A',           // red
  bearishLight: '#FCEBEB',
  warning: '#BA7517',           // amber
  warningLight: '#FAEEDA',
  info: '#378ADD',              // blue
  infoLight: '#E6F1FB',

  // Categories
  hot: '#D85A30',               // coral
  earnings: '#BA7517',          // amber
  unusual: '#534AB7',           // purple
  sentimentUp: '#1D9E75',
  sentimentDown: '#E24B4A',

  // Neutrals
  bg: '#FFFFFF',
  bgSecondary: '#F1EFE8',
  textPrimary: '#1A1A1A',
  textSecondary: '#5F5E5A',
  textTertiary: '#888780',
  border: '#E5E5E0',
};
```

Dark mode: invert backgrounds, lighten text colors. Use Tailwind's `dark:` prefix.

### Typography

- Font family: system-ui, sans-serif
- Weights used: 400 (regular), 500 (medium) — that's it, no 700
- Sizes:
  - Display: 22px (rarely used)
  - Heading: 17px (ticker), 16px (section header)
  - Body: 13px, 14px
  - Small: 11px, 12px (most labels)
  - Tiny: 9px, 10px (data labels, category headers in uppercase)

### Spacing

- Page padding: 14px
- Component padding: 8–12px
- Inter-element gap: 4–10px
- Section spacing (vertical): 1rem

### Borders & Radii

- Border: 0.5px solid (very subtle)
- Border color: `#E5E5E0` (light) / `rgba(255,255,255,0.1)` (dark)
- Radius: 4px (tags, pills), 8px (small cards), 12px (large cards)

### Component patterns

- **Pill labels**: rounded rect, 9px text, white text on colored bg, used for chart annotations
- **Stat cards**: small uppercase label (9px) + value (12–14px, 500 weight) + optional sub-label
- **Compact tables**: no borders between rows, alternating bg-tertiary
- **Hover states**: very subtle background change, no large transforms

---

## Implementation Phases

Each phase ships **end to end** (data + API + UI) before moving on. Don't build broadly across phases.

### Phase 1: News-Organized Watchlist (Weekend 1–2)  ✅ shipped 2026-05-14

**Goal:** A working watchlist that updates automatically with today's most important names.

**Tasks:**

- Set up FastAPI backend with one endpoint `/api/watchlist`
- Set up React frontend with one component `<WatchlistColumn />`
- Implement Finnhub client: news, earnings calendar, social sentiment
- Implement Alpaca client: latest quotes for watchlist tickers
- Build watchlist computation logic (5 categories)
- Schedule `refresh_watchlist` job every 60s
- Display in left sidebar

**Acceptance criteria:**

- 5 categories populate with sensible names
- Updates without page refresh
- Each item shows ticker, subtitle, % change

---

### Phase 2: Stock Detail View + Annotated Chart (Weekend 3–5)  ✅ shipped 2026-05-14 (price header only; chart shipped in Phase 3)

**Goal:** Clicking a watchlist item brings up detailed view with annotated chart.

**Tasks:**

- Build `<StockDetailView />` parent component
- Build `<PriceHeader />` with all the price info
- Build `<AnnotatedChart />` with D3 — bars + price line + horizontal level lines + pill labels
- Implement IV metrics calculations
- Implement max pain, gamma exposure calculations
- Endpoint `/api/ticker/{symbol}/chart` returns bars + annotations

**Acceptance criteria:**

- Click NVDA in watchlist → see chart with expected move bands, max pain, walls
- All annotations have pill labels with correct values
- Chart can switch between 1D / 5D / 1M / 3M timeframes

---

### Phase 3: Annotated Chart + Options Metrics Row (Weekend 6)  ✅ shipped 2026-05-14

**Goal:** Five compact cells showing IV Rank, VRP, skew, P/C, max pain.

**Tasks:**

- Build `<OptionsMetricsRow />` component
- Implement remaining calculations (IV Rank, VRP from chain history)
- Cache IV30 history in SQLite for IV Rank computation
- Endpoint `/api/ticker/{symbol}/metrics`

**Acceptance criteria:**

- All 5 cells populate with correct values
- Values match what you'd compute manually from the chain

---

### Phase 4: Trading Calendar (Weekend 7)

**Goal:** Weekly calendar strip at top of dashboard.

**Tasks:**

- Build `<CalendarStrip />` component
- Implement FRED client (releases endpoint)
- Implement OPEX date computation (third Friday of each month)
- Cache calendar events in SQLite (refresh daily)
- Endpoint `/api/calendar`

**Acceptance criteria:**

- See current week with today highlighted
- Earnings dates show for watchlist tickers
- FOMC, CPI, OPEX events visible

---

### Phase 5: Monte Carlo + Black-Scholes Panels (Weekend 8–9)

**Goal:** Side-by-side forward modeling panels.

**Tasks:**

- Implement `monte_carlo_paths()` function
- Implement Black-Scholes pricing + greeks
- Build `<MonteCarloPanel />` with fan chart (D3) + probability stats
- Build `<BlackScholesPanel />` with payoff diagram + greeks
- Build `<StrategyPicker />` for selecting strategy type
- Endpoints `/api/mc/{symbol}` and `/api/bs/payoff`

**Acceptance criteria:**

- MC fan chart shows paths + cones + probability pills
- BS panel shows expiry payoff and current value curves
- Greeks display correctly
- Strategy picker switches between long call, spread, straddle, etc.

---

### Phase 6: First ML Model — CatBoost Earnings (Weekend 10–13)

**Goal:** One model running end-to-end.

**Tasks:**

- Set up historical data pipeline (download earnings history for ~100 liquid tickers)
- Feature engineering for earnings move prediction
- Train CatBoost model, walk-forward CV
- Save model artifact, load at startup
- Inference endpoint returning prediction + confidence
- Display in model signals row

**Acceptance criteria:**

- Model trained on at least 2 years of earnings prints
- MAE on out-of-sample data is reported
- Prediction displays in dashboard for tickers reporting earnings

---

### Phase 7: Remaining ML Models (Weekend 14–18)

**Goal:** Add LSTM vol forecast, RF regime, MLP trend, ensemble.

One per weekend. Same pattern as Phase 6 for each.

---

### Phase 8: News Feed + Polish (Weekend 19+)

- News feed for selected ticker
- WebSocket real-time updates instead of polling
- Dark mode toggle
- Mobile-responsive layout
- Performance optimization

---

## Testing

### Unit tests (pytest)

- **Calculations:** every function in `calculations/` has tests with known inputs/outputs
- **Edge cases:** empty chains, single-strike chains, missing greeks
- **ML features:** point-in-time correctness (no future leakage)

```python
def test_max_pain_simple():
    chain = pd.DataFrame([
        {'strike': 100, 'type': 'call', 'open_interest': 1000},
        {'strike': 105, 'type': 'call', 'open_interest': 500},
        {'strike': 95, 'type': 'put', 'open_interest': 1000},
        {'strike': 100, 'type': 'put', 'open_interest': 500},
    ])
    assert max_pain(chain, current_price=100) == 100
```

### Integration tests

- Mock Alpaca/Finnhub/FRED responses
- Test API endpoints return expected schema
- Test watchlist computation produces 5 categories

### Backtesting framework

For ML models: walk-forward over historical data, report:

- MAE / RMSE for regressions
- Confusion matrix for classifications
- **Sharpe ratio of a strategy that trades on model signals** (this is the real test)
- Compare to a naive baseline (e.g., "predict mean")

---

## Known Free-Tier Limitations

Documented as we hit them in Phases 1–3. Each item lists the workaround in
the current build and what would change with a paid tier.

### Sentiment data — Finnhub paid endpoints

`stock_social_sentiment` and `news_sentiment` both 403 on the free key
(paid-tier only). Free-tier `company_news` returns articles **without**
per-article sentiment scores, so we can't even derive a slope ourselves.

- **Workaround:** Watchlist categories `sentiment_up` and `sentiment_down`
  return empty arrays plus a `notes` entry on the API response:
  `"Sentiment unavailable on free tier"`. Frontend renders this in italic
  gray under the category header.
- **Future:** Stocktwits has a free streaming API (rate-limited but
  workable) — wire that as the sentiment source in a later phase, or
  upgrade Finnhub when sentiment becomes a hard requirement.

### Open interest — Alpaca indicative options feed

The indicative feed returns IV + greeks for ~60% of contracts but
**zero open interest** across the entire chain (verified: 0/4800 rows on
NVDA). OI-dependent computations (max-pain, OI walls, GEX, gamma flip)
would otherwise all return null.

- **Workaround:** `services/alpaca_client.get_chain_snapshot` issues a
  chunked `OptionBarsRequest(timeframe=Day, start=today)` for every
  contract in the chain to populate today's per-contract daily volume.
  The chart router (`_chain_with_oi_proxy`) substitutes `volume` for
  missing `open_interest` before passing to the calc layer. The chart
  response includes `oi_source: "volume_proxy" | "open_interest"` so the
  UI can label the data quality. The `±20% spot-window guard` on
  `gamma_flip` (see §10) is required because the proxy makes deep-OTM
  strikes look more meaningful than they are.
- **Cost:** ~50 extra Alpaca API calls per fresh chain fetch on a
  4800-contract chain like NVDA. Cached 5min so it's tolerable, but the
  first cold load on a new ticker takes 8–15 seconds (see Performance
  Notes below).
- **Future:** Algo Trader Plus tier exposes real OI in the snapshot, at
  which point the substitution turns off automatically.

### Earnings calendar — Finnhub coverage gaps

Observed during Phase 2 verification: Finnhub's free `earnings_calendar`
sometimes does not return individual large-caps that other sources show
as reporting in the requested window. We confirmed against AAPL/AMD —
the dates we expected weren't returned despite querying `_from..to`
correctly.

- **Workaround:** Trust what Finnhub returns; show empty earnings
  category honestly when nothing matches. Don't fabricate dates.
- **Future:** Cross-reference with Nasdaq's free earnings calendar or
  pull from Yahoo as a secondary source when we hit the limit.

### IV history — empty until we collect

`iv_rank` (and the percentile proxy) need historical IV30 from
`options_snapshots`. The collection job (`collect_options_chain`,
runs daily at 16:30 ET) only started populating going forward — there's
no backfill source on the free tier.

- **Workaround:** Metrics endpoint returns `iv_rank: null` plus
  `iv_rank_status: "X/60 days collected"` until the percentile
  proxy is meaningful. Frontend renders `—` with the status line.

---

## Performance Notes

What's currently slow and why; what we accept vs. what's on the polish
backlog.

### Cold ticker click — 8–15 seconds

First click on a ticker that hasn't been viewed in the last 5 minutes
incurs:

- 1 stock snapshot call (~0.3s)
- 1 year-bars call (~0.5s, daily granularity)
- 1 chain snapshot call (~1s for the chain itself)
- N option-bars calls for per-contract daily volume — ~50 chunked calls
  on NVDA-sized chains, ~5–10s sequential

Total: **8–15 seconds on a fresh ticker, < 200ms on a cached one (5min
TTL on chain + bars).** Frontend currently shows "Loading…" text rather
than skeleton placeholders during this window.

### Deferred polish (not required for current phases)

- **Skeleton placeholders** for the chart and metrics row while bars +
  chain are loading. Currently text says "Loading chart…" / "Loading
  metrics…".
- **Pre-warm on hover** — when the user hovers a watchlist item for >300ms,
  prefetch its detail/chart/metrics so the click feels instant. Easy with
  TanStack Query's `queryClient.prefetchQuery`.
- **Background pre-warm of the universe** at app start (15 tickers × 8s
  = 2min in the background) so most clicks are warm-cache from the start.

### What's already fast enough

- Watchlist refresh: 60s cycle takes ~10s of work (mostly Finnhub news
  with 0.3s spacing + Alpaca chain volumes). Comfortably under the
  cycle.
- `/api/watchlist`: reads from SQLite cache, < 5ms.
- Frontend polling: TanStack Query 5s refetch on detail/chart/metrics is
  cheap because backend results are 30s-cached server-side.

---

## Known Limitations

Being honest about the $0 / free-tier path:

1. **Alpaca's indicative options feed is not real-time OPRA.** Fine for building, analysis, paper trading. Not suitable for live trading where exact bid/ask timing matters. Upgrade to Algo Trader Plus for real-time OPRA when ready to trade live.

2. **Finnhub free tier: 60 calls/min.** Aggressive caching needed during market open. May need to fall back to slower refresh intervals on busy days.

3. **No L2 / order book data.** This dashboard is not Bookmap. We don't see real-time bid/ask depth — that's an institutional data product.

4. **No proper "unusual options flow" service.** We compute our own ratio (today's volume vs 20-day avg) but it's coarser than what Cheddar Flow or Unusual Whales provide. They have sweep detection, premium-paid analysis, etc., that we don't.

5. **Historical options data depth is limited.** We collect chains daily starting now to build our own dataset. For deeper history needed for ML training, ORATS ($99/mo) or similar would help. Workaround: start collecting now, accept that ML quality improves over months.

6. **News latency.** Free news from Finnhub is seconds-to-minutes behind paid services. Fine for swing trading.

7. **No mobile app.** Web-only. Responsive design helps but native app is out of scope.

---

## Roadmap

Beyond the core build, ideas for future enhancements:

- **Live position tracking** — sync with Alpaca portfolio, show P&L on open positions
- **Interactive strategy builder** — drag/drop legs, see live greeks
- **Historical analogue matching** — "show me 10 historical setups that looked like NVDA today, what happened next"
- **Multi-ticker comparison** — compare NVDA vs AMD vs AVGO on same metrics
- **Cross-asset context panel** — VIX, DXY, HYG, gold relationships
- **Alert system** — set conditions (e.g., NVDA IV rank > 80) and get notifications
- **Backtest console** — interactive UI to test rules on historical data
- **Strategy persistence** — save trade ideas, track which played out
- **Voice notes** — record why you took a trade, review later

---

## Glossary

- **IV** — Implied Volatility. The volatility implied by current option prices.
- **RV** — Realized Volatility. Actual historical volatility computed from price returns.
- **VRP** — Volatility Risk Premium. IV minus RV. When positive, options are "expensive" relative to actual movement.
- **IV Rank** — Where current IV sits in its 52-week range. 0 = lowest, 100 = highest.
- **IV Percentile** — % of last year's IV readings below current. Similar to rank but uses distribution.
- **Skew** — Difference in IV between OTM puts and OTM calls. Positive skew = puts more expensive.
- **Term Structure** — IV across different expirations. Contango (rising) = normal, Backwardation (front higher) = near-term catalyst priced in.
- **OPEX** — Options expiration. Monthly OPEX is the third Friday.
- **OPRA** — Options Price Reporting Authority. The official US options data feed.
- **Quad Witching** — Quarterly OPEX when stock options, index options, stock futures, and index futures all expire on the same day.
- **Greeks** — Sensitivities of option price: Delta (price), Gamma (delta change), Theta (time), Vega (vol), Rho (rate).
- **Max Pain** — Strike where the most options expire worthless. Price often gravitates here near expiration.
- **Gamma Flip** — Price level where dealer gamma exposure switches sign. Above = stabilizing, below = amplifying.
- **GEX** — Gamma Exposure. Dealer's aggregate gamma position across all strikes.
- **0DTE** — Zero Days To Expiration. Options expiring same day.
- **AMC / BMO** — After Market Close / Before Market Open. When earnings are reported.
- **Expected Move** — 1-sigma move implied by the straddle price.
- **Iron Condor** — Sell OTM put spread + sell OTM call spread. Profits if price stays in a range.
- **Calendar Spread** — Sell near-dated, buy longer-dated, same strike. Profits from time decay differential.
- **GBM** — Geometric Brownian Motion. Standard stochastic process for stock price simulation.
- **Walk-Forward** — Validation method where you train on data up to time T, test on T+1 to T+N, then slide forward.

---

## Notes for Claude Code

- Start with Phase 1. Get it shipping end-to-end before touching Phase 2.
- When in doubt, ask before implementing. The spec is a guide, not a contract.
- Keep components small and focused. If a file gets over 200 lines, split it.
- All money values formatted with `Intl.NumberFormat` — don't trust raw `toFixed()`.
- All percentages rounded to 2 decimals max in display layer.
- All API responses validated against TypeScript interfaces using `zod` schemas.
- Cache aggressively. Free-tier rate limits will bite during market open.
- Use `pytest` for backend tests, `vitest` for frontend.
- Format with `black` (Python) and `prettier` (JS/TS).
- Lint with `ruff` (Python) and `eslint` (JS/TS).
- Pre-commit hooks: run formatters + linters + tests before commit.

---

*Built for personal use. Not investment advice. Trade at your own risk.*

---

## Open-source attributions

- Price chart and payoff curve rendering: [TradingView Lightweight Charts](https://www.tradingview.com/lightweight-charts/) (Apache-2.0). On-chart watermark is disabled in favor of this notice.