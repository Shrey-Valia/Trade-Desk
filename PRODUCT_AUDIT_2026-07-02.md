# Full Product Audit — 2026-07-02

Scope: entire product (backend rules engine, execution, data feed, payments/auth, trading terminal, product shell) plus a feature-parity sweep against TopstepX and options-native platforms (Tastytrade, thinkorswim, Tradovate/NinjaTrader, TradingView, TradeZella).
Method: 6 domain code auditors + adversarial verification of critical/high findings + 2 web-research agents (35 agents total). Baselines at audit time: backend 657/657 pytest green, frontend 105/105 vitest green.

**Verdict:** the trading core is far stronger than the last audit cycle — MLL/DLL are genuinely enforced, the order-type suite is deep, and the terminal loop is real. The product's weak half is now the **funded stage and the business layer** (funded accounts can't fail, payouts don't debit, resets are free, the paywall has a bypass), plus a handful of **P&L-integrity holes** reachable from the UI, and a **data-freshness story** that undercuts the "real-time" promise.

---

## A. Money/P&L-integrity bugs (all adversarially VERIFIED)

| # | Finding | Evidence | Status |
|---|---------|----------|--------|
| A1 | **Journal PATCH allows arbitrary status rewrites** — a trader can PATCH a losing closed trade back to `open`/`cancelled` and erase the loss from the combine ledger (un-failing DLL usage), or self-fill a `working` order at their own limit price. Every risk rule is downstream of this ledger. | `journal.py:277` (no transition guard), `combine_state.py:114` (balance sums `status=='closed'` only) | CRITICAL |
| A2 | **FLATTEN/REVERSE overwrite accumulated scale-out P&L** — `_close_one` bare-assigns `realized_pnl` instead of accumulating; scale out 2/3 of a winner then hit FLATTEN and the booked slices vanish. Same bug class the accuracy audit fixed elsewhere. | `zerodte.py:1284` vs `order_monitor.py:942` (accumulates) | HIGH |
| A3 | **GTC zombie orders survive contract expiry** — 0DTE contracts die at the close but only DAY orders get expired; GTC orders (the ticket default) rest forever, can "fill" on a dead contract at a Black-Scholes-floor price, and eat the scaling cap. | `order_monitor.py:526-536`, `tradeTicket.ts:68` | HIGH |
| A4 | **Market single-leg orders fill at the click-time client-sent price** — the chain click freezes a price into the ticket; the backend fills AT it. Select at $1.50, wait for $3.00, hit BUY → instant fake edge. (The straddle path is server-priced; this path trusts the client.) | `zerodte.py:852` (`fill_ref = payload.entry_price`), `tradeTicket.ts:72-78` | CRITICAL |
| A5 | **Copy-trade mirror drops `stop_price` and `oco_group`** — mirrored buy stop-limits arm instantly, sells never arm; monitor-side cancels (OCO sibling, day-lock) never cascade to followers; mirror sizing ignores the follower's aggregate contracts cap. | `copy_trade.py:127-152`, `order_monitor.py:875` | HIGH |

## B. Funded stage & business model (the biggest product gap)

| # | Finding | Evidence | Status |
|---|---------|----------|--------|
| B1 | **Funded (passed) accounts can never fail** — both `outcome="failed"` sites are guarded on `outcome=="active"`. A funded trader below the MLL can re-open/get-liquidated in a loop forever. The stage where firm money is nominally at risk has liquidation but no termination. | `combine_state.py:281`, `order_monitor.py:761` | HIGH (verified) |
| B2 | **Payouts never debit the balance, and evaluation profits are immediately withdrawable** — payout books only a CombineEvent; balance/HWM/MLL keep counting the withdrawn money; the ~$3K used to PASS becomes an instant $2.4K payout on activation. Real firms re-baseline the funded account at start balance and debit every payout. | `combines.py:557-564`, `combine_objectives.py:31-39` | HIGH (verified) |
| B3 | **No payout policy** — no minimum, no winning-day gate, no buffer above the MLL, no cadence, no request history. One un-confirmed click books 100% of available. (Topstep: $125 min, 5×$150+ winning days, 50%-of-balance cap.) | `combines.py:477-565`, `PayoutsPage.tsx` | MEDIUM→HIGH |
| B4 | **Combine resets are free, unlimited, un-throttled** — the one money-adjacent endpoint without the financial limiter; full HWM/MLL re-baseline. In the Topstep model the reset fee IS the business. | `combines.py:448-474` | HIGH (verified) |
| B5 | **Paywall bypass** — `POST /api/combines/purchase` provisions for free unconditionally, even when Stripe is configured; entitlement is frontend routing convention only. | `combines.py:369-402` | CRITICAL (verified) |
| B6 | **"Billed monthly, cancel anytime" is advertised but nothing models a billing period** — no renewal, lapse, suspension, or cancel flow; Stripe checkout is dead code the frontend never calls and drops the pricing-path/split the user chose. | `NewCombinePage.tsx:311`, `payments.py:137` | HIGH (verified) |
| B7 | **No account recovery** — no password reset, no email verification, no password change. A forgotten password permanently orphans paid combines. | `auth.py:73-133` | HIGH (verified) |
| B8 | Reset ignores open positions (their P&L escapes eval accounting); archived combines keep settling on every list read; webhook fulfilment not concurrency-safe; landing page advertises **$4,000** 100K trail while the engine enforces **$3,000** (three drifting hardcoded tier tables). | `combines.py:448`, `combine_state.py:234`, `payments.py:148`, `LandingPage.tsx:159` | MEDIUM |

## C. Rules-engine deviations from the advertised (Topstep) convention

| # | Finding | Detail |
|---|---------|--------|
| C1 | **Trailing drawdown trails the all-time intraday realized peak, not EOD balance** — a +$3K morning given back by the close still permanently raises the floor $3K. Strictly harsher than the Topstep convention the marketing claims. (`combine_state.py:224-235`) |
| C2 | **DLL day-lock leaves the open book running** — after realized losses exhaust the DLL, open positions keep bleeding down to the MLL with no daily enforcement. Topstep semantics: DLL hit → flatten + lock. (`order_monitor.py:812-825`) |
| C3 | **MLL fail basis inconsistent** — lazy snapshot fails on realized-only while the monitor tests live equity; the stricter, less-correct one is terminal. (`combine_state.py:282` vs `order_monitor.py:718`) |
| C4 | Fill realism is one-sided — only user market opens pay spread/slippage; monitor fills, stops, and **auto-liquidation** (the most slippage-heavy fill in real life) execute at frictionless mid; limit triggers compare the MID not the touch. |

## D. Data feed (the "real-time" gap)

| # | Finding | Detail |
|---|---------|--------|
| D1 | **Option quotes refresh on a 5-minute cache product-wide** — the chain the trader stares at (polled every 10s), fills, stop triggers, and auto-liquidation marks all read `get_chain_snapshot` (TTL 300s). For ATM 0DTE that's a different market. (`alpaca_client.py:617-666`) |
| D2 | **Shared 2-worker timeout executor** — request handlers and 45s-per-minute jobs contend; a genuinely stuck SDK call permanently eats a worker; two stalls brick /bars & /chart until restart. (`timeouts.py:44-48`) |
| D3 | **Stall-guard only covers /bars & /chart** — /metrics, /detail, and the zerodte chain path (on the ORDER path) can still hang the whole app's threadpool. |
| D4 | **No freshness metadata anywhere** — server knowingly serves up-to-1-hour-stale candles with zero indication; no `as_of`, no stale badge. Table stakes for a paid terminal. |
| D5 | **Token bucket 6/s = 360/min vs the 200/min free-tier quota it claims to protect**; background jobs share the budget with interactive requests, no priority. (`alpaca_client.py:43`) |
| D6 | Degraded feed surfaces as **404 "no quote available"** on /detail (breaker-open → empty dict → 404); 0DTE search badge caches a TIMEOUT as "no 0DTE today" for 5 min (root of the known test flake); half-day early closes never surfaced (0DTE settles at 1pm with no warning); header VIX is a 1-2-day-old FRED close with a fake change%; prewarm warms retired "5D" timeframe (50 warnings/min, dead cache keys); TTLCache never evicts date-rotated keys (slow leak); enabling the realtime flag would silently break the stale-spot guard (Quote.as_of never mapped). |

## E. Trading terminal UX

| # | Finding | Detail |
|---|---------|--------|
| E1 | **CLOSE button + C-hotkey die when the analytics fetch fails** — exit path gated on a query the server doesn't even need (it recomputes P&L). During a feed stall the trader can't close the precise position but FLATTEN ALL still works — exactly backwards. (`BottomStrip.tsx:406-414,584`) |
| E2 | **Chain missing bid/ask and volume** — one blended mid hides the spread, which on 0DTE IS the trade; the min-OI filter asks users to filter on a number they can't see. |
| E3 | **Chain hard-fixed at ±5 strikes** — no widen control; the ±8 filter band and the virtualization path are unreachable dead features because one call site passes 5. (`RightChain.tsx:132`) |
| E4 | **QuickOrder cap math still uses the retired max-leg convention** — diverges from ticket and server (sum-of-legs); one-click orders bounce. (`RightChain.tsx:169-174`) |
| E5 | **Safety model inverted** — single-position close requires arm+confirm, but REVERSE ALL / FLATTEN ALL (and the ⌘K flatten) fire on one click. No F-F flatten / X-X cancel-all hotkeys (TopstepX day-one defaults). |
| E6 | Multi-leg StrategyBuilder unreachable until you select an unrelated single leg; TradeTicket counts contracts per TIER not per combine; hotkey intents fired off-terminal vanish silently then replay stale; dead components (PositionRiskStrip — a finished greeks/UPL band worth mounting, ModeToggle, SymbolSearch, useWatchlist). |

## F. Product shell

| # | Finding | Detail |
|---|---------|--------|
| F1 | **Journal & Analytics aggregate ALL combines** while the UI implies per-account data (CombineSwitcher does nothing, risk panel grades cross-account losses against one tier's MLL). Backend already supports `combine_id`. |
| F2 | **Price alerts only evaluate while on /positions** — evaluator lives in AlertsBell, mounted only in the terminal header. Sit on the Dashboard and alerts silently stop. Earnings/fill alert kinds are dead API surface. |
| F3 | **Accounts page never answers the core prop question** — no MLL cushion, no DLL remaining, no day-locked badge, no pass-progress chips per card (all data already in the payload). Follower accounts' distance-to-fail is invisible everywhere. |
| F4 | Dashboard claims funding is "a manual step" while the engine auto-funds; Payouts page has totals but no payout history; Analytics CSV export ignores the date-range filter; onboarding tour walks through terminal UI while auto-firing on the purchase page; session expiry mid-day strands the app signed-in-but-401ing. |

---

## G. TopstepX / competitor parity — what to build

**Already at or near parity** (verified in-repo): trailing MLL + DLL with live display, server-side auto-liquidation, scaling plan, consistency + min-days objectives, flatten/reverse-all, draggable SL/TP brackets, limit/stop/stop-limit/trailing/OCO + TIF, DOM-lite ladder, indicators + drawing tools, deep journal/analytics, trade copier (Topstep charges this as a feature — here it's built in), two pricing paths, command palette, onboarding tour, mobile shell.

**Gaps worth building (prioritized):**

| Priority | Feature | Source | Notes |
|----------|---------|--------|-------|
| P0 | **Personal Daily Loss Limit with enforcement modes** (Do Nothing / Liquidate / Liquidate & Block, same-day lock-in) + personal profit-target lock | TopstepX signature | DLL override exists; add the mode + enforcement in the monitor |
| P0 | **Payout realism** (min amount, winning-day gate, buffer, request history, debit) | Topstep XFA rules | Fixes B2/B3 at the same time |
| P0 | **Freshness/staleness surfacing** (as-of stamps, DELAYED/STALE pill, early-close banner) | table stakes | Fixes D4/D6 |
| P1 | **Theta burn clock** — per-position theta as $/hour with time-to-close countdown | 0DTE-native synthesis | Data already computed (position greeks) |
| P1 | **Expected move / remaining expected move pill** — from the live ATM straddle, shrinking into the close | ToS MMM / SpotGamma | ATM quotes already fetched |
| P1 | **Close at % of max profit** (premium-denominated TP/SL) | Tastytrade doctrine | Brackets are underlying-only today; options traders think in premium |
| P1 | **Bid×ask + volume in the chain**, strike-span control | every options platform | Payload extension + UI |
| P2 | Probability-of-profit / %-to-breakeven in ticket & chain; probability cone overlay | ToS/Tasty/Robinhood | BS math already in repo |
| P2 | Quantity presets on the ticket; order-event sound alerts | TopstepX | Small |
| P2 | Payoff/risk graph with T+0 line at order entry | Tasty Curve / ToS | MonteCarloPanel + BS payoff exist unmounted |
| P3 | The-Tilt-style aggregate positioning gauge, leaderboards, TopstepTV-style feed, market replay | engagement | Multi-user scale needed; not now |

---

## H. Implementation plan (this session)

Six workstreams on disjoint file clusters, then a feature wave, then full verification:

1. **RULES** — B1 funded-fail, B2 payout debit + funded re-baseline, B3 payout policy gates, B4 reset fee + limiter, B5 purchase gate when Stripe on, B8 archived-settle guard + dup constant.
2. **EXEC** — A1 PATCH whitelist, A2 flatten accumulate, A3 GTC expiry purge, A4 server-side market pricing, A5 copy-trade stop/oco/cascade/cap, C2 DLL day-lock flatten, chain payload bid/ask/volume.
3. **FEED** — D5 rate 6→3 + job/interactive split, D3 data-layer stall guard, D4 as_of/served_stale fields, D6 404→503 + early-close + prewarm fix + 0DTE error-cache fix.
4. **FE-TERMINAL** — E1 close ungate, E2/E3 chain columns + span control, E4 QuickOrder sum fix, E5 arm/confirm + F-F/X-X hotkeys, E6 PositionRiskStrip mount + dead-code delete + per-combine count.
5. **FE-SHELL** — F1 combine scoping + All-accounts toggle, F2 evaluator to shell, F3 account-card risk chips, F4 copy fixes + payout history + CSV range + tour gating, B8 tier-constants unification.
6. **FEATURES** (after 2 & 4) — PDLL enforcement modes, theta burn clock, expected move pill, close-at-%-max-profit.

Deferred (bigger bets, need a product decision): real-time options quotes via OptionDataStream (needs paid feed — previously ruled out), Stripe wiring + billing periods (stay-simulated decision stands), email infra for account recovery, D1 short-TTL quote plane, D2 executor rework, C1 EOD-trailing convention change.
