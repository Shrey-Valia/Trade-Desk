# Real-time data-feed design spike (WS-D)

**Status:** Design / research only. No runtime behavior change ships with this doc.
**Date:** 2026-06-25
**Scope:** Decide a paid real-time market-data provider and define the architecture
that lets us flip from polling to a WebSocket stream behind a feature flag, with the
current polling path as a fallback.

> This is a **costed decision document**, not a build. The only code artifact is an
> optional, non-wired interface stub (`backend/services/realtime_feed.py`) imported by
> nothing and gated behind a disabled flag. See [§7](#7-optional-interface-stub).

---

## 0. Where we are today (the baseline this must compose with)

All market data is **pull-based**, all through `backend/services/alpaca_client.py`:

- `get_quotes(symbols)` — one batched `StockSnapshotRequest`, cached 5s.
- `get_bars(symbol, timeframe)` — `StockBarsRequest`, `feed=IEX`, cached per the
  `_TIMEFRAME_CONFIG` grid (30s–3600s).
- `get_chain_snapshot` / `get_option_chain_volumes` — option chain + per-contract
  daily volume, cached 5 min.

Every SDK call is wrapped in three layers (do not break these — the new path reuses them):

1. **`TokenBucket`** (`services/rate_limit.py`) — process-wide `_alpaca_bucket`
   (rate `6.0`/s, burst `8.0`) via `_spaced(fn)`; smooths the per-symbol fan-out of the
   background jobs so they can't burst into a 429 on the single account key.
2. **`resilient_call`** + **`CircuitBreaker`** (`services/resilience.py`) — one shared
   `"alpaca"` breaker. A 429 anywhere opens it; opens short-circuit every Alpaca path
   for a 30s cooldown (raising `CircuitOpenError`, which callers swallow into graceful
   "no data"). Rate-limit errors are deliberately **not** retried.
3. **`TTLCache`** (`services/cache.py`) — in-process, lock-guarded, monotonic-clock TTL.

Two scheduler jobs drive the load (`main.py`, both 60s, staggered ~25s):
`jobs/refresh_watchlist.py` (15-symbol universe → quotes + chain volumes) and
`jobs/prewarm_hot_tickers.py` (top hot + ~50 liquid names → chain/chart/metrics).
The frontend layers React Query polling on top (`refetchInterval` 5–10s on quotes,
metrics, chain, combine status; 8s on working orders).

**Known limitations (the reason for this spike):**

| Limitation | Cause | Audit impact |
|---|---|---|
| ~15-min delayed equities | Free Alpaca tier = IEX feed, `feed=DataFeed.IEX` | #1 Market data = 3 |
| Open interest is a **volume proxy** | Free options "indicative" feed ships no real OI; we sum per-contract daily *volume* (`_populate_per_contract_volume`) and label walls as "options structure", not OI | #1, walls/max-pain/GEX credibility |
| Single free key gets rate-limited | One account key shared by all jobs; the breaker exists precisely because we hit 429s under load | #1, chart "Loading…" stalls |
| No live tick / no depth | 100% pull; no WebSocket anywhere in the codebase (`websockets` is only a transitive dep in `uv.lock`, imported by nothing) | #5 DOM, #7 fill realism, #3 volume profile |

There is **no WebSocket consumer anywhere today** — adding one is greenfield.

---

## 1. Provider comparison

Pricing and capabilities verified June 2026 against vendor pages and current coverage
articles (sources at the end of this section). Figures are USD/month for a single
**individual / non-professional** subscriber unless noted; professional or
redistribution use raises exchange license fees materially for every provider.

### 1.1 Alpaca — paid tiers

We already ship `alpaca-py` (one SDK, one key, one breaker). Upgrading the existing
account is the lowest-friction change.

| | Basic (today) | **Algo Trader Plus** |
|---|---|---|
| Price | $0 | **$99/mo** |
| Real-time equities | IEX only, ~15-min delayed via REST | **Full SIP, real-time**, all US exchanges |
| Real-time options | Indicative feed only | **Real-time OPRA** |
| Real open interest | No (volume proxy) | **Yes** (OPRA snapshots carry `open_interest`) |
| WebSocket streaming | Yes, but **capped at 30 symbols** | **Unlimited symbols**, stocks + options streams |
| REST rate limit | 200 req/min | Unlimited |
| Python ergonomics | Already integrated; `StockDataStream` / `OptionDataStream` live clients ship in `alpaca.data.live` | same |

**Note on SDK version:** the installed SDK is **`alpaca-py 0.21.0`**, whose
`alpaca.data.live` exposes only `CryptoDataStream` and `StockDataStream`.
`OptionDataStream` ships in newer alpaca-py — **options streaming requires a minor SDK
bump** (additive; the data clients we use are unchanged). Equities streaming works on
the installed version today.

### 1.2 Polygon.io (rebranded **Massive**, early 2026)

| | Stocks Starter | Stocks/Options real-time | Full (websocket-grade) |
|---|---|---|---|
| Price | ~$29/mo | ~$99/mo | ~$199/mo |
| Real-time equities | 15-min delayed at Starter | Real-time at higher tier | Real-time + WS |
| Real-time options | Separate Options plans; real-time tier ~$99 | — | — |
| Real open interest | **Yes** — Option Chain/Contract **Snapshot** endpoints return `open_interest`, greeks, IV, break-even | | |
| WebSocket | Real-time options + equities WS (trades, quotes, per-second & per-minute aggregates, FMV) at the upper tiers | | |
| Rate limit | Unlimited API calls on paid tiers | | |
| Python ergonomics | Mature REST + WS, good docs; **separate SDK + second key** to integrate (new client, new breaker scope) | | |

Strong data, **real OI**, clean snapshot model. The cost is a **second integration**
(new SDK/key alongside Alpaca, which we keep for trading/clock/news).

### 1.3 Databento

| | OPRA (options) | Equities (e.g. `XNAS.ITCH` / consolidated) |
|---|---|---|
| Live price | **OPRA Standard $199/mo** (usage-based live discontinued June 3 2025; legacy users grandfathered) | Subscription + pay-as-you-go historical ($/GB on uncompressed DBN; $125 free credits) |
| + Exchange license | **OPRA display fee ~$1.25–$1.50 per non-pro user/mo**, passed through at cost; pro/redistribution requires a formal venue license | Similar pass-through model |
| Real open interest | **Yes** — via instrument-definition / statistics schemas (OI + settlement) | n/a |
| WebSocket / live | Yes — single-subscription live gateway, **DBN binary** (zero-copy, ~6µs median venue→app); same interface as historical replay | Yes |
| Python ergonomics | `databento` SDK; powerful but **lowest-level** (binary DBN normalization, microstructure-grade); the most engineering to wire | |

Best-in-class fidelity and latency, **real OI**, honest license pass-through. **Overkill
for a paper-trading dashboard** that renders 5s-refresh quotes and daily-volume walls —
we'd pay enterprise complexity for microsecond data we down-sample anyway.

### 1.4 IEX Cloud — **dead, do not consider**

IEX Group **retired all IEX Cloud API products on Aug 31, 2024** (the business was
<2% of group revenue and lossmaking). All endpoints are off; accounts are inactive.
Listed here only to close the question: **IEX Cloud is not an option.** (Ironically our
free Alpaca feed already *is* IEX exchange data; the live IEX exchange feed persists,
but the developer-friendly Cloud product is gone.)

### 1.5 Also worth a mention (not recommended for this use case)

- **Financial Modeling Prep / Alpha Vantage / Finnhub** — common IEX-Cloud refugees;
  fundamentals-and-EOD-friendly, but **weak/absent real-time OPRA options + OI** and
  thin streaming. We already use Finnhub for news/earnings — not a market-data upgrade.
- **dxFeed / CBOE DataShop** — true exchange-grade options + OI, but enterprise pricing
  and contracts; wrong altitude for a paper-firm prototype.

### 1.6 Recommendation

**Adopt Alpaca Algo Trader Plus ($99/mo) as the single paid feed; keep Polygon/Massive
as the documented fallback if Alpaca OI/options quality disappoints in practice.**

Rationale:
- **One SDK, one key, one breaker.** We already run `alpaca-py` end-to-end (quotes, bars,
  chain, clock, news). $99/mo flips on **real-time SIP equities, real-time OPRA options,
  real open interest, and unlimited-symbol WebSocket** with effectively *zero new
  integration surface* beyond a stream consumer and an SDK bump for options streaming.
- It directly retires three of the four baseline limitations (delay, OI proxy, the
  single-key 429 ceiling — unlimited REST + a WS that replaces most polling).
- Polygon is the better *pure-data* product (cleaner OI snapshot, arguably better
  options coverage) and is the **escape hatch**: if Alpaca's OI/options prove flaky, the
  same `RealtimeFeed` seam ([§2](#2-target-architecture)) lets us drop in a Polygon
  adapter without touching read paths. Databento is reserved for a future where we need
  true depth/microstructure (it's the only one here that cleanly does Level-2 / full
  book) — not now.

**Sources:**
[Alpaca Market Data plans](https://alpaca.markets/data) ·
[Alpaca real-time stock data docs](https://docs.alpaca.markets/us/docs/real-time-stock-pricing-data) ·
[alpaca-py live data reference](https://alpaca.markets/sdks/python/api_reference/data/stock/live.html) ·
[Polygon/Massive pricing](https://massive.com/pricing) ·
[Massive Option Chain Snapshot (OI field)](https://massive.com/docs/rest/options/snapshots/option-chain-snapshot) ·
[Polygon Options API](https://polygon.io/options) ·
[Databento OPRA dataset](https://databento.com/datasets/OPRA.PILLAR) ·
[Databento new OPRA pricing plans](https://databento.com/blog/introducing-new-opra-pricing-plans) ·
[Databento live API](https://databento.com/live) ·
[IEX Cloud closure notice](https://iexcloud.org/) ·
[IEX Cloud shutdown analysis](https://www.alphavantage.co/iexcloud_shutdown_analysis_and_migration/)

---

## 2. Target architecture

**Principle: the read paths don't change shape.** `get_quotes` / `get_bars` keep their
signatures and return types. We insert one cache lookup at the *top* of each, served by
a background WebSocket consumer that maintains an in-memory "latest" store. On a miss (or
when the flag is off), the existing REST+cache path runs **unchanged**. Polling becomes
the fallback, not the primary.

### 2.1 Components

```
                          ┌──────────────────────────────────────────────┐
                          │  Provider WebSocket (Alpaca StockDataStream / │
                          │  OptionDataStream, full SIP/OPRA, real-time)  │
                          └───────────────────────┬──────────────────────┘
                                                  │ async push (trades, quotes, bars)
                                                  ▼
   ┌───────────────────────────────────────────────────────────────────────────────┐
   │  RealtimeFeed consumer  (asyncio task, started in main.py lifespan if flag on)  │
   │  • subscribe(symbols)  • on_quote/on_bar handlers  • reconnect w/ backoff       │
   │  • writes into LatestStore (thread-safe, bounded, last-value-wins per symbol)   │
   └───────────────────────────────┬───────────────────────────────────────────────┘
                                   │ writes
                                   ▼
                 ┌───────────────────────────────────────────┐
                 │  LatestStore (in-memory)                   │
                 │  latest_quote[symbol] -> Quote (+ ts)      │
                 │  latest_bar[(symbol,tf)] -> Bar (+ ts)     │
                 └───────────────────────────────┬───────────┘
                                                 │ reads (hot path, no network)
                                                 ▼
   ┌───────────────────────────────────────────────────────────────────────────────┐
   │  alpaca_client.get_quotes / get_bars   (UNCHANGED signatures)                   │
   │    if settings.realtime_feed_enabled:                                           │
   │        hit = LatestStore.latest_quote(sym)  # fresh within staleness window?    │
   │        if hit: return hit                    # ← served from stream, 0 network  │
   │    ... existing TokenBucket + resilient_call + TTLCache REST path (FALLBACK) ...│
   └───────────────────────────────────────────────────────────────────────────────┘
```

The stream **fills the same TTLCache keys** the REST path already uses (e.g.
`alpaca:snapshots:...`) *and/or* a dedicated `LatestStore`. Using the existing cache
keys means **existing consumers need no changes at all** — they read fresher data
through the identical code path.

### 2.2 How it composes with the existing guards

- **TokenBucket** — a WebSocket is **one** persistent connection, not per-symbol REST
  fan-out, so it bypasses `_spaced()` entirely. The bucket keeps governing the
  *fallback* REST calls. Net effect: the bucket is *less* contended because most reads
  now hit the stream → **fewer 429s, the single-key ceiling stops being the bottleneck.**
  (Connection setup / re-subscribe can optionally take 1 token to stay polite.)
- **CircuitBreaker** — reuse the shared `"alpaca"` breaker for the *fallback* REST path
  unchanged. Add a **separate** `"alpaca-stream"` breaker for the WS connection itself:
  N consecutive reconnect failures open it → the consumer stops hammering and the read
  paths transparently fall back to REST polling. A successful reconnect closes it. This
  keeps a flapping stream from masquerading as a healthy feed.
- **TTLCache** — the consumer is a *writer*; read paths stay readers. Stream-written
  entries get a **short staleness TTL** (e.g. 2–3s for quotes) so that if the stream
  silently stalls (no ticks, market quiet, or a half-open socket), entries expire and the
  read path falls through to a REST refresh — the cache TTL *is* the liveness guard.

### 2.3 Background consumer task

Started in the FastAPI **lifespan** (`main.py`), only when `settings.realtime_feed_enabled`:

```python
# sketch — not wired; see §7 for the actual stub
async def run_consumer(feed: RealtimeFeed, store: LatestStore) -> None:
    feed.on_quote(store.put_quote)        # last-value-wins per symbol
    feed.on_bar(store.put_bar)
    feed.subscribe(settings.watchlist_universe)   # seed; expand on demand
    await feed.run()                      # blocks; internal reconnect loop
```

- Runs as an `asyncio.create_task` so it never blocks lifespan startup (contrast the
  existing prewarm job's `_run_async`, which *does* block — we explicitly avoid that).
- On shutdown, lifespan cancels the task and calls `feed.stop()`.

### 2.4 Reconnection & backpressure

- **Reconnect:** exponential backoff with jitter (cap ~30s), driven by the
  `"alpaca-stream"` breaker. On reconnect, **re-subscribe the full symbol set** (the
  provider does not remember subscriptions across sockets). Until reconnect succeeds,
  read paths transparently serve from REST fallback — no user-visible outage.
- **Backpressure:** the consumer is **last-value-wins** — for quotes we only need the
  newest tick per symbol, so the store overwrites rather than queues. There is **no
  unbounded buffer**: a slow consumer drops intermediate ticks, it never grows memory.
  Bars are keyed `(symbol, timeframe)` and likewise overwritten on each new closed bar.
  This caps memory at `O(symbols)` regardless of tick rate — important for OPRA, whose
  full-market tick rate is enormous (we only ever subscribe to the symbols on screen +
  the watchlist universe, never the whole tape).
- **Options volume:** never subscribe to the entire OPRA firehose. Subscribe per
  *underlying's* on-screen chain (bounded contract count), and unsubscribe when the user
  navigates away. The daily-volume/OI aggregation that feeds walls stays a periodic REST
  snapshot job — streaming every contract tick to recompute walls is unnecessary.

### 2.5 Why a `RealtimeFeed` interface (not a hardcoded Alpaca stream)

A thin abstract `RealtimeFeed` ([§7](#7-optional-interface-stub)) with `subscribe`,
`latest_quote`, `latest_bar`, `on_quote`, `on_bar`, `run`, `stop` lets us:
- ship a **no-op default** so nothing changes while the flag is off,
- swap **Alpaca → Polygon** without touching `get_quotes`/`get_bars`,
- unit-test the read-path integration with a fake feed (deterministic, no network).

---

## 3. Migration path

Incremental, each step independently shippable and reversible. The flag
(`settings.realtime_feed_enabled`, default **False**) gates everything.

1. **Land the seam (this spike).** Add `RealtimeFeed` interface + `NoOpRealtimeFeed`
   default + the disabled flag. Imported by nothing. **Zero behavior change.** ← *here.*
2. **Upgrade the Alpaca account** to Algo Trader Plus ($99/mo). No code change required;
   the existing REST paths immediately return real-time SIP equities + real OPRA options
   + real `open_interest` once the key is entitled. *(This alone moves #1 from 3→~5 even
   before any streaming.)* Flip `get_chain_snapshot` to read real `open_interest` instead
   of the volume proxy (already a field on the row — `ContractRow.open_interest`).
3. **Implement `AlpacaRealtimeFeed`** behind the flag: wraps `StockDataStream`
   (+`OptionDataStream` after the SDK bump), writes into `LatestStore` / the existing
   cache keys, with reconnect + the `"alpaca-stream"` breaker.
4. **Wire the read-path lookup** at the top of `get_quotes` / `get_bars`, guarded by the
   flag, falling through to REST on miss/stale. Start the consumer in lifespan when the
   flag is on.
5. **Enable in staging**, verify quotes/bars match REST within tolerance and that
   stream-stall correctly falls back. Watch the `"alpaca-stream"` breaker + cache hit rate.
6. **Enable in prod.** Polling jobs stay running as the safety net — they now mostly find
   warm cache and make far fewer REST calls.
7. **(Later) Depth/DOM & volume profile** — once the stream is trusted, add Level-1 book
   / aggregated trade tape consumers feeding new UI (these are *additive* read paths, same
   pattern).

**What flips the flag:** a single `REALTIME_FEED_ENABLED=1` env var (one `Settings`
field). Off → `NoOpRealtimeFeed`, no consumer task, read paths behave exactly as today.

**Rollback:** set the flag to `0` (or unset) and redeploy/restart. The consumer task
isn't started; read paths fall back to the unchanged REST+poll path. No data migration,
no schema change, no client change. Because polling is never removed, rollback is
"stop reading the stream" — instant and total.

---

## 4. Audit impact

| # | Item | Now | After this work | What unblocks it |
|---|------|-----|-----------------|------------------|
| **#1** | Market data | **3** | **~6** | Step 2 (paid tier) alone retires the 15-min delay + the OI volume-proxy → real-time SIP + real OPRA OI. Streaming (steps 3–4) removes the single-key 429 ceiling and gives live ticks. We stop having to disclose "indicative" / "volume as an OI proxy." |
| **#7** | Fill realism | 4 | **~5 (enables higher later)** | Real-time NBBO bid/ask from the stream lets simulated fills price against a *live* spread instead of a delayed/last trade. Full fill realism (queue position) still needs depth (#5), but real-time top-of-book is the precondition. |
| **#3** | Volume profile | — | **enabled** | A live aggregated trade tape (per-price volume) becomes available off the stream; volume-by-price histogram is then an additive consumer + render. Not buildable on 15-min-delayed daily bars today. |
| **#5** | DOM / depth | — | **enabled (future step)** | Real-time top-of-book ships with the equities stream now; a true Level-2 ladder needs a depth feed — **Alpaca/Polygon give Level-1**; a real DOM is the case for **Databento** later (the §1.6 escape hatch). This spike makes the seam exist; depth is a follow-on. |

Net: the **headline unlock is #1 (3→~6)**, and the architecture turns #7/#3/#5 from
"impossible on the current feed" into "additive consumers on an existing stream."

---

## 5. Risks / open questions

- **Cost vs. value.** $99/mo is real recurring spend for a paper-trading prototype. It's
  justified *only* once we're demoing "real-time, real OI" as a differentiator (the audit
  explicitly flags the OI-proxy as a partner-conversation liability). Until then, the
  **seam ships free** and the subscription is a single flip when the demo needs it.
- **Options data volume.** OPRA is the highest-throughput feed in US markets. We must
  **never** subscribe broadly — only on-screen chains + the small watchlist universe, with
  last-value-wins and explicit unsubscribe on navigation. Mis-scoping a subscription could
  blow past connection/symbol limits or saturate the consumer. (This is the single biggest
  implementation footgun.)
- **Single-key vs. per-user keys.** Today there is **one shared Alpaca key** and one
  process-wide breaker — fine for a single-instance prototype. Algo Trader Plus is licensed
  per account; a true multi-user prop-firm with **per-user professional** market-data
  entitlements would change the licensing (and cost) picture substantially (pro subscriber
  fees, possible redistribution license). Open question to resolve before any multi-tenant
  launch: do we hold one firm-level non-display license, or per-seat entitlements? This
  affects provider choice (Databento's pass-through model is the most transparent here).
- **Stream/REST divergence.** Stream and REST can briefly disagree (different snapshot
  instants). The staleness-TTL + fallback design tolerates this, but any UI that shows a
  single authoritative number must pick one source; we standardize on **stream when fresh,
  REST otherwise** and never blend within a single field.
- **SDK bump for options streaming.** Installed `alpaca-py 0.21.0` lacks
  `OptionDataStream`. Equities streaming works now; options streaming needs an additive
  SDK upgrade — low risk, but it's a prerequisite to streaming the chain.
- **Provider lock-in / Polygon rename churn.** Polygon's 2026 rebrand to "Massive" (domain
  + docs moved) is a reminder that the fallback adapter is worth keeping warm; the
  `RealtimeFeed` interface is exactly the insurance.

---

## 6. Decision summary

- **Provider:** **Alpaca Algo Trader Plus, $99/mo** — one SDK/key/breaker we already run,
  flips on real-time SIP equities + real-time OPRA options + **real open interest** +
  unlimited-symbol WebSocket. **Polygon/Massive** is the documented fallback adapter;
  **Databento** is reserved for future true-depth/DOM; **IEX Cloud is dead** (shut down
  Aug 2024).
- **Architecture:** a flagged background WebSocket consumer maintains an in-memory
  last-value-wins store that `get_quotes`/`get_bars` read from on the hot path, falling
  back to the **unchanged** REST+TokenBucket+CircuitBreaker+TTLCache path on miss/stale.
  A dedicated `"alpaca-stream"` breaker + staleness-TTL make stalls self-heal into polling.
- **Migration:** seam (free, now) → upgrade account → implement feed → wire flagged lookup
  → staging → prod. One env var flips it; rollback is unsetting it. Polling is never
  removed.
- **Audit:** unblocks **#1 (3→~6)**, enables **#7 / #3 / #5** as additive consumers.

---

## 7. Optional interface stub

`backend/services/realtime_feed.py` ships alongside this doc as a **design seam only**:
an abstract `RealtimeFeed` (`subscribe` / `latest_quote` / `latest_bar` /
`on_quote` / `on_bar` / `run` / `stop`) plus a `NoOpRealtimeFeed` default and a
`get_realtime_feed()` factory gated on a disabled `realtime_feed_enabled` flag.

**It is imported by nothing, wired to nothing, and changes no existing path.** It exists
so the architecture above has a concrete shape to implement against, and so a future
Alpaca/Polygon adapter slots in without touching `get_quotes`/`get_bars`.
