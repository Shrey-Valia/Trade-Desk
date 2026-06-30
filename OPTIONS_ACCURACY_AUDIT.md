# Trade Desk — 0DTE Options Accuracy Audit

**Date:** 2026-06-30 · **Branch:** `spike/drawing-tools` · **Commit:** `427d3f3`
**Method:** 8 skeptical auditors fanned across accuracy dimensions (expiry/dates, OCC symbols, pricing/greeks/IV, order fills, P&L accounting, chain integrity, risk gating) → every finding adversarially re-verified against the real code by an independent skeptic → synthesis. 39 raw findings, **36 confirmed/uncertain, 3 refuted.**

---

## VERDICT — Grade: **D**

**No — options trading is not accurately modeled, and the single most dangerous inaccuracy is that 0DTE positions are never settled at expiry.** A contract held to the 4:00pm ET bell is never booked to intrinsic, never realizes its win/loss, and stays `status="open"` forever — priced off a fabricated near-intrinsic mark (time floored at 60s) instead of true settlement. For a product whose entire reason to exist is 0DTE, the defining lifecycle event is simply absent.

Layered on top: stop-order fills are fabricated from a flat 30% IV guess, multi-leg commissions are undercounted by up to 4×, a scale-out final-close silently wipes out previously booked realized P&L, and `/reverse` bypasses the prop-firm risk gate entirely. These are not edge cases — they sit on the common path.

The math that **is** present (intrinsic payoff curves, per-leg gross P&L, slippage modeling) is mostly correct. The lifecycle and accounting around it are broken in ways that produce wrong money.

---

## CRITICAL

### 1. 0DTE positions are never settled at expiry — they live forever at a fabricated mark
`backend/services/order_monitor.py:248-356, 271-272, 729-755, 116-122` — **CONFIRMED** (three independent auditors agree)

**What's wrong.** There is no expiry/EOD settlement anywhere in the system. `run_order_monitor` early-returns `{"skipped":"market_closed"}` the instant the session ends, so it cannot run after 4pm to settle anything. The per-trade loop has exactly three close paths — working-order fill, SL/TP brackets, trailing stop — plus risk-floor auto-liquidation. None is expiry-driven. `close_reason="expiry"` is declared in the `CloseReason` literal (`schemas/journal.py:20`) but has **zero assignment sites**. No scheduled job settles positions either — `settle_combines` only re-baselines combine HWM, never touching `Trade.status`. Compounding it: time-to-expiry is floored at 60s in both `_t_to_close` (`order_monitor.py:121`) and `_intraday_analytics` (`journal.py:758-762`), so even a read-time valuation never reaches true T=0 intrinsic.

**Why it matters.** A trader who lets a 0DTE straddle ride to the close never has the gain or loss realized. An OTM contract that should settle worthless (−100%) and an ITM contract that should book intrinsic both stay "open" at a stale mark indefinitely. That phantom URPL keeps folding into combine balance, the MLL trailing floor, the DLL daily budget, and pass/fail progress — so the **entire account state is computed on positions that no longer exist**, and it permanently consumes the scaling-cap budget. Auto-liquidation can't even fire post-close because the monitor is gated off.

**Fix.** Add an EOD settlement pass that runs independent of `market_open()` (e.g. 16:00–16:05 ET, or at the top of each tick keyed on wall-clock ET). For every open trade whose nearest-leg expiry is at/after the 4pm ET close, book each leg at intrinsic against the 4pm settlement spot (`max(S-K,0)` / `max(K-S,0)` × sign × contracts × 100 − exit commission), set `status="closed"`, `close_reason="expiry"`, cascade `mirror_close`, and model ITM exercise/assignment explicitly. Use ET dates throughout.

### 2. Final close after a scale-out OVERWRITES accumulated realized P&L
`backend/routers/journal.py:284-287, 351` — **CONFIRMED**

**What's wrong.** `scale_out_trade` correctly *accumulates* each partial slice: `trade.realized_pnl = round((trade.realized_pnl or 0.0) + slice_realized, 2)` (line 351). But the final PATCH close recomputes realized for only the *remaining* contracts (the legs were already decremented by the scale-outs) and assigns it with a bare `=`: `trade.realized_pnl = round(realized, 2)` (line 287). It never adds to the running total.

**Why it matters.** Scale out of a winner — book +$800 on 2 of 3 contracts — then close the last contract for +$100, and you end with `realized_pnl = $100`, not $900. **$800 of already-booked profit silently vanishes** from the trade, journal, daily RPL, combine balance, HWM/MLL, and pass progress. A scaled-out loss is erased the same way. (A never-scaled trade is unaffected — likely why this slipped past testing.)

**Fix.** On final close of a position with prior accumulated realized, ADD instead of overwrite: `trade.realized_pnl = round((trade.realized_pnl or 0.0) + realized, 2)`. Track a `scaled` flag / closed-quantity so a fresh full close still sets the full number exactly once. Verify `mirror_close` doesn't propagate the wrong total to followers.

---

## HIGH

### 3. Working stop orders fill at a fabricated flat-30%-IV model price, not a real quote
`backend/services/order_monitor.py:133-148, 254-260, 670-677` — **CONFIRMED** (claimed CRITICAL, downgraded only because no real capital is at risk)

`_default_option_mark` prices every leg with `bs_intraday(spot, strike, t, rate, DEFAULT_IV, side)` where `DEFAULT_IV = 0.30` — a hardcoded guess, never the chain's implied IV. The production job `jobs/monitor_orders.py:20` calls `run_order_monitor` with no `option_mark` override, so the flat-IV mark is **always** the runtime path. For a STOP order, `fill_px = max(0.01, prem)` writes this fabricated premium straight into every leg's `entry_price` and `net_debit_credit`; the trigger crossing test uses the same mispriced mark. Real SPY 0DTE ATM IV is routinely 8–20% and BS price is extremely sensitive to sigma near expiry — a stop entry books a cost basis **that never existed in the market**. **Fix:** price the working-order mark from the live chain quote (or ATM-implied IV from `get_chain_table`); fall back to `DEFAULT_IV` only when no quote exists.

### 4. 0DTE chain greeks use the 1-DAY-floored engine, contradicting the prices in the same row
`backend/routers/zerodte.py:327-343` — **CONFIRMED**

The chain table prices each strike with `bs_intraday` (60s T floor) but computes the displayed delta/theta with `bs_greeks`, which floors T at `_MIN_T = 1/365` (a full day). The same `t_close` goes to both. Displayed theta **understates** the violent end-of-day decay that drives 0DTE P&L; delta is computed at the wrong T. A correct intraday engine — `greeks_intraday` — already exists in `intraday_analytics.py`. **Fix:** replace `bs_greeks` with `greeks_intraday()` at `zerodte.py:327-328`.

### 5. Commission counts only the largest leg — multi-leg trades undercharged by up to 4×
`backend/routers/journal.py:93-101, 548`; `backend/services/order_monitor.py:166-168` — **CONFIRMED** (two auditors)

All four commission sites compute `max((leg.contracts) for leg in legs) * commission_per_contract` — the MAX across legs, not the SUM. Gross-P&L math correctly iterates every leg, so the error doesn't cancel. A 1-contract iron condor pays $0.65/side here vs ~$2.60 at a real broker; a straddle pays $0.65 vs $1.30. Realized P&L on every multi-leg close is too rosy by `(L-1)×N×$0.65` per side and compounds into the MLL/DLL floors. **Fix:** `sum(...)` over legs in `_position_commission_side`, `_commission_side`, `_default_unrealized_for`, and the `journal.py:545` block; scale-out exit commission should be `qty × num_legs × rate`.

### 6. Monitor's option mark always treats expiry as TODAY — mis-prices every future-expiry position
`backend/services/order_monitor.py:116-148` — **CONFIRMED**

`_default_option_mark` computes time-to-expiry as `_t_to_close(now)` = seconds to *today's* 4pm ET, never reading `leg["expiry"]` — even though the legs carry it and the close-P&L path reads it correctly. zerodte falls back to the nearest future expiry when no same-day chain exists (`zerodte.py:166-169`), so this triggers in practice. A position on a 5-day expiry is priced as if it expires today, collapsing days of time value; this mark drives working-order fill triggers, the recorded stop fill price, and trailing-stop triggers. **Fix:** make `_t_to_close` read `leg["expiry"]`, mirroring `journal.py:751-761`; use per-leg T for multi-expiry.

### 7. `/reverse` opens fresh positions without the risk gate — FAILED/day-locked combines keep trading
`backend/routers/zerodte.py:1218-1293` — **CONFIRMED**

`reverse_positions()` flattens every open position and re-opens the opposite side as brand-new Trades, but calls only `_require_market_open()`. It never calls `_require_tradeable()` (403s on FAILED combine / day-lock, 422s on scaling-cap overflow) and never runs `_clamp_contracts_to_cap()`. A trader on a FAILED 50K combine, or day-locked after the DLL, can press Reverse and instantly hold a full new opposite-side 0DTE book — defeating the prop-firm fail/day-lock and scaling-cap rules. **Fix:** call `_require_tradeable(session, combine, contracts=<sum of reversed leg sizes>)` and run each reversed trade through `_clamp_contracts_to_cap`. Treat reverse exactly like an open.

### 8. Position closed after expiry day settles at the next live spot, not the 4pm expiry spot
`backend/routers/journal.py:152-178` — **CONFIRMED**

Once expiry day passes, `_trade_is_zerodte` is False and close takes the multi-day branch, where `T_now = 0` for an expired leg, so `bs_price` returns intrinsic — but against the **current live spot**, not the 4pm expiry spot. There is no stored 4pm settlement price anywhere. A call that expired OTM Friday but gapped up over the weekend is booked as profitable when closed Monday. Reachable precisely because of finding #1 (positions left open past expiry). **Fix:** snapshot and persist the 4pm ET settlement spot per expiry; settle expired legs against that frozen spot.

### 9. IV-rank history is a median over ALL strikes and ALL expiries, not ATM IV30
`backend/jobs/collect_options_chain.py:47-83` — **CONFIRMED** (live impact deferred until the 60-day window fills)

`collect_options_chain` stores every contract of every expiry (0DTE through LEAPS) and every strike. `_historical_iv30` takes the per-day median across all of them and treats it as "ATM IV30." Today's numerator (`_atm_iv`) is correctly ATM-near-term, but the historical denominator has no strike/expiry filter — making IV-rank/percentile non-comparable and not IV30 at all. **Fix:** store only ATM near-term IV at collection time, or filter by strike-proximity + near-term expiry.

### 10. DTE for multi-day positions uses a UTC date while 0DTE uses ET — loses a day of value every evening
`backend/routers/journal.py:583-589, 711-726` — **CONFIRMED**

`get_trade_analytics` computes `today = datetime.now(timezone.utc).date()` and feeds it into `T_now`, while `_trade_is_zerodte` uses `datetime.now(_ET).date()`. From ~7–8pm ET until ET midnight the two disagree, asymmetrically in the dangerous direction: a 1DTE position the night before expiry is marked as if it already expired (intrinsic only), understating its mark by the entire remaining extrinsic value. **Fix:** use `datetime.now(_ET).date()` in `get_trade_analytics` (and `journal.py:691`).

---

## MEDIUM

- **Held-past-close 0DTE marks at floored 1-min-to-expiry** — `journal.py:758-762`. ~$5/contract phantom time value from the 4pm bell to ET midnight. Compounds with #1. **Fix:** set `t_now=0` when `total_seconds - elapsed_seconds <= 0`.
- **After-hours positions marked with stale floored-T BS value as "live" P&L** — `journal.py:744-865`. Stale 16:00 spot + 60s T floor presented as live UP&L all evening, no settled-state transition.
- **Multi-leg analytics assume all legs share `legs[0]`'s expiry** — `journal.py:750-762`. Calendars/diagonals with a near 0DTE leg route the far leg through T≈0. **Fix:** per-leg T in `_portfolio_value`/greeks.
- **MTM marks all legs with one frozen entry-implied IV** — `journal.py:764-808`, `position_analytics.py:149-175`. IV crush/spike after entry invisible; put/call skew erased. Affects booked realized on close. **Fix:** mark each leg to its live option-quote mid when available.
- **Chain table displays the ASK as the contract price (mid branch is dead code)** — `zerodte.py:213-223`. `_quote_price` returns ask whenever ask>0; the `(bid+ask)/2` branch is unreachable. ATM IV back-solved from the ask runs hot, inflating the whole modeled surface. **Fix:** test the mid branch before the ask-only fallback.
- **Working limit/stop triggers compute against the flat-30%-IV model** — `order_monitor.py:133-148, 653-674`. Same root cause as #3 (the *timing* half). Triggers fire at the wrong time vs the real market.
- **One-sided quote lets a market BUY fill at the bid / SELL at the ask** — `zerodte.py:462-473`. `_pick_fill_price` sets `spread=0` and fills at the lone price; common on wide far-OTM 0DTE near the close. **Fix:** synthesize a touch spread, bias to the missing side.
- **Single underlying-level SL/TP can only protect one side of a short straddle/strangle** — `order_monitor.py:184-192, 742-754`. A short straddle at 500 with `stop_loss=505` never trips on a drop to 490; only MLL/DLL auto-liquidation backstops it. **Fix:** evaluate brackets as a distance band for market-neutral structures.
- **Monitor + intraday pricing hardcode 4:00pm close — mis-price every 0DTE on NYSE half-days** — `order_monitor.py:116-122`, `zerodte.py:62-80, 256-263`, `journal.py:708/756`. ~9 early-close (1pm) days/year get ~3h of fictitious theta, despite half-day-aware infra in `services/market_calendar.py`. **Fix:** drive close from the NYSE schedule's `market_close` in all three sites.
- **Expected-move ATM straddle mid falls back to stale `last` and a one-sided quote** — `expected_move.py:56-61`. ±1σ EM band can be built from a yesterday print or a half-quote. Display annotation only.
- **ATM strike selected against last-trade spot with no staleness guard** — `zerodte.py:155-175`. `/chain` not gated by `_require_market_open`; uses `Quote.price` (any session) with no timestamp. After an overnight gap the ATM strike/IV/EM bands anchor to a stale print. Order entry is safe (opens are gated).
- **Scaling cap counts a position as its largest leg, undercounting true contract exposure** — `zerodte.py:491-512, 560-561`. A 5-lot straddle (10 real contracts) counts as 5 vs a tier cap of 5. Internally consistent with the "1 contract = 1 structure" convention but diverges from true risk. **Fix:** sum leg contracts (and mirror in `TradeTicket.tsx`), or document the convention.
- **Open-path risk gate ignores open-position URPL — relies entirely on the ~20s monitor** — `combine_state.py:242-265, 282-283`. `_require_tradeable` computes day-lock/FAILED from *realized only*. A combine deep past its DLL/MLL on a mark-to-market basis can keep opening until the next monitor tick. Backstopped by `_auto_liquidate`. **Fix:** fold live open-position URPL into the order-time balance/DLL test.
- **Market opens fill against a chain snapshot cached up to 5 minutes, no freshness check** — `zerodte.py:442-473, 633-640`. `ContractRow` carries no timestamp; a fill can be priced off a 5-min-stale quote. Indicative-fill simulator (no broker mis-execution) but recorded entry/P&L drift. **Fix:** stamp snapshot fetch time, refuse/widen stale fills, require two-sided quotes.
- **0DTE theta is a full-1-day finite-difference step that saturates at the 60s floor** — `intraday_analytics.py:99-102`. Quoted per-day theta is essentially `−(remaining extrinsic)`, meaningless as a *rate*. (Auditor's "more negative than the option's value" claim is false — `|theta| ≤ value(now)` always.) Advisory display metric. **Fix:** scale a sub-day step back to per-day, or relabel.

---

## LOW

- **Expected-move `_mid` returns a lone bid/ask as the leg "mid"** — `expected_move.py:56-61`. Docstring claims "larger of bid/ask" — false (`bid or ask` returns bid-if-truthy). **Fix:** return None when only one side quotes.
- **Only flat $0.65/contract commission modeled — no exchange/ORF/regulatory fees** — `config.py:95`. Paper P&L a few cents/contract rosy. Material only at high trade counts; risk engine reads net P&L separately.
- **OCC date parse assumes 20xx (`%y%m%d`) with no century pin** — `alpaca_client.py:587`. Parse-only (never builds OCC symbols), all live options 20xx — no triggerable defect today. **Fix:** pin `2000 + int(date_str[:2])` and validate.
- **Chain window goes asymmetric when ATM sits near the listed-strike edge** — `zerodte.py:274-280`. Cosmetic; each shown strike is still correct.

---

## PRIORITIZED FIX ORDER

1. **Expiry/EOD settlement pass** (CRITICAL #1) — root of the whole 0DTE story; also resolves the held-past-close, after-hours-stale, and post-expiry-settlement-spot findings downstream.
2. **Scale-out final-close overwrite** (CRITICAL #2) — one-line `+=` fix; stops silent loss of booked money today.
3. **Live-chain IV for working/stop marks** (#3) — kills the fabricated stop fill price and the mistimed triggers.
4. **Commission `max` → `sum`** (#5) — trivial, deterministic money fix across 4 sites.
5. **`/reverse` risk gate** (#7) — add `_require_tradeable` + cap clamp.
6. **UTC→ET date for multi-day DTE** (#10) + **per-leg expiry in monitor/intraday marks** (#6).
7. **Chain greeks → `greeks_intraday`** (#4) + **`_quote_price` mid** — display correctness, near-trivial.
8. **IV-rank ATM filter** (#9, deferred) — fix before the 60-day window fills and surfaces a garbage percentile.
9. NYSE half-day close, two-sided-quote guards, URPL-aware gate, scaling-cap basis, theta scaling — MEDIUM cleanup.
10. Regulatory fees, OCC century pin, chain-window symmetry — LOW, opportunistic.

---

## WHAT IS NOT BROKEN (don't waste time here)

The intrinsic-value **expiration payoff curve** is computed correctly from true intrinsic; **per-leg gross P&L and cost-basis math** correctly iterate all legs; the **slippage model** (`_fill_slippage` / `_pick_fill_price`) is sound for two-sided quotes; the **today's-ATM-IV30 numerator** (`_atm_iv`) is correctly ATM-near-term; **`_auto_liquidate`** does correctly include URPL in its MLL/DLL floor tests; and the **OCC parse** has no triggerable defect with current data. Commissions *are* modeled (the bug is summation, not absence).

---

---

## FIX STATUS (branch `fix/options-accuracy-audit`, 649 tests green)

### ✅ Fixed + tested
- **CRITICAL #1 — expiry settlement.** New `settle_expired_positions` in `order_monitor.py` books open positions to intrinsic at the 4pm/half-day close (independent of `market_open()`), `close_reason="expiry"`, records the settlement spot, cascades `mirror_close`. Wired into the monitor's market-closed branch. Subsumes the post-expiry-settlement-spot finding (#8). 8 new tests.
- **CRITICAL #2 — scale-out overwrite.** Close paths in `journal.py` and `_book_close` now `+=` accumulated realized.
- **HIGH #3 — fabricated IV marks / #6 expiry-as-today.** `_default_option_mark` reworked: live chain-quote mid per contract, model fallback at the **leg's own** expiry (half-day aware). 2 new tests.
- **HIGH #5 — commission max→sum** across all 4 sites + scale-out exit. Test helpers fixed to track production.
- **HIGH #7 — /reverse risk gate.** Now calls `_require_tradeable` + clamps to the scaling cap. 2 new tests.
- **HIGH #10 — UTC→ET DTE** at all 3 journal sites.
- **HIGH #4-chain — chain greeks** now use `greeks_intraday` (1-min floor), not the day-floored `bs_greeks`.
- **HIGH #9 — IV-rank** now filters to each day's near-term ATM (|delta|≈0.5) contracts.
- **MEDIUM — chain `_quote_price`** returns the two-sided mid before the ask-only fallback. 1 new test.
- **MEDIUM — one-sided fills** synthesize a 2% touch spread so the aggressor pays. 2 new tests.
- **MEDIUM — half-day closes** in `order_monitor`, `zerodte`, `journal` route through the NYSE schedule (`market_calendar.session_close_et`).
- **MEDIUM — held-past-close / after-hours mark** → `t_now=0` (settlement intrinsic) once past the expiry close.
- **MEDIUM — 0DTE theta** reports remaining decay-to-expiry instead of a 60s-saturated 1-day step.
- **MEDIUM — expected-move `_mid`** drops the lone-bid/ask fallback (two-sided or last only).
- **LOW — OCC century pin** explicit `2000+YY` with validation.

### ✅ Fixed + tested — second wave (the previously-deferred items)
- **Scaling cap now counts TOTAL contracts (sum of legs).** *Decision: total-contracts convention.* `_open_contracts_for_combine` sums legs; `/open` straddle gates on 2×, `/open-multi` on base×Σratios, `/reverse` on Σ legs; `TradeTicket.tsx` updated (sum legs + straddle 2× in the cap check). +2 tests.
- **Two-sided brackets** for short-vol structures (short straddle/strangle, iron condor/butterfly): the stop is a distance band (a big move EITHER way triggers it). Directional strategies unchanged. +3 tests.
- **Per-leg expiry in journal intraday analytics** — each leg prices off its own expiry close (calendars/diagonals); single-expiry reduces to identical numbers. +1 test.
- **Order-time gate is mark-to-market aware** — `_require_tradeable` folds live open-position URPL into the MLL/DLL test (resilient: degrades to realized-only if pricing is cold). +2 tests.
- **Quote/chain freshness** — `as_of` (last-trade timestamp) on `Quote` + `ContractRow`, populated at fetch; a stale-spot guard (`max_spot_staleness_s`) refuses opening against a halted/illiquid print. +1 test.
- **Regulatory/exchange fees** — `regulatory_fee_per_contract` folded into `settings.per_contract_fee`, applied to entry+exit everywhere commission is.
- **Half-day session close** routed through the NYSE schedule (already done first wave).

### ⏸ Still deferred (cosmetic / not worth the churn)
- **Chain-window asymmetry (LOW)** — cosmetic; each shown strike is still correct.
- **MTM journal analytics still uses entry-implied IV (vs live option quotes).** Deliberate documented design; the *monitor* working/trailing mark already uses live chain quotes. Marking the journal payoff panel to live option quotes is a larger, lower-value rework left for a future pass.

---

## REFUTED (verified NOT bugs — don't chase these)

- **`_MIN_T=1/365` floor distorting 0DTE journal pricing** — refuted. 0DTE positions ALWAYS route to the intraday path (`_trade_is_zerodte` gate at `journal.py:137/517`); the day-floored engine never sees a hours-of-premium-left 0DTE position.
- **DAY working-order expiry UTC-vs-ET off-by-one** — refuted. `_et_date()` converts to ET before taking the calendar date; same-session orders are never cancelled, and the monitor doesn't run on closed days.
- **Scale-out re-folds full ENTRY commission into every slice** — refuted. The slice fraction divides by the same contract count the commission base uses, so entry commission is charged exactly once across slices (balanced case error = $0.00). The residual imbalanced-multi-leg case is the separate `max`-vs-`sum` commission issue (#5), not this mechanism.
