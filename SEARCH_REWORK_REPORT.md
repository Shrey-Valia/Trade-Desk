# Search rework — live catalog + live 0DTE check

Three phases, three commits, both AUDIT G-002 legs closed. The
ticker search now covers the entire active US-equity universe
(~13,000 symbols) instead of 16 hardcoded entries, and the
`0DTE TODAY` badge reflects what Alpaca's option-contracts endpoint
actually lists for today's date instead of a hardcoded
SPY/QQQ/IWM allow-list.

`tsc --noEmit` clean. **248/248** backend tests pass (225 prior +
11 catalog + 10 chain-availability + 2 net ticker_search).

---

## Phase 1 — Real symbol catalog
Commit: `bac87bc`

**Backend**
- `services/symbol_catalog.py` — new module wrapping the live
  Alpaca asset list. Single module-level `_catalog` tuple guarded
  by a lock. `refresh()` calls
  `TradingClient.get_all_assets(status=ACTIVE,
  asset_class=US_EQUITY)`, filters by `tradable + active`, sorts
  by symbol, swaps under the lock. Failures keep the prior
  catalog and log WARN; never raise. `search(q, limit)` uses the
  same `3.0 exact / 2.0 prefix / 1.0 substring / 0.5 name-substring`
  ranking the router shipped with.
- `routers/ticker_search.py` — drops the in-file `_CATALOG` tuple
  and delegates to `symbol_catalog.search()`. Response shape
  unchanged so the frontend doesn't refactor.
- `main.py` — APScheduler cron at **09:35 ET Mon–Fri** for daily
  refresh + `symbol_catalog.refresh()` added to the existing
  `_background_warm` so the live catalog populates on cold boot
  rather than waiting for the next cron tick. The boot timeline
  now shows the catalog warm completing right after
  `refresh_watchlist` + `prewarm_hot_tickers`.

**Tests**
- `tests/test_symbol_catalog.py` — 11 new tests covering: fallback
  loaded at import; empty / exact / prefix / substring /
  name-substring searches; limit cap; ranking-order regression
  against a synthetic 4-entry fixture; refresh returning empty
  keeps prior catalog; refresh raising keeps prior catalog;
  refresh populating with stubbed Asset objects.

**Verification — live**
After cold boot, log line:
```
2026-05-31 16:33:11 INFO [services.symbol_catalog] symbol_catalog: refreshed; 12929 entries
```
Sample queries against the running backend (with the catalog
loaded):
| query | top result | total hits |
|---|---|---|
| `BABA` | BABA Alibaba Group Holding | 8 |
| `palantir` | PLTR Palantir Technologies | 1 |
| `BRK` | BRK.A Berkshire Hathaway | 9 |
| `microsoft` | MSFT Microsoft Corporation | 3 |
| `TLT` | TLT iShares 20 Year Treasury Bond ETF | 7 |
| `VOO` | VOO Vanguard S&P 500 ETF | 4 |

The catalog is **12,929 entries** (excluding non-tradable rows).

---

## Phase 2 — Real 0DTE-availability check
Commit: `f6fa303`

**Backend**
- `services/chain_availability.py` — new module:
  - `has_zero_dte(symbol)` — single-symbol lookup. Calls
    `TradingClient.get_option_contracts(expiration_date=today_et,
    underlying_symbols=[sym], limit=1)`. Counts the response.
    Cached per `(symbol, today_iso)` for 5 minutes. Empty symbol
    short-circuits without an Alpaca call. On any exception
    returns False AND caches False so a flaky path doesn't
    re-hit on every keystroke.
  - `has_zero_dte_bulk(symbols)` — cache-aware batch path used by
    the router. Symbols already cached resolve synchronously;
    cold misses fan out via `ThreadPoolExecutor(max_workers=8)`
    with a **2-second per-batch deadline** so a single slow
    upstream call can't pin the whole search response. Per-symbol
    timeouts cache False so subsequent keystrokes don't re-hit
    the same slow path.

- `routers/ticker_search.py` — invokes `has_zero_dte_bulk` once
  per request, with the result symbols. Each `SearchHit` looks up
  its flag from the returned dict.

**Tests**
- `tests/test_chain_availability.py` — 10 new tests covering:
  True/False on contract presence; cache hit on repeat; negative
  results cached; cache keyed per-day (no bleed across NY day
  boundary); exception → False with no propagation; empty symbol
  short-circuit; bulk return shape; bulk cache fast-path skips
  already-cached symbols; bulk empty list.
- `tests/test_ticker_search.py` — updated to monkeypatch
  `has_zero_dte_bulk` so the suite stays hermetic against
  Alpaca. New tests: `test_zero_dte_flag_is_dynamic_from_chain_check`
  proves the flag now reflects the chain-check (not the static
  universe); `test_router_calls_zero_dte_bulk_once_per_query`
  fences the bulk batching against an N+1 regression.

**Cache discipline verified**
The TTL cache (`services.cache.TTLCache`) is the shared store. Key
shape: `has_0dte:{SYMBOL}:{YYYY-MM-DD}` with the date in NY time.
5-minute TTL means re-typing the same query stays free for the
duration of a session; the date suffix means the cache is
self-invalidating at midnight ET without code touching it.

**Live verification — chain endpoint**
Direct Alpaca probe (bypassing the cache) on three known expiry
dates around the test run:
| date | SPY | QQQ | AAPL | NVDA | BABA |
|---|---|---|---|---|---|
| 2026-05-29 (Fri, past) | 0 | 0 | 0 | 0 | 0 |
| 2026-05-31 (today, Sun) | 0 | 0 | 0 | 0 | 0 |
| **2026-06-01 (Mon)** | **1** | **1** | **1** | **1** | 0 |
| 2026-06-02 (Tue) | 1 | 1 | 0 | 0 | 0 |

On Monday the live check would correctly badge SPY / QQQ / AAPL /
NVDA but not BABA. Tuesday's data shows that AAPL/NVDA do NOT have
Tuesday-expiry contracts on Alpaca's listing (matches reality —
individual stock options typically expire on M/W/F or weekly
Fridays, not every weekday).

**Live verification — search response on Sunday**
All search hits correctly show `no 0DTE today` because no contracts
expire on Sunday. This is the production-correct behavior; on a
weekday with daily expiries (Monday) the badge would activate for
the symbols Alpaca actually lists.

---

## Phase 3 — Search UX polish
Commit: `0ae07c7`

**Frontend**
- `frontend/src/hooks/useTickerSearch.ts` — added a 200ms debounce
  on the query string. The catalog jumped from 16 to ~13,000
  symbols AND the 0DTE check now fans out to Alpaca per result;
  without a debounce, a fast typer fired N network round-trips
  for an N-character query, each round-trip triggering a
  chain-availability bulk call. The debounce absorbs the typing
  cadence; react-query's cache continues to serve repeated
  prefixes for free.
- `useDebouncedValue(value, delay)` — small inline hook,
  `clearTimeout` on unmount / value change.

**The rest of the polish ask was already satisfied** by the
existing `TickerSearchBox`:
- Result limit stays at 10 — fits the 220px-wide dropdown
  comfortably across all sample queries.
- Loading state — `isFetching ? "Searching…" : "No matches."` in
  the empty body.
- Empty state — "No matches." when results empty.

**Visual verification (screenshots committed)**:
- `screenshots/search_baba_live_catalog.png` — typing "BABA"
  shows: BABA / BABO / BABU / BABW / BABX / BBYY / KBAB / RYOJ.
- `screenshots/search_aapl_live_catalog.png` — typing "AAPL"
  shows: AAPL ranked first, then 6 derivative tickers.
- All flags correctly `no 0DTE today` on Sunday.

---

## Edge cases discovered

1. **Catalog refresh blocks behind earlier warm steps.** The
   background warm runs `refresh_watchlist` → `prewarm_hot_tickers`
   → `symbol_catalog.refresh()` sequentially. `refresh_watchlist`
   alone takes ~50s on a fresh boot (it hits Alpaca for option
   chain volumes per watchlist symbol). The catalog only populates
   after that completes. **Impact**: for ~2 minutes after a cold
   boot, search runs against the 16-symbol fallback. Users typing
   "BABA" during that window get an empty result. Acceptable for
   a single-user dev setup; production deployment should consider
   running the catalog warm in parallel with (rather than after)
   the watchlist refresh.

2. **`tradable=False` filter drops some symbols a curious user
   might search for.** Alpaca marks some symbols as `tradable=False`
   if Alpaca itself can't route an order to them (typically:
   foreign-listed ADRs that don't clear, halted issues, etc.).
   The catalog excludes them on purpose so the search results map
   to actually-tradable instruments. If we ever support
   non-tradable analysis, this filter would need to flip.

3. **Symbols with class designators (`BRK.A`, `BRK.B`) work as
   expected.** The catalog preserves Alpaca's symbol format, which
   includes the dot. Substring matching on "BRK" returns both
   share classes ranked first; on "BRK.A" returns only BRK.A.

4. **The 0DTE flag is correctly False on weekends.** No contracts
   expire on Saturday / Sunday so the chain-availability call
   returns zero contracts. The badge stays off across the board.
   Demo recording on a Monday morning will show the correct
   weekday behavior.

5. **First search after a 5-minute idle hits a cold cache.** Per
   the 5-minute TTL, returning users after a coffee break will
   trigger a fresh chain-availability fan-out on the first
   keystroke. Wall time is bounded by the ThreadPoolExecutor's
   2s deadline plus the debounce (200ms) for ~2.2s total — within
   acceptable interactive bounds.

6. **Alpaca's `tradable` field on the Trading client is best
   thought of as "Alpaca can trade this"**, not "the underlying
   instrument can be traded." For YC purposes this distinction
   doesn't matter — we're surfacing tickers the user could
   actually open a position on through us.

---

## Could-not-verify

1. **Live weekday 0DTE flag.** This run executed on a Sunday;
   `expiration_date=today` correctly returns zero contracts for
   every symbol. The live-Alpaca probe in the report (Monday +
   Tuesday) confirms the underlying call returns the right shape,
   but the in-app dropdown rendering of the badge **enabled**
   requires a weekday session.

2. **Live debounce visibility.** The 200ms debounce was verified
   to compile + ship; the user-facing "did it feel snappier or
   less spammy?" judgment needs an actual fast-typing pass on a
   loaded interface. The screenshots show the chrome behaving
   correctly but don't time-trace request frequency.

3. **Performance under sustained typing.** No load test was run.
   For a single user this is fine; production deployment with
   multiple concurrent users would want to validate the
   ThreadPoolExecutor's `max_workers=8` ceiling against the
   200-req/min Alpaca rate limit at peak.

---

## Git

```
$ git log --oneline -3
0ae07c7  Phase 3: Search UX polish for the larger catalog
f6fa303  Phase 2: has_0dte_today reflects actual chain availability, not hardcoded universe
bac87bc  Phase 1: Real symbol catalog via Alpaca assets endpoint
```

(Phase 1's commit also folded in the prior session's
TradingView-swap report + evidence screenshot — those files were
left untracked at the time and got picked up by `git add -A`.
Cosmetic; doesn't change Phase 1 substance.)

---

## Closing

Both AUDIT G-002 legs are now closed. Search is no longer "a
16-entry picker dressed as search" — it's a real ticker search
with a real 0DTE-availability gate. Demo flow for the YC video:
type "AAPL" → see AAPL with a "0DTE TODAY" badge (during weekday
session) → click → chain populates → ticket selects → BUY +1.
That whole flow now uses live data end-to-end.
