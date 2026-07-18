# Gap Analysis — What the Prop Firm Is Missing

**Date:** 2026-07-13 · **Method:** 22-agent workflow — 6 codebase mappers, 3 competitor-benchmark researchers (Topstep/Apex/MFFU/Tradeify/FTMO/FundedNext/The5%ers + prop-firm ops + options-specific mechanics), 6 gap analysts, 6 adversarial verifiers that grepped/read the code to confirm each claim. 95 verified gaps (claims found to already exist were dropped).

Scope: **missing capabilities**, not bugs — prior audits (PRODUCT_AUDIT_2026-07-02, 2026-07-08 re-audit) covered correctness.


## Trader lifecycle & prop rules


### P0 — cannot operate as a real business without it


#### Admin / operator back office  `[P0 · effort L · verified missing]`

Build a role-gated operator surface: an is_admin/role column on the user model, admin-only FastAPI router (backend/routers/admin.py) and React pages for (a) user search/detail with session + combine history, (b) combine adjustment tools (manual fail/un-fail, balance adjustment with mandatory combine_events audit rows, extend paid_through, grant reset credits), (c) event-ledger search across combine_events, (d) breach dispute annotations. Today every ops action is either automatic or impossible — grep for 'admin' across backend/routers, services, models finds nothing.


**Why it matters:** A prop firm is an operations business: rule disputes, refunds, goodwill adjustments, and abuse bans are daily work. With no back office the operator's only tool is sqlite3 against the production DB, which defeats the append-only audit ledger the platform already built.


**Industry benchmark:** A vertical 'prop-firm OS' market exists precisely for this (FPFX Tech, YourPropFirm, Propriotec, Trade Tech Solutions); every real firm runs a CRM/admin layer, and transparent back-office tooling measurably cuts support load.


**Verification evidence:** backend/models/user.py (read in full): User has email/password_hash/display_name/active_combine_id/copy_lead_combine_id/reset_credits/DLL-settings only — no is_admin/role column. backend/main.py:456-472 include_router list has 17 routers, no admin router; backend/routers/ has no admin.py. grep -rli 'admin' across backend/*.py (excl. pycache/tests) returned zero product files. frontend/src/pages/ contains 11 pages (Accounts, Analytics, Dashboard, Journal, Landing, NewCombine, Payouts, Positions, Settings, SignIn, SignUp) — no admin/operator page; grep 'admin|operator|backoffice' in frontend/src empty.


#### KYC / identity verification gate before first payout  `[P0 · effort L · verified missing]`

Add a verification state machine on the user (unverified → pending → verified → rejected), a document+liveness provider integration point (Sumsub/Veriff/iDenfy-style webhook handler; can be a stub adapter while sim-only), sanctions/geo screening (OFAC country blocklist at signup and at payout), and a hard gate in POST /api/combines/{id}/payout (backend/routers/combines.py) requiring verified status before the first payout request. Frontend: verification prompt card on PayoutsPage.tsx.


**Why it matters:** The industry pattern is frictionless purchase but mandatory identity verification before money leaves the firm — payment rails impose BSA/AML obligations the moment real disbursement exists. Without even the state machine, the platform cannot flip payouts from simulated to real.


**Industry benchmark:** Universal across FTMO, FundedNext, Topstep, Apex: no KYC at signup, ID verification (1–3 days, Sumsub-style) required before funded status/first payout. The 2025 GENIUS Act extended BSA/KYC to stablecoin payout rails, closing the crypto loophole.


**Verification evidence:** grep -rniE 'kyc|sumsub|veriff|ofac|sanction|idenfy|liveness' across backend/ and frontend/src hit only health-probe 'liveness' comments (backend/main.py:477, backend/services/realtime_feed.py:190). POST /api/combines/{id}/payout (backend/routers/combines.py:661-810, read in full) gates only on funded, activation fee, 5 winning days, min $125, available balance, 24h pacing, MLL floor — no verification state. backend/models/user.py has no verification fields; frontend/src/pages/PayoutsPage.tsx grep for 'verif|kyc' returned nothing.


#### Trader agreement acceptance and e-sign at funding  `[P0 · effort M · verified missing]`

Two-layer legal machinery: (1) versioned ToS/risk-disclosure acceptance at signup and at combine purchase (agreement_acceptances table: user_id, doc_version, timestamp, IP), re-prompted when the doc version bumps; (2) a funded-account agreement e-sign step inserted into the activation flow (POST /api/combines/{id}/activate-account currently charges $149 and flips state with no contract), establishing the trader as an independent contractor on simulated capital. Grep for kyc/agreement/verification in the codebase finds nothing.


**Why it matters:** Payouts framed as performance rewards on demo accounts only survive legal scrutiny if a signed agreement exists; without recorded acceptance the firm has no enforceable rulebook to point to when denying a payout or terminating for abuse.


**Industry benchmark:** FTMO signs the 'FTMO Account Agreement' post-verification before FTMO Trader status; all four major CFD firms use e-sign agreements at funding; US firms collect contractor agreements via Rise/Deel automatically.


**Verification evidence:** grep -rniE 'agreement|terms of service|tos|e-sign|disclosure|contractor' across backend/ and frontend/src returned only incidental hits (e.g. 'stripe-signature' header, 'Design notes' comments). No agreement_acceptances table in backend/models/ (listing: user, combine, combine_event, payment, trade, alert, auth_session, etc.). frontend/src/pages/SignUpPage.tsx, NewCombinePage.tsx, components/auth/AuthCard.tsx contain no terms/agree/accept text. The activate-account endpoint (backend/routers/combines.py, immediately after the payout endpoint at ~line 817) charges the $149 fee with no contract step.


#### Payout method and tax document collection  `[P0 · effort M · verified missing]`

Model layer for disbursement even while money movement stays simulated: payout_methods table (ACH routing/account, wire, crypto wallet address — typed per rail, one default per user), a W-9/W-8BEN collection step (store classification + year, gate first payout on it), and yearly 1099-NEC aggregation (sum approved payouts per user per calendar year, $600 threshold flag). Wire the payout request modal in frontend/src/pages/PayoutsPage.tsx to require a method on file. Disbursement execution can remain a no-op adapter per the standing sim decision.


**Why it matters:** A payout request today has no destination and no tax posture — the firm literally could not pay a passing trader or file required information returns. This is the difference between a demo and a business that can flip the 'real money' switch.


**Industry benchmark:** US traders are 1099-NEC independent contractors (W-9 at onboarding, issued at $600+/yr); non-US file W-8BEN. Firms run 2–3 rails in parallel (Rise, Deel, Wise, ACH/wire, USDC) because each has country gaps.


**Verification evidence:** grep -rniE 'payout_method|w-9|w9|w-8|1099|routing|ach' across backend/ and frontend/src returned only unrelated hits (comments about 'each'). backend/models/ has no payout_methods or tax model. frontend/src/pages/PayoutsPage.tsx payout modal (~lines 220-276) collects only an amount and confirms — no method-on-file requirement; grep 'method|tax|w-9' in that file matched nothing relevant.


#### Human payout adjudication workflow (approve / deny / hold)  `[P0 · effort M · verified missing]`

Replace the unattended timer (jobs/settle_combines.approve_pending_payouts auto-approves anything older than PAYOUT_REVIEW_WINDOW_H) with a real queue: payout states requested → under_review → approved | denied | held, a denial-reason taxonomy (rule-breach categories, abuse flag, verification incomplete), refund-the-debit logic on denial (the debit is booked at request time in combine_state.py payouts_booked), trader-visible status + reason on PayoutsPage.tsx, and an appeal note field. Auto-approve can remain as a configurable fallback for clean accounts.


**Why it matters:** Payout review is where prop firms actually enforce their rules — denials cluster into ~12 documented TOS categories industry-wide. An auto-approving timer means the firm pays out group-passers and stale-quote exploiters with zero human checkpoint on its single most sensitive money flow.


**Industry benchmark:** Industry enforcement pattern is human review + audit trail before any denial/ban; Topstep/Apex/MFFU all run manual first-payout review (first payout slowest, later ones 24–48h).


**Verification evidence:** backend/jobs/settle_combines.py:16-100: approve_pending_payouts auto-approves any 'payout_requested' older than PAYOUT_REVIEW_WINDOW_H (default 1.0h, line 35) with positional matching — exactly the unattended timer the claim describes. Only two payout states exist ('payout_requested'/'payout_approved', see event-type literal at backend/routers/combines.py:193-195); grep -rniE 'under_review|denied|held|appeal' found no payout-state hits in product code. No denial taxonomy, no refund-the-debit path (debit booked at request in combine_state PAYOUT_DEBIT_TYPES, combine_state.py:226), no reason display on PayoutsPage.tsx.


### P1 — industry table stakes; traders churn without it


#### Inactivity / dormancy rule and activation deadline  `[P1 · effort M · verified missing]`

Three timers, all absent today: (1) funded-account inactivity — require ≥1 execution-origin trade every N days (config, e.g. 14–30) on funded+activated combines, with a warning event at N-7 and auto-archive at N (extend backend/jobs/renew_combines.py or a new daily job; a funded account currently lives forever with billing frozen via the funded_frozen branch); (2) activation deadline — a passed combine must call activate-account within e.g. 7–14 days of funded_at or it archives; (3) eval dormancy is already economically handled by monthly rebill, so exclude it. Surface countdowns on DashboardPage/AccountsPage.


**Why it matters:** Funded accounts are the firm's open-ended liability; with billing frozen and no dormancy rule, every passed account is a perpetual free claim on the firm. Traders also game deadline-free activation by warehousing passed accounts.


**Industry benchmark:** Sim-funded accounts industry-wide require a trade every ~7–30 days or close; Apex enforces a 7-day PA activation deadline; monthly PA/data fees enforce activity elsewhere.


**Verification evidence:** grep -rniE 'inactiv|dormant|deadline' across backend/ and frontend/src matched only network-timeout 'deadline' comments and 'dormant feature-flag' notes. backend/jobs/renew_combines.py (read) handles only billing renewal/archival at paid_through and explicitly SKIPS funded accounts (funded_frozen counter, lines 124-171) — confirming a funded account lives forever with billing frozen. No job or endpoint checks last-trade recency; no deadline on combine.funded_at for activation (backend/models/combine.py:62-87 has funded_at/funded_activated_at with no expiry).


#### Funded-stage consistency rule at payout  `[P1 · effort S · verified missing]`

Re-apply the existing best-day check at the payout gate: in POST /api/combines/{id}/payout (backend/routers/combines.py), compute realized profit by 5pm-PT day since funded_epoch_at (machinery already exists in combine_state.realized_by_trading_day and combine_settlement.consistency_ok) and require no single day > X% (e.g. 40–50%, tier-configurable) of the payout-window total; return the shortfall math in the 4xx detail so the frontend can show 'trade N more green days'. Currently consistency_ok gates only the eval pass and nothing in the payout path references it.


**Why it matters:** Without a funded consistency rule, one lucky 0DTE lotto day funds an entire payout — exactly the gamble-and-cash-out pattern the eval-stage rule was built to filter, reappearing at the stage where the firm actually pays.


**Industry benchmark:** Topstep XFA applies a 40% best-day cap to payouts; Apex 4.0 applies 50% at payout; Tradeify uses graduated 20/25/30% caps by payout number.


**Verification evidence:** consistency_ok is defined at backend/services/combine_settlement.py:96 and consumed only in backend/services/combine_state.py:464-549, where line 485 gates the EVAL pass (target_met and min_days_met and consistency). The payout endpoint (backend/routers/combines.py:661-810, read in full) uses realized_by_trading_day only to count winning days (>= $150) and never references consistency; no best-day-percentage check or shortfall math exists in the payout path.


#### Re-activate the scaling-plan ladder  `[P1 · effort S · verified partial]`

The (threshold, contracts) ladder structure in backend/services/scaling_plan.py is deliberately flattened to one $0 step (50K→5, 100K→10, 150K→15). Populate real equity-milestone steps (e.g. 50K: 3 contracts at start → 5 above +$1.5K; scale per tier), enforce on the settled EOD balance so the cap can't flap intraday, and display the current step + next unlock on the dashboard objectives panel and in the order ticket's cap messaging (zerodte._clamp_contracts_to_cap already communicates clamps). Add a funded-stage extension: cap grows after each approved payout.


**Why it matters:** A flat cap lets a fresh account swing max size on day one — the exact blow-up profile trailing drawdown exists to prevent — and removes the progression mechanic that keeps traders engaged between pass and payout.


**Industry benchmark:** Topstep scales 5→15 minis with balance milestones (micros 10x); Apex publishes per-size contract ladders tied to profit thresholds; funded caps growing with payout track record is standard.


**Verification evidence:** backend/services/scaling_plan.py (read in full): the (threshold, contracts) ladder machinery exists and IS live — max_contracts() enforced in _require_tradeable (backend/routers/zerodte.py:654-725) and the cap surfaces in the TradeTicket gate (frontend TradeTicket.test.tsx 'scaling-cap gate', types/combine.ts:35 max_contracts) — but SCALING_PLANS is deliberately flattened to one $0 step per tier (lines 17-21: 50K [(0.0,5)], 100K [(0.0,10)], 150K [(0.0,15)]), per the module docstring 'a single step at $0'. scaling_steps() ('for display') has zero callers (grep -rn scaling_steps: only its definition). No equity milestones, no next-unlock UI, no payout-based cap growth.


#### Abuse detection and prohibited-conduct enforcement  `[P1 · effort L · verified missing]`

A risk-desk layer with three detectors feeding a review queue (and the payout-adjudication hold state): (1) cross-user correlation — same underlying/strike/side/timestamp-delta clustering across different users' combines, plus shared IP/device fingerprint on order submission (only per-IP auth rate limits exist today); (2) sim-fill exploitation — flag sub-second open→close round trips with abnormal win rates concentrated at quote-update lulls, since paper fills against delayed Alpaca quotes are latency-arbitrageable by design; (3) opposite-side hedging across a user's own 5 combines to guarantee one passes (the copy-trade service makes correlated multi-account flow first-class, but nothing watches for inverse or cross-user copying). Persist flags as combine_events, never auto-ban.


**Why it matters:** Group-passing and stale-quote arbitrage are the two attacks that drain sim-model prop firms; with auto-approving payouts and zero detection, one Discord group with a quote-lag script is an unbounded loss.


**Industry benchmark:** Firms flag ~97% trade-correlation clusters, shared AWS IPs across 30 accounts, <800ms round trips with >78% win rates; TOS universally reserve voiding stale-quote fills; firms distinguish allowed self-copy from banned cross-trader copy.


**Verification evidence:** grep -rniE 'fingerprint|device|user.agent|abuse|correlat' across backend/*.py (excl. pycache/tests) hit only CuratedEntry('AMD', 'Advanced Micro Devices') and backend/services/rate_limit.py:175 (request.client.host — the per-IP rate limiter, the only IP-aware code). backend/services/copy_trade.py exists (correlated multi-account flow is first-class) but no service or job inspects cross-user trade clustering, sub-second round trips, or inverse hedging across a user's combines; no risk-desk queue or flag-writing detector anywhere.


#### Lifecycle notification machinery (extends the known email-infra gap)  `[P1 · effort M · verified missing]`

Beyond the already-deferred forgot-password/verification emails: an event-driven notifier that fans out on combine_events writes — pass/funded (with activation CTA), MLL breach/termination, DLL day-lock, payout requested/approved/denied, renewal receipt, reset-credit granted, inactivity warning. Implementation: an outbox table consumed by a worker with pluggable channels (SMTP adapter + in-app notification center with unread badge in TradeDeskHeader). The append-only combine_events ledger (backend/models/combine_event.py) is already the perfect event source; nothing consumes it outbound.


**Why it matters:** Traders who get liquidated or funded while away from the terminal learn about it hours later; payout status changes silently. Support ticket volume and churn concentrate exactly on these moments at real firms.


**Industry benchmark:** Industry notifications are largely email/Discord; FTMO's app pushes account events; Topstep emails every lifecycle transition (pass, breach, payout status, rebill receipts).


**Verification evidence:** grep -rniE 'notificat|outbox|smtp|sendgrid|mailgun' across backend/ and frontend/src: zero product hits. combine_events (backend/models/combine_event.py) are only consumed pull-style as a history ledger (events endpoint in routers/combines.py:350 area, rendered in PayoutsPage/useCombines) — nothing fans out on writes. The bell in TradeDeskHeader (frontend/src/components/positions/TradeDeskHeader.tsx:74 → components/alerts/AlertsBell.tsx) is the separate WS6 feature for user-CREATED price/earnings/fill alerts (backend/models/alert.py docstring), not a lifecycle notification center; no email channel or worker exists.


#### Affiliate / referral program and promo codes  `[P1 · effort L · verified missing]`

Two connected pieces the purchase flow lacks entirely (frontend/src/pages/NewCombinePage.tsx takes no code input; grep finds only the internal SPLIT_DISCOUNT constant): (1) promo codes — a codes table (percent/fixed, expiry, max-redemptions, tier scope) applied in backend/services/pricing.py price resolution and recorded on the Payment ledger row; (2) referral/affiliate — per-user referral codes, click/signup attribution (cookie + signup field), commission ledger accruing a % of evaluation and reset payments, and a payout path for affiliates (can reuse the payout-methods work). Admin CRUD for both lives in the back-office item.


**Why it matters:** Affiliates are the sector's primary acquisition channel and discounting is how eval volume is manufactured; launching without either means paying retail CAC in a market trained on 40–90% coupon culture.


**Industry benchmark:** Apex pays 15% recurring (6-mo cookie), MFFU 12% on evals+resets, FTMO up to 39% tiered; Apex runs near-continuous 80–90% coupons, Tradeify ~40% codes; FundedNext rotates BOGO/split add-on promos via affiliate codes.


**Verification evidence:** grep -rniE 'promo|referral|affiliate|coupon|discount' across backend/ and frontend/src matched only the internal SPLIT_DISCOUNT constant (backend/services/pricing.py:65, frontend/src/lib/pricing.ts:26) — exactly as the claim predicted. No codes/commission/attribution tables in backend/models/; frontend/src/pages/NewCombinePage.tsx has no code-entry field (grep 'promo|code' empty); pricing.py monthly_price() takes only tier/path/split.


### P2 — competitive


#### Graduated payout caps and cadence ladder  `[P2 · effort M · verified missing]`

The payout gate has a floor (min $125, 24h pacing, 5 win days, MLL buffer) but no ceiling: a trader can request 100% of available profit in one shot. Add per-request caps that graduate with payout count — e.g. cap at 50% of balance per request, absolute caps by tier for the first N payouts (payout #1–2: $2K on 50K), rising each approved payout, uncapped after ~6 — stored as a ladder in pricing/config, enforced in the payout endpoint, displayed as 'next payout unlocks $X' on PayoutsPage.tsx. Payout count since funded_epoch_at is already derivable from combine_events.


**Why it matters:** Payout caps are the firm's cash-flow smoothing and its main defense against pass-and-drain accounts; uncapped first payouts concentrate the loss from every abuse vector into a single request.


**Industry benchmark:** Topstep caps XFA requests at 50% of balance with recent per-tier absolute caps ($2K–$3K on 50K); Apex runs a graduated ladder uncapped after ~6th payout; Tradeify Lightning scales $1,500→$2,500→$25K.


**Verification evidence:** backend/routers/combines.py:661-810 (payout endpoint, read in full): gates are PAYOUT_MIN_AMOUNT=$125 (line 58), PAYOUT_MIN_WINNING_DAYS=5, PAYOUT_MIN_INTERVAL_H=24, idempotency window, and the MLL-floor check — floors only. The amount check is `amount > available + 1e-9` → a trader can request 100% of available in one shot; no per-request percentage cap, no tier/payout-count ladder in pricing.py or config.py, no 'next payout unlocks' display in PayoutsPage.tsx.


#### Product-line variants: instant funding and 1-step eval  `[P2 · effort M · verified missing]`

The purchase flow supports exactly one product shape (eval → funded). Add two SKU variants to the pricing matrix (backend/services/pricing.py) and provisioner (backend/services/combine_provision.py): (1) a 1-step eval — same target, no consistency rule or fewer min days, higher price, faster split; (2) an instant-funded tier — no eval, high upfront fee, lower starting split (e.g. 70%) with static drawdown. Most machinery (funded_epoch_at accounting, payout gates, MLL) is reusable; the variants are mostly provisioning flags plus a NewCombinePage.tsx path option.


**Why it matters:** Single-SKU firms lose the impatient high-LTV segment; instant funding is a high-margin product (large fee, most buyers breach) and 1-step is the 2025-26 competitive default.


**Industry benchmark:** FTMO added 1-Step (90% split from first withdrawal); FundedNext runs 7 models including Stellar Instant; The5%ers Hyper Growth is 1-step with no min days; Apex 4.0 allows 0-min-day passes; FunderPro Instant pays first reward at $100 profit.


**Verification evidence:** backend/services/pricing.py (read in full) models exactly one product shape — eval→funded — with two orthogonal purchase options (path: activation/no_activation; split: 80_20/50_50). grep -rniE 'instant|one.step|1.step' in pricing/provisioning: nothing. backend/services/combine_provision.py has no variant flags; backend/models/combine.py has no product-type column (status/outcome/funded_at only); NewCombinePage.tsx offers only tier+path+split.


#### News-event trading restriction for funded accounts  `[P2 · effort M · verified missing]`

A Tier-1 economic-event rule for funded combines: maintain a calendar of high-impact releases (CPI, FOMC, NFP — FRED/Finnhub integrations already exist in the codebase for data), and either block new opens in a ±2 min window or require flat books 2 min before release, enforced in zerodte._require_tradeable with a distinct 403 reason and a countdown banner in the terminal. Make it a per-tier/config flag so eval accounts stay unrestricted (permissive-eval, strict-funded is the common shape).


**Why it matters:** 0DTE options are the purest news-punt instrument in existence — a max-size straddle 30 seconds before CPI is a coin-flip against the firm's capital, and every real firm has a rule or ban aimed at exactly this.


**Industry benchmark:** MFFU requires flat 2 min before Tier-1 events on sim-funded; FTMO blocks ±2 min around ~15 high-impact releases/mo on standard funded accounts; Topstep bans max-size news punts; Apex bans news-exploitation strategies.


**Verification evidence:** The DATA layer exists exactly as the claim assumed: backend/services/calendar_constants.py has FOMC_MEETINGS_2026 hardcoded, backend/routers/calendar.py:58-70 merges FOMC + FRED economic releases with importance='high' — but purely for display. _require_tradeable (backend/routers/zerodte.py:654-725, read in full) checks failed/day-lock/MLL/MTM-DLL/scaling cap only — no event-window branch; grep -rniE 'cpi|fomc|nfp|blackout|restricted.window' in zerodte.py, combine_state.py, config.py: zero hits. No countdown banner in the terminal.


#### Per-trade risk limits / defined-risk rule for short options  `[P2 · effort M · verified missing]`

Naked short calls/puts are freely permitted (backend/routers/zerodte.py ~line 972 books short_call/short_put) with only the aggregate contract cap and MLL monitor (20s cadence) between a gap move and the account floor. Add an options-native risk gate in _require_tradeable: per-order max defined risk as a fraction of remaining MLL cushion (e.g. ≤30–50%), computed as debit for long structures and max-loss for spreads; for naked shorts either require a defined-risk pairing (convert to spread), demand margin-style buffer headroom, or make naked shorts a funded-stage-prohibited structure. Optionally a portfolio delta/vega cap as phase 2.


**Why it matters:** A naked 0DTE short call has unbounded loss between 20-second monitor ticks; one gap candle can take a funded account far below its MLL floor, and in a real-money future that overshoot is the firm's loss, not the trader's.


**Industry benchmark:** Options-specific funding firms (Black Eagle) allow only defined-risk structures (credit spreads, iron condors) with live Greek limits; Apex 4.0 'intended risk' guidance caps ~30% of drawdown per trade; real-capital desks gate naked short options behind margin.


**Verification evidence:** backend/routers/zerodte.py:972 books strategy = 'short_call'/'short_put' (naked shorts) with no risk gate beyond _require_tradeable (lines 654-725: failed/day-lock/MLL/MTM/aggregate contract cap — no per-order max-defined-risk vs MLL cushion). grep -niE 'max_loss|defined.risk|margin|naked' in zerodte.py: max_loss appears only at line 1359 inside ContractPreviewOut (the /preview payoff-diagram response — display only). No spread-conversion requirement, no buffer-headroom check, no funded-stage prohibition on naked shorts.


#### Free trial / practice combine  `[P2 · effort M · verified missing]`

A $0 time-boxed trial SKU: provision a combine flagged trial=True (excluded from the 5-slot cap, from payout eligibility, and from auto-fund), 7–14 day expiry enforced by the renew job, full rule engine active (MLL/DLL/targets) so the trial teaches the actual rules, with a conversion CTA into NewCombinePage on pass or expiry. Provisioning, rules, and archival machinery all exist; this is mostly a flag plus gating.


**Why it matters:** The eval purchase is a $49–$149 leap of faith at an unknown firm; a trial that demonstrates the terminal and the rule engine is the cheapest conversion lever available, especially for a novel options prop product with no brand trust.


**Industry benchmark:** FTMO's 14-day Free Trial (halved targets, full tooling) is a signature acquisition asset; FundedNext gives free entries via monthly competitions (150 winners/month).


**Verification evidence:** grep -rniE '\btrial\b|practice|demo' across backend/ and frontend/src: only incidental comment hits ('in practice', 'narrow set in practice'). backend/models/combine.py has no trial flag; backend/services/pricing.py has no $0 SKU (BASE_MONTHLY is 50K/100K/150K only); combine_provision and the 5-slot cap logic have no trial exclusion; renew_combines.py has no trial-expiry branch.


### P3 — polish


#### Shareable pass and payout certificates  `[P3 · effort S · verified missing]`

Generate a certificate artifact on two events: eval pass (funded_at stamp) and payout approval — a server-rendered image/PDF with account size, achievement, date, and a verification URL (public GET /api/certificates/{token} that confirms authenticity without exposing account data). Surface download/share buttons on the dashboard pass banner and PayoutsPage ledger rows.


**Why it matters:** Certificates are the sector's organic-marketing loop — every pass posted to X/Discord is free acquisition — and the verification URL doubles as trust signaling for a new firm with no payout-proof history.


**Industry benchmark:** FTMO and FundedNext both issue shareable challenge-pass and payout certificates with public verification; firms publicize aggregate payout totals ($284M+ at FundedNext) as trust signals.


**Verification evidence:** grep -rniE 'certificat' across backend/ and frontend/src (all extensions): zero hits. backend/main.py:456-472 router list contains no certificates router; no public verification endpoint of any kind; no download/share affordance on the dashboard pass banner or PayoutsPage ledger.


#### Modeled progression beyond sim-funded (live-track concept)  `[P3 · effort M · verified missing]`

Add the concept of a post-sim tier even while execution stays simulated: criteria tracking on funded combines (payout count, months funded, consistency score, rule-violation-free streak) with a visible 'live track' progress panel, and a terminal state live_invited that today simply badges the account and uncaps payout-request limits. This models the industry ladder on backend/models/combine.py (currently funded is one flat state defined by funded_epoch_at) so a future real-capital stage has somewhere to attach.


**Why it matters:** The best traders — the ones a prop firm actually profits from long-term — churn when the ladder visibly ends; even a modeled live track retains them and pre-builds the data (payout track record) any real-capital partner would demand.


**Industry benchmark:** Standard pattern is eval → sim-funded → invitation-only live: Topstep Live Funded (fixed-floor drawdown, uncapped payouts), Apex mirrors PA trades via API before inviting, MFFU invites via affiliated companies.


**Verification evidence:** grep -rniE 'live_invited|live.track|live_track' across backend/ and frontend/src: zero hits. backend/models/combine.py:55-87 confirms the flat model the claim describes: status is 'active'|'archived', outcome is 'active'|'passed'|'failed', and funded is defined solely by funded_at/funded_activated_at/funded_epoch_at timestamps — no post-funded criteria tracking, consistency score, streak, or terminal invited state anywhere.


## Trading engine & market data


### P0 — cannot operate as a real business without it


#### Production market-data capacity, licensing & entitlements  `[P0 · effort L · verified missing]`

The entire platform runs on ONE free-tier Alpaca key: interactive+background token buckets summing to 3 req/s (backend/services/alpaca_client.py), IEX-only equity feed, and the free 'indicative' options feed (backend/config.py:21) which returns no open interest (worked around with ~50 extra volume calls per chain). Needed: a paid options/equities data tier sized for N concurrent traders, OPRA redistribution agreement with per-subscriber entitlement/reporting (displaying real-time options NBBO to paying customers is a licensed activity), SIP or paid equity feed instead of IEX, real open interest, and per-user rate architecture (the current single shared bucket means 10 concurrent users starve each other's fills).


**Why it matters:** This is a hard legal and physical blocker to multi-user launch: exchange data agreements prohibit redistributing real-time data to customers on an individual free plan, and 3 req/s cannot serve more than a couple of simultaneous traders — fills, chains, and monitor passes all contend for the same bucket. Every real firm treats market-data licensing/fees as a core operating line item.


**Industry benchmark:** Futures prop firms bundle or pass through CME data fees (Apex charged monthly PA data fees; Topstep bundles data into TopstepX). OPRA has per-subscriber professional/non-professional fee schedules that any options display product must report under. The MetaQuotes license-revocation episode (~80-100 prop firms died 2024-2025) is the canonical lesson that data/platform licensing is existential.


**Verification evidence:** backend/config.py:21 alpaca_options_feed='indicative' (free feed); backend/services/alpaca_client.py:57-72 two process-wide TokenBuckets summing to settings.alpaca_rate_limit_per_s (default 3/s), shared by ALL users; alpaca_client.py:1080 feed=DataFeed.IEX for equity bars; alpaca_client.py:702-704 with_volume=True issues extra OptionBarsRequest calls because 'indicative feed returns no open_interest field'. grep -rni 'entitlement|OPRA|SIP|redistribution' backend/ hits only a comment in realtime_feed.py:104; the only per-user rate limits are on financial endpoints (backend/tests/test_financial_rate_limit.py), not market data. No paid-tier config, no per-subscriber entitlement code anywhere.


### P1 — industry table stakes; traders churn without it


#### Event-driven trigger engine (eliminate 20-second execution granularity)  `[P1 · effort L · verified missing]`

All resting orders, stops, trailing stops, brackets, premium exits, and MLL/DLL auto-liquidation are evaluated by a single APScheduler pass every 20s (backend/services/order_monitor.py, scheduled in backend/main.py). Replace with quote-event-driven evaluation: subscribe streaming quotes for every symbol/contract with an open position or working order (the streaming scaffold in realtime_feed.py already exists), evaluate triggers on each tick (or a <=1s loop as fallback), and define an explicit gap-through fill policy (fill at first quote through the trigger with the fills.py friction model, not at a mark up to 20s later). Keep the 20s pass as a reconciliation sweep.


**Why it matters:** 0DTE options are the highest-gamma instruments in existence — premiums routinely move 30-50% inside 20 seconds. A stop that executes 20s late is a different product than the one traders think they bought, and drawdown liquidations landing far beyond the configured MLL/DLL generate the dispute volume that dominates prop-firm support load. This is the single biggest 'feels fake' signal a serious trader will hit in the first hour.


**Industry benchmark:** Topstep/Apex/MFFU real-time trailing accounts enforce drawdown tick-by-tick and auto-liquidate immediately on breach; TopstepX and Tradovate/NinjaTrader execute stops on the touch. No launched firm enforces intraday risk on a 20s cron.


**Verification evidence:** backend/main.py:249-256 schedules monitor_orders on IntervalTrigger(seconds=20) — the sole evaluator for working orders, stops, trailing, brackets, premium exits, and MLL/DLL liquidation (backend/services/order_monitor.py). grep for realtime/get_realtime_feed/LatestStore in order_monitor.py and fills.py returns zero hits — the realtime_feed.py scaffold (subscribe/on_quote at lines 94/117) is never wired to trigger evaluation. No tick-driven path, no gap-through fill policy; fills price at the mark seen on the 20s pass.


#### Browser push channel + options streaming enablement  `[P1 · effort L · verified partial]`

Extends the known 'realtime streaming quotes' deferred item with verified specifics: (a) the stale blocker is gone — installed alpaca-py is 0.43.4 which ships OptionDataStream, so the 'equities only' limitation documented at backend/services/realtime_feed.py:15-16 no longer holds; wire an OPRA option-quote subscription for contracts with open positions/working orders into the existing LatestStore. (b) Flip settings.realtime_feed_enabled (backend/config.py:58) on by default once soak-tested. (c) Build the missing browser leg: a FastAPI WebSocket (or SSE) endpoint fanning out quote/position/order events, and migrate the frontend polling hooks (5s quotes, 8s working orders, 10s chain, 15s alerts in frontend/src/hooks/) to the push channel with polling as fallback.


**Why it matters:** Every screen a trader compares this to (TopstepX, Tradovate, ToS, broker apps) updates sub-second. 5-15s REST polling makes marks, P&L, and the drawdown meter visibly stale — traders will screenshot the lag next to their broker and post it. It also multiplies REST load per user, compounding the P0 capacity gap.


**Industry benchmark:** TopstepX, Tradovate, NinjaTrader, TradeLocker, cTrader all stream quotes and account state via WebSocket; no funded-trading platform ships on REST polling.


**Verification evidence:** Server scaffold is real: backend/services/realtime_feed.py implements StockDataStream consumer + LatestStore read-through consulted by alpaca_client get_quotes (alpaca_client.py:147-233), started in main.py:298-320 lifespan — but settings.realtime_feed_enabled defaults False (backend/config.py:58) so NoOpRealtimeFeed ships. Options streaming absent: realtime_feed.py:15-16 documents 'equities only... alpaca-py 0.21.0 lacks OptionDataStream', yet backend/uv.lock pins alpaca-py 0.43.4 and `uv run python -c "from alpaca.data.live import OptionDataStream"` succeeds — the stale-blocker claim is CONFIRMED. Browser leg truly missing: grep WebSocket/SSE/EventSource/text/event-stream across backend routers and frontend/src returns no endpoint and no client — frontend hooks poll (frontend/src/hooks/useAlerts.ts:105 setInterval 15_000, etc.).


#### Immutable order/execution ledger with fill reports  `[P1 · effort M · verified missing]`

There is no Order/Execution/Fill entity: one models/trade.py Trade row is simultaneously order, position, and journal entry, mutated in place (working->open overwrites entry_price/entry_date; scale-outs rewrite legs_json; breadcrumbs accumulate in a notes string). Build an append-only executions table written at every fill/trigger/liquidation event: order id, requested price, quoted NBBO at decision time, filled price, slippage decomposition (half-spread vs size-impact vs liquidation stress from fills.py), trigger reason, monitor-pass/stream-event id, and timestamps. Expose per-fill reports in the trader UI and an admin query surface, and publish the fill-model methodology as a docs page.


**Why it matters:** Rule-breach terminations and payout denials are the top dispute category in this industry; without an immutable record of what the engine saw and why it filled/liquidated at a given price, every dispute is the operator's word against the trader's. It is also the substrate the risk desk (abuse detection) and any future auditor/processor due-diligence needs.


**Industry benchmark:** Industry enforcement pattern is 'human review + audit trail before ban'; firms' TOS reserve the right to void specific fills, which requires per-fill records. FTMO's MetriX and TopstepX journals expose per-execution detail to traders; transparent dashboards measurably cut support tickets.


**Verification evidence:** backend/models/ contains no Order/Execution/Fill model (only trade.py, combine.py, payment.py, etc.); grep 'class (Order|Execution|Fill)' and 'executions|execution_ledger|fill_report' across backend/ come up empty. backend/models/trade.py:90 comment confirms one row carries the order lifecycle ('status carries the order lifecycle: working...'); order_monitor.py:_commit_fill (lines 1424-1449) mutates the same row in place — overwrites leg entry_price, entry_underlying_price, entry_date, status working→open — and breadcrumbs accumulate via `trade.notes = (trade.notes or '') + ...` at lines 352, 470, 603, 989, 1316, 1555. No quoted-NBBO-at-decision capture, no slippage decomposition persistence, no fill-report UI, no fill-model docs page.


#### Margin/buying-power model for short options (or defined-risk-only enforcement)  `[P1 · effort M · verified missing]`

Verified absent: grep for margin/buying-power across backend/ returns only an unrelated docstring word (order_monitor.py:870). Short options and net-credit structures are gated solely by the per-combine contract-count scaling cap — a 50K combine can sell naked calls (unbounded loss) with no notional, max-loss, or premium-at-risk capacity check, and credit structures free up no less capacity than debit ones. Implement either (a) defined-risk-only enforcement: reject naked short legs, require every net-credit structure to have a bounding long wing, and charge buying power = max structural loss; or (b) a Reg-T-like short-option requirement (max(20% underlying - OTM amount, 10% strike) + premium) checked at placement and marked in the monitor pass.


**Why it matters:** Without max-loss-based sizing, the combine's contract cap is meaningless for short-vol trades: one trader's 5-lot iron condor and another's 5 naked SPY calls consume identical capacity while carrying wildly different tail risk, so MLL liquidation becomes the de facto margin engine — guaranteeing traders blow through limits on gap moves and generating exactly the disputes the ledger gap amplifies. Every real options desk sizes by risk, not lot count.


**Industry benchmark:** The real options-funding firms are explicitly defined-risk: Black Eagle allows only defined-risk strategies (credit spreads, iron condors) with Greek-based limits; SMB/T3/Maverick run real margin. Brokers universally apply short-option margin formulas.


**Verification evidence:** grep -rni 'margin|buying.power|buying_power' backend/ (excl. tests) hits only the unrelated word 'marginal' in order_monitor.py:870 — exactly as claimed. Sell-to-open is allowed (zerodte.py:446/493 action Literal['buy','sell'] — 'sell = short straddle (credit)'); the only size gate is the per-combine contract-count scaling cap (_clamp_contracts_to_cap zerodte.py:596, gate at :718). max_loss exists only as a display field on ContractPreviewOut (zerodte.py:1359) for the payoff diagram — never checked at placement. No defined-risk rejection of naked short legs, no Reg-T-like requirement anywhere.


#### Liquidity-capped sizing and partial fills (NBBO-size-aware engine)  `[P1 · effort M · verified missing]`

Extends the known deferred item with a concrete mechanism: Alpaca option quotes carry bid_size/ask_size — cap the instantly-fillable quantity at the displayed NBBO size (x a configurable multiplier), fill the remainder as a resting working order re-evaluated on subsequent quotes (partial-fill states on the new execution ledger), impose a per-contract max order size from volume/OI proxy already fetched in alpaca_client, and reject or heavily-penalize entries into zero-bid/one-sided strikes instead of synthesizing a 2% touch. Surface displayed size in the chain/ticket so the cap is legible.


**Why it matters:** All-or-none instant fills at capped 5% slippage mean a 100-lot in a dead strike fills as easily as a 1-lot — traders can pass combines with size that could never execute live, and the firm then pays real payouts to sim-only strategies. 'Exploiting sim fills' is a named ban category at every firm precisely because it is a direct P&L leak.


**Industry benchmark:** Prop TOS universally prohibit exploiting simulated fills; Apex 4.0's 'intended risk' rules target max-size all-in behavior; real routing (Tradovate/Rithmic for futures firms) naturally enforces book-size limits that a simulator must replicate.


**Verification evidence:** grep 'bid_size|ask_size|partial' in fills.py/alpaca_client.py/order_monitor.py: the Quote mapping (alpaca_client.py:979-996) reads only bid_price/ask_price/last — NBBO sizes are never captured. 'partial' hits are all about partial feed data or scale-out P&L, not partial fills. backend/services/fills.py has only the deterministic size-impact penalty (_SIZE_SLIP_PER_CONTRACT=0.005, cap 5%) — orders of any size fill atomically; pick_fill_price (fills.py:96-111) synthesizes a 2%-of-last touch for one-sided/zero-bid quotes instead of rejecting. No per-contract max order size from volume/OI, no partial-fill states, no displayed-size in RightChain.tsx.


### P2 — competitive


#### SPX/XSP index options via a second data vendor  `[P2 · effort L · verified missing]`

SPX/NDX/VIX are denylisted because Alpaca's free tier doesn't carry CBOE index products (backend/services/curated_universe.py, config zero_dte_universe = SPY/QQQ/IWM). Integrate a vendor that carries CBOE index options (Polygon, Tradier, dxFeed, or CBOE DataShop) behind the existing alpaca_client-style abstraction, add SPX/XSP chains with the same 0DTE gating, and route their settlement through the existing cash-settlement path — which is exactly correct for these products since SPXW dailies are European-style, PM-cash-settled.


**Why it matters:** SPX is where the majority of real 0DTE volume lives; a firm branded '0DTE options prop firm' without the flagship 0DTE instrument reads as amateur to its exact target customer. Bonus: European cash settlement makes the sim's settle-at-intrinsic behavior faithful rather than a fudge, sidestepping the entire assignment problem for these products.


**Industry benchmark:** Options Funding (the closest direct competitor) leads with SPX alongside SPY/QQQ/IWM + 0DTE; the ops research names cash-settled SPX/XSP 'the operationally sane default' for a 0DTE firm.


**Verification evidence:** backend/services/curated_universe.py:17,39 explicitly denylists SPX/NDX/VIX ('cash-settled CBOE products'); backend/config.py:224-231 zero_dte_universe=('SPY','QQQ','IWM') with comment 'Index options (SPX, XSP, NDX) are intentionally omitted: Alpaca's free options feed does not list cash-settled index options'. grep -rni 'polygon|tradier|dxfeed|datashop' backend/ (excl. tests) returns zero vendor integrations — the only non-Alpaca sources are finnhub_client.py/fred_client.py (reference data) and yfinance_client.py (earnings dates only).


#### Expiration-day close-out policy and settlement friction  `[P2 · effort M · verified missing]`

settle_expired_positions cash-settles everything at 4pm intrinsic with NO spread friction — strictly better than any achievable real-world exit, so holding to the bell is mechanically optimal. Add: (a) a forced pre-close flatten window (e.g., 3:45-3:55 ET) for open 0DTE positions — or at minimum for short/ATM legs — executed through the normal fills.py friction path like the existing day-lock flatten; (b) if positions may settle, apply an exit-friction haircut at settlement; (c) optionally simulate American-style assignment for ITM-at-close short SPY/QQQ legs (OCC auto-exercise at $0.01 ITM) or document cash-settlement-by-fiat as an explicit product rule.


**Why it matters:** Frictionless intrinsic settlement is a systematic subsidy that trains funded traders into hold-to-expiry behavior that would be pin-risk suicide with real options, and sharp traders will farm it (sell wide condors, never pay the exit spread). Every real firm forcibly flattens before the close for exactly this reason.


**Industry benchmark:** Topstep auto-liquidates at 3:10pm CT, MFFU at 4:10pm ET, Apex requires flat by 4:59pm ET; the options-ops research prescribes force-closing short options near strikes by a 3:30-3:45 ET cutoff for physically-settled products.


**Verification evidence:** backend/services/order_monitor.py:545-551 settle_expired_positions settles at 'settlement INTRINSIC value at the 4pm ET close'; lines 1493-1494 state outright that 'expiry settlement is cash-settled at intrinsic, so it pays no spread' — zero exit friction, confirming hold-to-bell is strictly optimal. No forced pre-close flatten: grep 'flatten window|pre.close|3:45|15:45' returns nothing; the 'day-lock flatten' (order_monitor.py:956-989) is DLL/profit-lock driven, not time-of-day. No assignment simulation: grep 'assignment|auto.exercise' hits only the docstring at :551 saying settlement is 'not exercise-assignment', and the product rule is documented only in code comments, not a user-facing rules page.


#### Trading-halt / LULD awareness in the execution path  `[P2 · effort M · verified missing]`

No halt or LULD state anywhere; the only guard is the 300s stale-print refusal (zerodte._require_fresh_spot). Subscribe to Alpaca's trading-status stream (available via the existing streaming scaffold) or poll asset status, hold a per-symbol halt flag in alpaca_client, and: reject new opens on halted underlyings with a typed 409, suspend trigger evaluation (stops/trailing/brackets) during the halt, re-evaluate on reopen against the first post-halt NBBO with gap-through policy, and show a halt banner in the terminal.


**Why it matters:** Individual curated symbols (TSLA, NVDA, meme-adjacent names) halt regularly on volatility and news. Today a 4-minute LULD halt leaves quotes inside the 300s freshness window, so orders can fill and stops can trigger against pre-halt prices, then liquidations fire into the reopen gap — a guaranteed dispute generator on the platform's most active names.


**Industry benchmark:** Real platforms (Tradovate, ToS, broker APIs) expose halt state and suspend order handling; firms' news rules (MFFU flat-2-min before Tier-1 events) exist precisely because event gaps break sim fills.


**Verification evidence:** grep -rni 'halt|LULD|limit.up|limit.down|trading.status' backend/ (excl. tests): every hit is a comment about stale prints possibly meaning a halt (config.py:128, zerodte.py:175/188, alpaca_client.py:341, calculations/types.py:33). The only guard is _require_fresh_spot (backend/routers/zerodte.py:174-188) refusing opens on a >300s-old print (config.py:131 max_spot_staleness_s=300). No halt flag, no trading-status stream subscription, no trigger suspension during halts, no halt banner in frontend/src.


#### Multi-leg stop, stop-limit, and bracket orders on net premium  `[P2 · effort M · verified partial]`

Multi-leg working orders support net-premium LIMIT only (order_monitor._process_working_multi); premium-multiple TP/SL exists but there is no resting net-premium STOP or stop-limit for structures, no OCO between a structure's TP and SL as placeable-at-entry brackets on net debit/credit. Add stop/stop-limit trigger evaluation on the structure's live net premium (the per-leg live-quote plane already prices structures), with the same signed debit/credit convention and sign-flip protection the PATCH /order path already has.


**Why it matters:** Spread traders' standard workflow is 'buy condor at 1.20, bracket at 2.40/0.60' as resting orders — forcing them to babysit premium-multiple exits or leg out manually makes the structure builder feel half-finished, and defined-risk structures are exactly what an options prop firm wants to encourage (see the margin gap).


**Industry benchmark:** Tastytrade, ToS, and IBKR all support stop and bracket orders on multi-leg net premium; TopstepX's signature interaction is bracket-at-entry with draggable modification.


**Verification evidence:** Single-leg orders support the full set: zerodte.py:499 order_type Literal['market','limit','stop','stop_limit'] plus oco_group (trade.py:120-123, zerodte.py:513). Multi-leg is limit-only exactly as claimed: OpenMultiLegRequest at zerodte.py:1072 declares order_type Literal['market','limit'], and order_monitor._process_working_multi (line 1365) returns None unless order_type=='limit' — no net-premium stop or stop-limit trigger path for structures. Attached premium-multiple TP/SL brackets ARE placeable at entry on multi-leg (tp_premium_mult/sl_premium_mult on the payload, zerodte.py:~1089-1110) and evaluated by the monitor, so bracket-style exits exist; the resting net-premium STOP/stop-limit order types are the missing piece.


#### Server-side alert evaluation with a notification channel  `[P2 · effort M · verified partial]`

Alerts (backend/routers/alerts.py) are evaluated only by the browser ticking POST /evaluate every 15s (frontend/src/hooks/useAlerts.ts) — nothing fires when the app is closed. Move evaluation into the server scheduler (or the new event loop), persist triggered state, and deliver through a notification layer (builds on the deferred email infrastructure; add web push and/or in-app notification inbox). Extend the same channel to order events traders universally expect: fill confirmations, stop-outs, liquidations, DLL/MLL proximity warnings, and combine pass/fail.


**Why it matters:** A trader who gets auto-liquidated or passes their combine while at lunch and learns about it hours later loses trust immediately; alerting-only-while-watching defeats the purpose of alerts. Notification of liquidation events is also a fairness/dispute-mitigation feature, not just convenience.


**Industry benchmark:** Industry notifications run through email/Discord at minimum (Topstep/Apex/MFFU); FTMO's app pushes account events natively; broker platforms all push fill and margin notifications.


**Verification evidence:** A routed server evaluation endpoint exists — POST /api/alerts/evaluate (backend/routers/alerts.py:194) — and triggered state persists on the Alert row, but it only runs when the browser ticks it: frontend/src/hooks/useAlerts.ts:105 setInterval(tick, 15_000), and alerts.py:12-14 documents the client-side-evaluation design. No scheduler job for alerts in backend/main.py (jobs: refresh, prewarm, collect_options_chain, settle_combines, renew_combines, monitor_orders, sweep_cache — no alert pass), so nothing fires when the app is closed. No notification layer at all: grep 'notification|web push|inbox|email' across routers/services finds no email service, no push, no in-app inbox; no fill/stop-out/liquidation/DLL-proximity notifications.


#### Portfolio Greek limits as configurable combine rules  `[P2 · effort M · verified missing]`

The platform already computes live greeks (PositionRiskStrip, order_monitor._leg_model_price BS fallback) but the only exposure rule is a contract-count scaling cap. Add server-enforced, per-combine portfolio Greek caps — net delta (in SPY-beta-adjusted dollars), gamma, vega, and short-theta — checked at order placement (reject with a typed 409 naming the binding limit) and monitored on the risk pass with warn-then-liquidate semantics; surface live headroom in the risk strip.


**Why it matters:** Contract counts are a futures-firm concept that maps terribly to options: 10 ATM 0DTE straddles and 10 far-OTM lottos are the same 'size' but different books entirely. Greek-based limits are how a real options risk desk thinks, and they're the natural next rule tier after the margin model — also a genuine differentiator no futures-derived competitor can copy easily.


**Industry benchmark:** Black Eagle (options funding) advertises Greek-based limits with defined-risk strategies up to $250K; real-capital options desks (SMB, T3) manage traders on Greek budgets, not lot counts.


**Verification evidence:** Greeks are computed and displayed — backend/routers/journal.py:1151-1168 aggregates portfolio delta/gamma/theta/vega, frontend/src/components/positions/PositionRiskStrip.tsx renders them, order_monitor._leg_model_price provides the BS fallback — but grep 'delta.*cap|greek.*limit|greek.*cap|net_delta' across backend returns zero enforcement code. backend/services/account_tiers.py and models/combine.py contain no greek fields; the only exposure rule is the contract-count scaling cap (zerodte.py:596-718). No placement-time 409 on greek breach, no monitor-pass greek check, no headroom display.


#### Second live-quote source / failover for the fill-and-exit plane  `[P2 · effort L · verified missing]`

All fills, stops, liquidations, and settlement pricing hang off one vendor behind one shared 'alpaca' circuit breaker; when it opens mid-session, exits 503 and MLL/DLL enforcement stalls until recovery (yfinance fallback exists only for reference data, not the live option-quote plane). Add a hot-failover second options-quote source (Tradier/Polygon — can be the same vendor added for SPX) behind the get_live_option_quotes interface, with a documented degraded-mode policy: exits allowed against the fallback feed, opens blocked, and an incident banner in the terminal.


**Why it matters:** For a firm whose product IS execution against live prices, a vendor outage during a volatile session means traders watch positions burn with no way out — the single worst trust event possible, and one the firm caused. Vendor dependency is the documented existential failure mode of this industry.


**Industry benchmark:** The MetaQuotes revocations killed ~80-100 prop firms in 2024-2025; survivors run multiple platform/data vendors in parallel. Futures firms inherit redundancy from Rithmic/CQG dual-feeds.


**Verification evidence:** fills.live_leg_quotes (backend/services/fills.py:133-151) calls only services.alpaca_client.get_live_option_quotes; on ANY failure ('cold feed / breaker open') it degrades to {} → callers fall back to the frictionless model mid, and opens 503 (fills.py:77). One CircuitBreaker guards all Alpaca paths (alpaca_client.py:49, 108, 473). yfinance_client.py is earnings-reference-data only ('Thin yfinance wrapper for historical earnings dates + EPS estimates'). grep 'polygon|tradier' backend/ = no second options-quote vendor, no degraded-mode policy, no incident banner.


#### Fill-time quote-quality guards against sim-fill exploitation  `[P2 · effort M · verified missing]`

The deterministic fill engine will fill against any quote inside the 300s staleness window, including synthesized one-sided quotes (2% touch) and locked/crossed NBBO. Add engine-level guards: reject or re-quote fills when NBBO is crossed/locked or wider than a per-symbol sanity band, require two-sided real quotes for size above a threshold, tighten max_spot_staleness_s (300s is an eternity for 0DTE) for execution decisions specifically, and stamp every execution-ledger row with a quote-quality flag the risk desk can query for stale-quote-arbitrage patterns.


**Why it matters:** Latency/stale-quote arbitrage is a top documented abuse vector against simulated platforms — payouts are real money, so systematically exploitable fills are a direct P&L drain. Guards at fill time are cheaper than clawing back payouts after ML-based detection.


**Industry benchmark:** Prop TOS reserve the right to void stale-quote fills; documented detection signatures target sub-second round trips at quote-update lulls with >78% win rates; every firm bans 'exploiting sim fills' as a named category.


**Verification evidence:** backend/services/fills.py pick_fill_price (lines 70-112): one-sided/last-only quotes get a synthesized 2%-of-price touch (lines 96-110) rather than rejection; crossed NBBO is silently flattened via spread=max(0.0, ask-bid) (line 92) — no crossed/locked detection or re-quote; no per-symbol spread sanity band; no two-sided-quote requirement by size. The only staleness gate on the execution path is the 300s underlying-spot check (_require_fresh_spot, zerodte.py:174-188 against config.py:131 max_spot_staleness_s=300.0) — no tighter execution-specific window, no option-quote-level staleness gate in fills.py/order_monitor.py, and no quote-quality flag persisted anywhere (no execution ledger exists).


### P3 — polish


#### NBBO size display and time & sales tape  `[P3 · effort M · verified missing]`

The chain (RightChain.tsx) and ticket show price but no displayed size, and there is no time-and-sales for the selected contract or underlying. Once streaming lands, surface bid/ask size in the chain and QuickOrder ladder, and add an option trades tape (OptionDataStream trades) plus underlying prints panel in the terminal.


**Why it matters:** 0DTE scalpers read the tape and displayed size to time entries; its absence marks the platform as a dashboard rather than a trading terminal. Also makes the liquidity-capped fill engine legible — traders can see the size their order will be capped against.


**Industry benchmark:** TopstepX, Tradovate, NinjaTrader all ship DOM/T&S as core terminal furniture; ToS and tastytrade show option NBBO size everywhere.


**Verification evidence:** Backend never captures sizes: alpaca_client.py:979-996 maps only bid_price/ask_price/last into Quote — no bid_size/ask_size fields. Frontend: grep 'bid_size|ask_size' across frontend/src = zero hits; frontend/src/components/positions/chain/RightChain.tsx shows prices only. No time & sales: LiveFeed.tsx is an account-activity tape ('the bottom-strip activity tape'), TickerTape.tsx is a TradingView widget strip — no option trades tape or underlying prints panel for a selected contract.


#### Multi-DTE expirations (1DTE to weeklies) as a rules-gated expansion  `[P3 · effort L · verified missing]`

_require_today_expiry (backend/routers/zerodte.py) 409s any non-today expiry by design. Keep strict-0DTE as the flagship, but scope an optional multi-DTE combine tier: allow 1-7 DTE defined-risk structures, which requires an overnight-holding rule set (EOD margin/gap risk policy, overnight position caps or forced-flatten defaults consistent with the EOD trailing model) and relaxing the expiry gate per combine config rather than globally.


**Why it matters:** Strict 0DTE means five tradeable hours-per-day per symbol and zero product for swing-style options traders; competitors let traders choose. Low urgency because the brand and the entire risk model (EOD trailing, day locks) are built around intraday-only — this is deliberate niche positioning, not an oversight.


**Industry benchmark:** Options Funding supports SPX/SPY/QQQ/IWM including but not limited to 0DTE; futures firms treat overnight holding as a rules problem (banned at most, Swing variants at FTMO/FunderPro sold as an add-on).


**Verification evidence:** backend/routers/zerodte.py:792-806 _require_today_expiry raises a 409 for any non-today expiry ('0DTE-only... that path is closed here'), enforced at both open paths (zerodte.py:836, 1172). No per-combine DTE configuration: grep 'dte' in models/combine.py returns nothing; config.py has only zero_dte_universe. No overnight-holding rule set (no overnight caps, no EOD forced-flatten-for-overnight defaults) anywhere in combine rules or account_tiers.py — the gate is global and hardcoded, not rules-gated per combine.


## Risk engine & enforcement


### P0 — cannot operate as a real business without it


#### Firm-side risk desk with admin role and manual intervention tooling  `[P0 · effort L · verified missing]`

Add an operator/admin role (role or is_admin on backend/models/user.py, admin-gated router) with: per-trader risk view (open positions, live URPL, distance-to-MLL/DLL, combine_events across ALL users — today the ledger at GET /api/combines/events is trader-visible only), manual force-flatten of a trader/combine (reusing order_monitor's _book_close path), account lock/suspend (a tradeable=false flag checked in _require_tradeable), per-user limit overrides set by the FIRM (not just the trader's personal DLL slider), and a human payout approve/deny queue replacing the 1-hour auto-approve timer in backend/jobs/settle_combines.py.


**Why it matters:** A prop firm that pays real money with zero human control surface cannot operate: no one can stop a runaway account, honor a legal hold, deny a fraudulent payout, or answer a rule-dispute ticket with evidence. Every enforcement action is currently irreversible automation visible only to the trader it hit.


**Industry benchmark:** Every real firm runs a risk desk with manual intervention and human review before bans/payout denials (industry pattern: human review + audit trail). The prop-firm OS vendors (FPFX Tech, YourPropFirm, Propriotec, Trade Tech Solutions) sell exactly this admin back office as the core product; Topstep/Apex/MFFU all manually review flagged accounts and payouts.


**Verification evidence:** grep -riE 'admin|superuser|is_staff|role' over backend/*.py and frontend/src returns zero role/authz hits (only unrelated words). backend/models/user.py has no role/is_admin/tradeable/suspended column (full read: email, password_hash, display_name, active_combine_id, copy_lead_combine_id, reset_credits, dll_overrides_json, dll_disabled_json, profit_target_json). backend/main.py:456-472 routes 17 routers — none admin. GET /api/combines/events is trader-scoped: backend/routers/combines.py:343-360 filters CombineEvent.user_id == user.id. Payout approval is a pure 1-hour timer: backend/jobs/settle_combines.py:32-100 (PAYOUT_REVIEW_WINDOW_H=1.0, approve_pending_payouts auto-approves anything past the window). _require_tradeable (backend/routers/zerodte.py:654-727) checks only failed/day-lock/MLL/DLL/scaling-cap — no lock/suspend flag, no firm-set overrides (only the trader's own DLL settings on the user model).


#### Trading-abuse and anomaly surveillance wired into payout approval  `[P0 · effort L · verified missing]`

Build a surveillance job (offline, can run nightly off the existing positions/orders/combine_events tables) that flags: cross-USER trade correlation (same contracts, entry/exit timestamps within seconds, proportional sizes — outside the sanctioned copy_trade feature), a single user hedging opposite sides across their own combines to guarantee one passes, sub-second open-to-close round trips clustered at quote-update lulls (stale-quote/latency arb against the 20s sim-fill model), and gambling signatures (lot-size variance >3x day-to-day, no-stop all-in opens at max cap). Flags land in an admin review queue and BLOCK the payout auto-approve in jobs/settle_combines.py until cleared.


**Why it matters:** Fills are simulated, payouts are real — sim-fill exploits convert directly into cash liabilities. This is the single biggest financial exposure of the sim-prop model: group-passing and self-hedging cost real firms millions and are the reason every operating firm built detection. Today a user can open long on combine A and short on combine B and mathematically guarantee a funded account.


**Industry benchmark:** Industry detection signatures are well documented: ~97% trade-correlation flags, shared IP/device clustering, <800ms round-trip win-rate concentration, payout-request clustering; firms distinguish allowed self-copying from banned cross-trader copying; payout denials cluster into ~12 TOS categories. Apex/MFFU/Topstep all run ML correlation across the user base before paying.


**Verification evidence:** grep -riE 'surveillance|anomaly|abuse|correlation|suspicious|flagged' over backend/*.py hits only request-id correlation middleware (main.py:46,418), rate-limit comments (config.py:107,206), a payments webhook manual-resolution comment (routers/payments.py:234), and seed-data comments. backend/jobs/ contains only categories, collect_options_chain, monitor_orders, prewarm_hot_tickers, refresh_watchlist, renew_combines, seed_trades, settle_combines — no surveillance job. approve_pending_payouts (jobs/settle_combines.py:38-100) has no flag/hold gate of any kind; the only inputs are event age and count. services/copy_trade.py exists (the sanctioned-copy-trade premise is accurate).


### P1 — industry table stakes; traders churn without it


#### News-event trading lockout using the existing economic calendar  `[P1 · effort M · verified missing]`

Wire the display-only calendar (backend/routers/calendar.py, backend/services/calendar_constants.py — FOMC/CPI/OPEX dates already hardcoded for 2026) into enforcement: _require_tradeable in backend/routers/zerodte.py rejects opens within N minutes (config, e.g. 2-10) around Tier-1 events, order_monitor optionally flattens or cancels working orders before the window, and the restriction is stage-aware (stricter for funded than eval) with a per-user permissive toggle mirroring the DLL-override pattern. FOMC at 2:00pm ET is squarely inside RTH, so the 0DTE crowd's favorite max-size punt is currently completely ungated.


**Why it matters:** News punts are the canonical prop-firm abuse: a trader opens max contracts 10 seconds before FOMC for a coin-flip that the trailing-MLL model was never priced for. Firms without the rule bleed funded-account blowup variance and payout liabilities; traders also expect the rule to be published and enforced consistently rather than adjudicated after the fact.


**Industry benchmark:** MFFU requires flat 2 minutes before Tier-1 events on sim-funded; FTMO blocks ±2 min around ~15 high-impact releases/month on standard funded accounts; Topstep bans max-size news punts under conduct rules; Apex bans news-exploitation. An events calendar that enforces nothing is display candy.


**Verification evidence:** services/calendar_constants.py (FOMC_MEETINGS_2026 etc.) is imported only by backend/routers/calendar.py:27-30 (display feed) and backend/jobs/categories.py (watchlist category tagging). grep 'FOMC|calendar_constants|economic' in backend/routers/zerodte.py and backend/services/order_monitor.py: zero hits. _require_tradeable (zerodte.py:654) contains no calendar/event-window logic; the only time gate on opens is _require_market_open (zerodte.py:549-561, market-hours check).


#### Options-native exposure limits: max-loss-per-trade, notional/Greek caps, short-option sizing  `[P1 · effort L · verified missing]`

Replace the contract-count-only cap (backend/services/scaling_plan.py, enforced at zerodte.py:565-592) with options-aware sizing: (1) a max-loss-per-trade gate — defined-risk structures sized by actual max loss vs a fraction of remaining drawdown; (2) naked short calls/puts (supported at zerodte.py:972, unbounded loss) sized by margin-style or delta-notional rules instead of counting the same as a $0.05 lottery ticket; (3) per-symbol concentration caps; (4) optional per-stage delta/vega aggregate caps computed from the chain data already fetched for marks. Alternatively offer a 'defined-risk only' account mode that rejects naked short legs at open.


**Why it matters:** For an options firm, contract count is the wrong risk unit: 5 naked short calls into an FOMC spike can gap through the MLL between 20-second monitor ticks and leave the FIRM holding the loss beyond the trader's floor, while 5 long teenies carry $25 of risk. The one real options-funding competitor differentiates on exactly this.


**Industry benchmark:** Black Eagle (options challenge firm, up to $250K) uses live Greek-based limits and restricts to defined-risk structures (credit spreads/iron condors); Options Funding runs SPX/SPY/QQQ 0DTE with defined-risk rules; Apex 4.0 'intended risk' guidance caps ~30% of drawdown per trade. Contract-count ladders are a futures convention transplanted onto the wrong product.


**Verification evidence:** Enforcement is contract-count-only: services/scaling_plan.py max_contracts + aggregate check in _require_tradeable (zerodte.py:713-727) + _clamp_contracts_to_cap (zerodte.py:596-613). max_loss and greeks ARE computed but display-only: POST /api/zerodte/preview (zerodte.py:1322-1360, PreviewGreeks/max_loss for the trade-ticket detail panel) and journal analytics (routers/journal.py:1146-1194). Naked shorts confirmed supported: strategy = 'short_call'/'short_put' at zerodte.py:970-973, and they consume the cap identically to longs (legs counted per-contract in _open_contracts_for_combine, zerodte.py:565-592). grep -riE 'delta_cap|vega|notional|defined.?risk|concentration' finds no enforcement code — vega/delta hits are all display analytics.


#### Session-close auto-flatten and expiration-day close-out policy  `[P1 · effort S · verified missing]`

Add a configurable force-flatten time (e.g. 3:50-3:55pm ET, half-day aware via services/market_calendar.py) executed by order_monitor: close all open positions with the existing stressed-friction close path and cancel working orders, instead of letting everything ride to 4pm intrinsic settlement (order_monitor.settle_expired_positions). Make the cutoff a tier/stage config so funded accounts can be stricter, and emit a combine_events entry plus a countdown surface in the terminal UI.


**Why it matters:** Riding to the closing print is free optionality the sim gives away: real 0DTE desks force-flatten because the last minutes are pure gamma/pin risk, and for American-style physically-settled underlyings (SPY/QQQ — the platform's default) 'settle at intrinsic' silently waives assignment and after-hours contrary-exercise risk that a live broker would impose. Traders trained on this platform would get destroyed (or firms would get assigned) the moment flow goes live.


**Industry benchmark:** Topstep auto-liquidates at 3:10pm CT, MFFU at 4:10pm ET, Apex requires flat by 4:59pm ET; options-specific guidance (E*TRADE/IBKR expiration-risk docs) is to force-close short options near strikes by a 3:30-3:45 ET cutoff. OCC auto-exercises $0.01+ ITM and contrary instructions run to ~5:30pm — none of which the current settle-at-intrinsic model reflects.


**Verification evidence:** order_monitor's only end-of-day path is settle_expired_positions (backend/services/order_monitor.py:545, settling at intrinsic at the 16:00 ET close per line 127's half-day-aware schedule) — everything rides to expiry. grep -riE 'close_all|force_flatten|auto.?flatten|cutoff|15:50|countdown' over backend and frontend/src: no scheduled-flatten hits (cutoff matches are unrelated payout/IV windows). _flatten_book (order_monitor.py:811) fires only on MLL/DLL/profit-lock breach, never on a clock. A manual trader-initiated POST /api/zerodte/flatten exists (zerodte.py:1500) but is a UI button, not firm policy; no tier/stage cutoff config, no combine_event, no terminal countdown.


#### Operator kill switch and per-symbol trading controls  `[P1 · effort S · verified missing]`

A platform trading-state config (admin-settable, DB-backed so it survives restarts): global 'halt all new opens' switch checked in _require_tradeable, optional 'close-only' mode (closes allowed, opens rejected), and a per-symbol ban list. Should be settable even when the market-data feed is the thing that broke (i.e., no dependency on Alpaca calls). Pairs with the resilience.py API circuit breaker but is a human decision, not an automatic one.


**Why it matters:** When the quote feed goes bad (Alpaca incident, corrupted chain data), every fill the sim books against garbage prices becomes a dispute or a payout liability, and today the only remedy is killing the server process. An incident kill switch is the first tool any trading-ops runbook reaches for.


**Industry benchmark:** Universal ops tooling at real firms and brokerages; prop-firm back offices (FPFX, YourPropFirm) ship trading-state and symbol-block controls as standard, and TopstepX exposes symbol-block even to traders. The MetaQuotes/platform-outage era (2024-25, ~80-100 firms dead) made incident controls an existential lesson.


**Verification evidence:** grep -riE 'kill.?switch|close.?only|halt|trading_enabled|maintenance|ban' over backend: 'halt' appears only in stale-quote comments (zerodte.py:175-188, config.py:128, alpaca_client.py:341); no trading-state switch. backend/models/ has no platform/trading-state table (account_state.py is per-user EOD balance state). services/resilience.py is the automatic API circuit breaker only — nothing human-settable. _require_tradeable (zerodte.py:654) consults no global or per-symbol halt flag.


#### Tradeable-universe allowlist and quote-quality gates on the open path  `[P1 · effort M · verified partial]`

The open endpoints accept any of ~13,000 symbols (zerodte.py resolves any ATM chain expiring today); the curated universe in backend/services/curated_universe.py gates only browse/starring (backend/routers/user_browse.py:84), not trading. Add: (1) an enforced tradeable allowlist (liquid 0DTE names — SPY/QQQ/IWM/major weeklies) configurable by the admin role; (2) a max relative bid-ask spread reject on option legs at open (e.g. refuse fills when spread > X% of mid or mid < $0.05), extending the existing underlying stale-print refusal (zerodte.py:175-192) to the option quotes themselves. Extends the already-deferred OI-capped-sizing item with a reject-tier below it.


**Why it matters:** Illiquid weekly options have fantasy marks — a sim that fills them at spread-crossed quotes still lets traders farm stale or crossed markets on names no market-maker actually quotes, generating 'profits' the firm must pay out but could never hedge. Constraining the universe is the cheapest abuse-surface reduction available.


**Industry benchmark:** Options-funding firms restrict to SPX/SPY/QQQ/IWM-class products (Options Funding explicitly lists them); futures firms enumerate tradeable contracts exhaustively; TOS across the industry reserve the right to void stale-quote fills — better to refuse them at open.


**Verification evidence:** An allowlist EXISTS but is not enforced on opens: backend/config.py:212-231 defines settings.zero_dte_universe = ('SPY','QQQ','IWM') with a comment claiming it is 'the ONLY symbols Trade Desk allows users to open positions on' and gates 'search, chain, opens' — but grep shows it is consumed only by GET /api/market/zero-dte-universe (routers/market.py:247-253) and (historically) ticker_search, which Phase 2 swapped to live chain probing (services/chain_availability.py, consumed by ticker_search.py:22 and user_browse.py:28 for display flags). zerodte.py has ZERO references to zero_dte_universe or curated_universe: _resolve_atm_chain (zerodte.py:193) and _resolve_same_day_quotes (zerodte.py:1112) resolve any symbol with a same-day chain — the config comment is stale. curated_universe gates only starring/logging (user_browse.py:82-86,163-165), as the analyst said. Quote-quality: the stale-UNDERLYING reject exists (zerodte.py:175-192) but option legs are never spread-rejected — services/fills.py:47-90 charges half-spread + size impact and floors fills at $0.01; no max-spread%-of-mid or min-mid gate, and nothing is admin-configurable.


### P2 — competitive


#### Market-halt / LULD / circuit-breaker state model  `[P2 · effort M · verified missing]`

Model an explicit halt state per underlying and market-wide: detect halts (quote-age heuristics already exist at zerodte.py:175; add LULD-band and market-wide L1/L2/L3 detection from feed data or a status endpoint), and define policy while halted — freeze bracket/trailing-stop evaluation in order_monitor (they currently keep evaluating on last-known-good marks), queue rather than skip MLL liquidations past the 60s TTL, and apply widened reopen friction to any close booked in the first seconds after resume so halt-reopen gaps don't fill at pre-halt prices.


**Why it matters:** In a real halt-reopen gap the current monitor either fills stops at stale pre-halt prices (trader windfall/dispute) or skips liquidation entirely and lets a breach run — both are firm-pays outcomes. 0DTE on single names makes LULD halts a when-not-if event.


**Industry benchmark:** The benchmark research flags halted-underlying handling and fast-market circuit breakers as core options-firm mechanics; brokerages universally freeze conditional orders during halts and reopen via auction. The platform's only 'circuit breaker' today is the Alpaca API-call breaker in services/resilience.py.


**Verification evidence:** grep -riE 'LULD|limit.?up|limit.?down' over backend: zero hits; 'circuit' hits are all the API-error circuit breaker (resilience.py) and its consumers (ticker.py:92-221). Halts exist only as comments around the stale-print heuristic (zerodte.py:175-192, config.py:128). Premises confirmed: order_monitor evaluates brackets/liquidations on a last-known-good spot fallback with a 60s TTL (_SPOT_FALLBACK_TTL_SECONDS, order_monitor.py:62-97) with no halt-freeze, no liquidation queueing past the TTL, and no reopen-gap friction.


#### Firm-wide aggregate exposure view (net Greeks/notional per underlying)  `[P2 · effort M · verified missing]`

A firm-level rollup, computed by a job or on-demand admin endpoint: net contracts, notional, and (once Greeks exist) net delta/vega per underlying/expiry/strike across ALL open positions and working orders, including copy-trade multiplication (services/copy_trade.py can turn one lead trade into many follower positions). Surface it as the headline of the risk-desk dashboard with concentration alerts (e.g. >N combines short the same strike into a known event).


**Why it matters:** The firm's real risk is correlated blowup: 200 combines short the same SPY 0DTE straddle into FOMC is a single trade from the firm's perspective. It's also the prerequisite for ever hedging funded flow live — you cannot hedge what you cannot aggregate.


**Industry benchmark:** Firm-aggregate exposure across mirrored accounts is called out in the ops research as 'the real constraint' (SPX has no position limits; the firm's book is the limit); Apex mirrors PA trades via API precisely to manage aggregate exposure before live invites.


**Verification evidence:** grep -riE 'firm|aggregate.*exposure|rollup|all_users|across.*combines' over backend/routers, services, jobs: only per-user/per-combine code. The sole aggregation is _open_contracts_for_combine (zerodte.py:565) — per-combine contract count for the scaling cap. No admin endpoint or job computes cross-user positions; main.py:456-472 routes no such router. services/copy_trade.py exists (fan-out premise accurate) with no exposure aggregation.


#### Trade-conduct rule engine (min hold time, order-rate caps, all-in flags)  `[P2 · effort M · verified missing]`

Per-combine trading-conduct gates enforced at open/close time, distinct from the per-IP HTTP throttle (backend/main.py:400, 240 req/min): configurable minimum hold time before close (anti-microscalping, e.g. 5-10s), max opens per minute per combine, max consecutive same-direction re-entries after stop-outs, and an 'all-in' event emitted when an open consumes >X% of remaining drawdown. Violations emit combine_events entries consumable by the surveillance queue rather than silent rejections.


**Why it matters:** HFT-style rapid-fire against a 20-second sim-fill loop is the easiest exploit on the platform (spam opens/closes to farm favorable mid-crossings), and published conduct rules with in-engine enforcement are what let a firm deny a payout without a he-said-she-said fight.


**Industry benchmark:** Prohibited across the industry: microscalping/tick-scalping, HFT, exploiting sim fills; Apex 4.0 codified 'intended risk' rules (DCA/max-size all-in flagged, ~30%-of-drawdown-per-trade guidance); payout-denial categories explicitly include risk-per-trade breaches.


**Verification evidence:** grep -riE 'hold_time|min_hold|opens_per|microscal|consecutive|all.?in' over backend (excluding tests): zero conduct-rule hits ('consecutive' matches are the API breaker and journal win-streak analytics). The only throttles are the coarse per-IP global HTTP limiter (main.py:399-412, exactly as the analyst cited) and a per-user throttle on FINANCIAL endpoints only — payout/activation/purchase (config.py:199-210, financial_rate_limit_attempts=5/min). Neither touches the trade open/close path; no min-hold, no per-combine open-rate cap, no re-entry or all-in events.


#### Equity-gated scaling ramp activation  `[P2 · effort S · verified partial]`

The (threshold, contracts) ladder structure in backend/services/scaling_plan.py exists but every tier is a single step at $0 — activate a real ramp (e.g. 50K: 3 contracts at start, 5 above +$1,000; 100K: 5→10; 150K: 8→15, tuned for options) keyed off settled balance, plus admin-configurable ladders per tier. Frontend mirror useOpenContractsCount already consumes the cap so the UI follows automatically.


**Why it matters:** Flat caps let a fresh eval go max size on trade one — the exact lottery-pass behavior scaling plans exist to prevent; the trailing-MLL math assumes progressive sizing. It also weakens the funded-stage story: growth-gated size is part of the product traders are buying.


**Industry benchmark:** Topstep scales 5→15 minis by balance milestone (the platform's tiers already copy Topstep's drawdown numbers, so the missing ramp is conspicuous); Apex/MFFU cap contracts per account size with balance-gated increases.


**Verification evidence:** Claim's factual premise confirmed, and the machinery is fully live: backend/services/scaling_plan.py SCALING_PLANS = {'50K':[(0.0,5)], '100K':[(0.0,10)], '150K':[(0.0,15)]} — every tier a single step at $0. max_contracts() already walks (threshold, contracts) steps against settled profit and is enforced on opens (_require_tradeable zerodte.py:713 + _clamp_contracts_to_cap zerodte.py:596); frontend/src/hooks/useOpenContractsCount.ts exists and is consumed by TradeTicket/RightChain. Only the multi-step ladder values and admin-configurable ladders are absent. CAVEAT for the parent agent: the module docstring says the flat cap is 'per the account owner's preference — a higher, simpler cap than Topstep's ramped build-equity table', i.e. this is a deliberate product decision, not an oversight.


### P3 — polish


#### Inactivity / dormancy rule for funded accounts  `[P3 · effort S · verified missing]`

A settle-time check (natural home: backend/jobs/settle_combines.py) that flags funded/passed combines with no trade in N days (config, industry range 7-30), emits a warning combine_event/email at N-7, and suspends or expires the account at N — with the admin role able to extend. Track last-trade-at per combine (derivable from the orders table today).


**Why it matters:** Every dormant funded account is an open-ended payout liability sitting on the books with a stale KYC/risk picture; firms bound this tail universally. Also feeds honest liability accounting for the billing/finance side.


**Industry benchmark:** Sim-funded accounts at Apex/MFFU/Tradeify require a trade every ~7-30 days or the account closes; monthly PA/data fees enforce activity as a backstop. No equivalent exists in this codebase.


**Verification evidence:** grep -riE 'inactiv|dormant|last_trade' over backend (excluding tests): 'dormant' hits are only feature-flag comments (realtime_feed, montecarlo, ticker_selection, stripe); no inactivity logic. backend/jobs/settle_combines.py contains only lifecycle settlement + payout auto-approve (lines 32-140) — no last-trade check. backend/models/combine.py has no last_trade_at/activity column (grep 'last_trade|trade_at|activity' returns nothing). No warning event, suspension, or admin extension anywhere.


## Payments, payouts & business ops


### P0 — cannot operate as a real business without it


#### Payout disbursement rail + payout-method onboarding  `[P0 · effort L · verified missing]`

There is no way for money to leave the platform. Add (1) payout-method collection on the User/profile model — at minimum an ACH (US) and international-wire/Wise or Rise/Deel destination, stored as a separate PayoutMethod table with verification status, never in the settings JSON; (2) a disbursement adapter behind the existing approve_pending_payouts job in backend/jobs/settle_combines.py so 'payout_approved' transitions to 'payout_sent'/'payout_settled' only when the rail confirms, with failure/retry states; (3) a payout-method step in frontend/src/pages/PayoutsPage.tsx gating the request dialog. Even in simulated mode, model the full state machine (requested → approved → sent → settled / failed) so a real rail can be dropped in.


**Why it matters:** 'Paid' today is an event row — the single most load-bearing promise of a prop firm (you get real money) has zero machinery behind it. Cannot launch, cannot even credibly demo the funded-trader lifecycle end to end.


**Industry benchmark:** Rise is the prop-firm favorite ($1.5B+ volume, 190+ countries, stablecoin + fiat), Apex and MFFU both use it; MFFU also runs Deel; Topstep/Tradeify offer direct ACH for US plus international wire ($25–45 fee). Firms run 2–3 rails in parallel because of country gaps; first payout 1–3 days, later ones 24–48h.


**Verification evidence:** No PayoutMethod model (backend/models/ contains only account_state, alert, auth_session, combine, combine_event, historical_earnings_event, options_snapshot, payment, ticker_selection, trade, user, user_star, watchlist_item). Grep for payoutmethod|payout_method|bank_account|routing_number|iban across backend/ and frontend/src → zero hits. Payout states are only 'payout_requested' → 'payout_approved' (backend/services/combine_state.py:230 PAYOUT_DEBIT_TYPES = ("payout", "payout_requested"); backend/jobs/settle_combines.py approve_pending_payouts). No payout_sent/payout_settled/failed states exist anywhere. frontend/src/pages/PayoutsPage.tsx has no method-collection step (grep method|verif → empty).


#### KYC / identity verification gate before first payout  `[P0 · effort M · verified missing]`

No identity fields, no provider integration, no gate. Add a KYCVerification model (status: unverified/pending/verified/rejected, provider ref, document + liveness result), integrate one provider (Stripe Identity is the least new-vendor surface given services/payments.py already wraps Stripe; Sumsub/Persona/iDenfy are the industry alternatives), and block POST /api/combines/{id}/payout in backend/routers/combines.py (~line 661) until status=verified. Frontend: a verification step on PayoutsPage before the first request. Include sanctions/geo screening (OFAC list, blocked countries) at the same checkpoint.


**Why it matters:** Payment rails and banking partners impose BSA/AML obligations the moment real money moves — no rail will disburse to unverified identities. Also the firm's only defense against one person farming payouts across many accounts.


**Industry benchmark:** Universal 2025–26 pattern: no KYC at challenge purchase, mandatory document + liveness verification before first payout (FTMO gates 'FTMO Trader' status behind it; futures firms verify at first payout, 1–3 day turnaround via Sumsub/iDenfy/Veriff). GENIUS Act (July 2025) extended BSA/KYC to stablecoin payout chains, so crypto rails don't dodge it.


**Verification evidence:** Grep for kyc|ofac|sanction|sumsub|persona|identity-verification across backend/ and frontend/src → zero relevant hits (initial matches were substring false positives like 'verification' in unrelated comments). No KYC model in backend/models/. POST /api/combines/{id}/payout in backend/routers/combines.py has no verification dependency. frontend/src/pages/PayoutsPage.tsx grep for verif|kyc|identity → empty.


#### Tax document collection (W-9/W-8BEN) and 1099-NEC issuance  `[P0 · effort M · verified missing]`

Zero tax machinery. Before the first payout, collect W-9 (US) or W-8BEN (non-US) with legal name, address, and TIN — new TaxProfile model plus a form step in the payout onboarding flow. Track cumulative annual payouts per user and generate 1099-NEC data for US traders crossing $600/yr. Practical shortcut: if the payout rail is Rise or Deel (see rail gap), both generate contractor agreements and jurisdiction-appropriate tax docs automatically — pick the rail with this in mind and this gap collapses into configuration.


**Why it matters:** Legally required once real payouts exist: US prop traders are independent contractors and the firm must file 1099-NEC at $600+; paying without W-9/W-8BEN on file creates backup-withholding liability for the firm itself.


**Industry benchmark:** Industry norm: W-9 at payout onboarding, 1099-NEC at $600+/yr, W-8BEN for foreign traders; Rise and Deel automate the whole chain, which is a major reason prop firms choose them.


**Verification evidence:** Grep for W-9|W9|W-8|1099|TIN|withhold|tax → only substring false positives ('AlertIn', 'continue', 'SettingsConfigDict' match 'tin'; 'syntax' matches 'tax'). No TaxProfile model in backend/models/. Payment model (backend/models/payment.py) has no tax fields; no cumulative-payout tracking per user exists.


#### Admin/operator console with role-based access  `[P0 · effort L · verified missing]`

No is_admin/role on User (confirmed: backend/models/user.py has only auth + trading fields), no admin router, no operator UI. Build: role column + admin-only dependency in backend auth; an /admin surface with (1) user search/detail/suspend, (2) payout review queue (see next gap), (3) payment ledger view with operator-initiated refund, (4) combine inspection (rule breaches, equity curve, event log), (5) business dashboard: MRR, active combines by tier, churn, outstanding payout liability (sum of funded balances above start × split). Everything operator-shaped today requires direct sqlite access.


**Why it matters:** A single-operator business still needs an operator seat: every support ticket ('why was my payout delayed', 'refund me', 'my account was wrongly breached') currently ends in hand-written SQL against the production DB, which is how ledgers get corrupted.


**Industry benchmark:** A vertical 'prop-firm OS' market exists precisely for this back office: FPFX Tech, YourPropFirm, Propriotec, Trade Tech Solutions all ship CRM/admin + rule-engine + payout-automation consoles; transparent dashboards measurably cut support load.


**Verification evidence:** backend/models/user.py User fields verified in full: email, password_hash, display_name, active_combine_id, copy_lead_combine_id, reset_credits, dll_overrides_json, dll_disabled_json, profit_target_json, created_at, updated_at — no role/is_admin. backend/routers/ has no admin router; backend/main.py:456-472 include_router list has none. frontend/src/pages/ has no admin page (11 pages, all trader-facing). Grep mrr|churn|liability|suspend → zero product hits. Note: routers/user_browse.py is symbol stars/popular-slate browse, not user administration.


#### Human payout review with deny/hold path and reason codes  `[P0 · effort M · verified missing]`

The 'review desk' in backend/jobs/settle_combines.py is a pure timer — grep confirms no denied/held state exists anywhere in the payout flow. Add payout states denied and on_hold with operator action from the admin console, a required reason code on denial (drawn from the ~12 industry TOS categories: prohibited-strategy trades, news-window abuse, copy-trading correlation, etc.), automatic re-credit of the denied amount to the epoch-scoped available balance (today a denied request would permanently eat the trader's withdrawable profit since available = split-of-profit minus prior requests), and trader-facing status + reason on PayoutsPage. Keep the timer as an auto-approve default for clean accounts.


**Why it matters:** Payout review is where a prop firm defends its economics — auto-approving every request after a timer means any exploit (coordinated passing, stale-quote scalping) pays out automatically. Denial without a ledger re-credit path would also silently confiscate trader funds.


**Industry benchmark:** Every real firm holds first payouts for manual review (first payout slowest, 1–3 days) and documents denial categories; enforcement pattern is human review + audit trail before any forfeiture. Payout denials cluster into ~12 documented TOS categories across firms.


**Verification evidence:** backend/jobs/settle_combines.py approve_pending_payouts is a pure timer: 'payout_requested' older than PAYOUT_REVIEW_WINDOW_H (default 1.0h, line 35) auto-approves by writing 'payout_approved' (lines 42-92). Grep payout_denied|on_hold|denied across backend → only the payout_approved lines. No reason codes, no re-credit path. frontend/src/pages/PayoutsPage.tsx grep denied|hold|reason → empty.


#### Card-on-file recurring billing + dunning (extends known Stripe-wiring deferral)  `[P0 · effort L · verified missing]`

Beyond the known 'wire the Stripe frontend' item: the renewal engine in backend/jobs/renew_combines.py writes Payment rows that cannot fail — there is no saved payment method to charge. Needed specifics: Stripe SetupIntent/saved-PM at first checkout (or Stripe Billing subscriptions per combine), off-session charge attempts in the renewal job, a failed-renewal state machine (retry schedule → email → grace period → auto-archive combine), payment-method management UI in the SettingsPage Billing tab (add/replace card, default PM), and webhook handling for invoice.payment_failed. The existing checkout/webhook code in backend/services/payments.py and routers/payments.py is one-shot Checkout only.


**Why it matters:** The whole revenue model is monthly subscriptions ($69–169/mo per combine) — without card-on-file and dunning, month-2 revenue is zero and every renewal 'succeeds' fictitiously. This is the difference between a payments demo and a subscription business.


**Industry benchmark:** Topstep ($49/$99/$149/mo), Apex, MFFU all bill monthly with saved payment methods and suspend/close accounts on failed rebills; monthly PA/data fees are also how funded-account inactivity is enforced.


**Verification evidence:** Grep setupintent|setup_intent|payment_method|off_session|dunning|invoice across backend/services/payments.py, backend/routers/payments.py, backend/jobs/renew_combines.py, backend/models/payment.py → zero hits. renew_combines.py docstring confirms auto-renew writes 'one simulated Payment... status paid' that cannot fail — no retry/grace/failed-renewal machine. services/payments.py:3-4 states the module is dormant unless stripe_secret_key set and offers only one-shot create_checkout_session (line 68). No PM-management UI in SettingsPage Billing tab (grep empty).


### P1 — industry table stakes; traders churn without it


#### Coupon / promo-code system  `[P1 · effort M · verified missing]`

Confirmed zero coupon machinery. Add a PromoCode model (code, percent/fixed discount, applies-to: first-period vs recurring, tier restrictions, expiry, max redemptions, per-user limit), validation endpoint, a code field on the checkout in frontend/src/pages/NewCombinePage.tsx, discount recorded on the Payment row (list price vs paid amount for revenue reporting), and pass-through as Stripe promotion_codes in services/payments.py when the real rail is on. Also needed for renewal pricing (some promos discount only period one).


**Why it matters:** Prop firms acquire nearly all customers through discount promos — launching at rack rate with no promo field means every marketing campaign, affiliate deal, and win-back email has no mechanism to land.


**Industry benchmark:** Apex runs 80–90% off coupons near-continuously (50% 'permanent floor'), Tradeify ~40% codes, MFFU frequent sales, FundedNext rotating flat-%/BOGO promos; even premium-positioned FTMO runs site promos. Discount culture is the sector's defining acquisition motion.


**Verification evidence:** Grep promo|coupon|discount across backend/ and frontend/src → zero hits (all 'commission' matches are brokerage commission_per_contract in backend/config.py:119 and trading P&L code). No PromoCode model in backend/models/. frontend/src/pages/NewCombinePage.tsx has no code input (only 'account_code' display at line 488). Payment model has no list-price-vs-paid fields.


#### Affiliate / referral program with attribution and commission ledger  `[P1 · effort L · verified missing]`

Zero referral code (confirmed by grep). Build: per-user (or dedicated-affiliate) referral codes and links, cookie/last-touch attribution at signup + purchase, a commission ledger (percent of purchase AND reset payments, since resets are a major revenue line), an affiliate dashboard page (clicks, signups, conversions, accrued/paid commissions), minimum-payout threshold, and commission payout via the same disbursement rail as trader payouts. Tie promo codes to affiliates so codes double as attribution.


**Why it matters:** Affiliates are the primary acquisition channel for the entire sector; a firm without one is buying every customer with paid ads at full CAC.


**Industry benchmark:** Apex 15% recurring with 6-month cookie ($1K min payout), MFFU 12% on evals AND resets, FTMO up to 39% tiered Bronze→Platinum, FunderPro up to $1,200/referral with weekly affiliate payouts.


**Verification evidence:** Grep referral|affiliate|attribution across backend/ and frontend/src → zero hits; every 'commission' match is the simulated brokerage commission (backend/config.py:114-124, routers/journal.py:101-190). No referral fields on User (backend/models/user.py verified in full), no affiliate dashboard page in frontend/src/pages/.


#### Invoices / receipts with billing address capture  `[P1 · effort M · verified missing]`

GET /api/payments/history is a raw JSON list rendered in the SettingsPage Billing tab; there is no artifact per charge. Add: sequential invoice numbering, billing name/address capture at first purchase (also prerequisite for the tax-docs and sales-tax gaps), a per-Payment receipt view (HTML print-to-PDF is enough at this scale) downloadable from the Billing tab, and email delivery once the known email-infrastructure item lands. If Stripe is live, Stripe's hosted invoices/receipts can carry most of this — but the placeholder rail needs its own artifact for parity.


**Why it matters:** Traders expense these fees and file taxes with them; 'where is my receipt' is a guaranteed day-one support ticket, and card networks effectively require receipts for dispute defense.


**Industry benchmark:** Table stakes at every real subscription business; FTMO/Topstep issue receipts per charge and traders routinely deduct evaluation fees as business expenses.


**Verification evidence:** GET /api/payments/history at backend/routers/payments.py:148-149 returns a JSON list; grep invoice|receipt|billing.address across backend and frontend/src → only frontend/src/lib/feed.ts:55 ('refunded' status string). backend/models/payment.py has no invoice number or billing name/address columns (full model read: user_id, combine_id, tier, amount, status, created_at). SettingsPage Billing tab (lines ~380-403) renders the raw charge history with 'no card is charged' copy — no per-charge artifact.


#### Trader agreement e-sign at funding  `[P1 · effort M · verified missing]`

Nothing is signed anywhere — no ToS acceptance timestamp at signup, no funded-trader agreement. Add: (1) versioned ToS/refund-policy acceptance recorded at account creation and at purchase; (2) an independent-contractor / funded-trader agreement presented and e-signed (checkbox + typed name + timestamp + doc version stored is legally sufficient; DocuSign-class integration optional) as a gate inside POST /api/combines/{id}/activate-account in backend/routers/combines.py before the funded stage unlocks.


**Why it matters:** The agreement is what makes payouts legally 'performance rewards on simulated accounts' and traders independent contractors — without it the firm has no enforceable rule set, no basis for payout denial, and unclear tax posture.


**Industry benchmark:** FTMO signs the FTMO Account Agreement post-verification; all four CFD majors use e-sign agreements at funding; Rise/Deel auto-generate contractor agreements as part of payout onboarding.


**Verification evidence:** No ToS/agreement fields in backend/models/user.py (full field list verified). Grep terms|agree|policy in frontend/src/pages/SignUpPage.tsx and NewCombinePage.tsx → zero hits (no checkbox at signup or checkout). POST /api/combines/{id}/activate-account (backend/routers/combines.py:817 activate_account) charges the $149 fee, records the event, and unlocks payouts with no agreement gate in its body.


#### Payout abuse detection feeding the review queue  `[P1 · effort L · verified missing]`

Nothing flags risky payouts. The platform already has copy-trading (copy_lead_combine_id on User) and full order/fill history, so the signals are computable: same-IP/device-fingerprint clusters across accounts (requires capturing IP + user-agent at login/order time — not stored today), trade-correlation across users (same instrument/side/timing), sub-second round-trip win-rate concentration (stale-quote scalping against the sim fill engine), and no-stop all-in sizing patterns. Score each payout request and route high-risk ones to the manual review queue (see deny/hold gap) instead of the auto-approve timer.


**Why it matters:** This is the loss channel that kills prop firms: coordinated group-passing and sim-fill exploitation are pure payout extraction against a simulated book — the firm pays real money against fake edge. An auto-approving timer with no flags is an open vault.


**Industry benchmark:** Firms run ML correlation across the whole user base (~97% correlation flags), shared IP/device fingerprinting (30 accounts from one AWS IP = instant flag), and <800ms round-trip win-rate signatures; payout requests clustering at the same stage is a documented tell. Enforcement is human review + audit trail before ban.


**Verification evidence:** No IP/device capture is stored: backend/models/auth_session.py AuthSession has only token_hash, user_id, created_at, expires_at; _client_ip (backend/services/rate_limit.py:156) is used solely for in-memory rate-limit keying (backend/main.py:408), never persisted. Grep ip_address|user_agent|fingerprint in backend (non-test) → only those rate-limit lines. No risk scoring anywhere in backend/jobs/settle_combines.py or the payout endpoint — approval is the unconditional timer described above.


#### Refund policy surface + operator refund tool + dispute ops  `[P1 · effort M · verified partial]`

Refund handling exists only inside the dormant Stripe webhook (_refund_payment in backend/routers/payments.py ~line 293) and is unreachable in placeholder mode. Add: a published refund policy page (e.g. refundable within N days if no trades placed — state it explicitly at checkout in NewCombinePage.tsx), an operator-initiated refund action in the admin console that reuses _refund_payment's ledger + archive logic for both rails, and chargeback ops: evidence capture (signup IP, ToS acceptance, trade activity) for dispute response, plus auto-ban/flag on chargeback since a disputed evaluation fee from a trader who then requests payouts is fraud.


**Why it matters:** Card-not-present subscription products live or die on dispute ratio — without a policy and dispute-evidence workflow, Stripe will terminate the account once real charges flow; without an operator refund tool every goodwill refund is a DB surgery.


**Industry benchmark:** The5%ers offer a 14-day money-back guarantee pre-trading; FTMO refunds the challenge fee with first payout; all firms publish explicit refund policies and fight disputes with activity evidence.


**Verification evidence:** _refund_payment exists at backend/routers/payments.py:293 and genuinely handles both charge.refunded and charge.dispute.created (lines 186-187, 334-335: marks payment 'refunded', cancels resting orders, archives the purchased combine) — but only via the Stripe webhook, which is dormant in placeholder mode (services/payments.py:3-4, stripe_enabled() line 31). No published refund policy page (grep refund in frontend/src → only feed.ts:55 status label; NewCombinePage.tsx has none), no operator-initiated refund (no admin surface exists at all), no chargeback evidence capture (no IP/ToS-acceptance stored per the admin and e-sign verdicts), no auto-ban on dispute (dispute just archives the combine).


#### Sales tax / VAT on evaluation fees  `[P1 · effort M · verified missing]`

Prices in backend/services/pricing.py are tax-naive: no tax calculation, no billing-country capture, no tax line on Payment rows. Minimal path: capture billing country (shared with the invoice gap), enable Stripe Tax on checkout sessions in services/payments.py (automatic_tax), and record tax amount separately on the Payment row so revenue reporting is net-of-tax. Digital-service evaluation fees are VAT-able in the EU/UK from the first sale regardless of firm location.


**Why it matters:** Selling monthly digital subscriptions internationally without VAT/GST handling creates accruing tax liability in every jurisdiction with a digital-services rule; retrofitting tax onto an existing ledger is far more painful than launching with it.


**Industry benchmark:** All major firms sell internationally and price with tax handled at checkout (Stripe Tax / Paddle-style merchant-of-record patterns are the standard for challenge sellers).


**Verification evidence:** Grep automatic_tax|billing_country|vat|sales_tax across backend and frontend/src → zero hits. backend/services/pricing.py:1-40 is a flat price matrix with no tax concept; backend/models/payment.py has no tax column; services/payments.py checkout sessions do not set automatic_tax (grep empty); no billing-country capture anywhere.


### P2 — competitive


#### Tier upgrade/downgrade with proration  `[P2 · effort M · verified missing]`

Tier, pricing path, and split are locked for the life of a combine (per the pricing.py docstring and NewCombinePage copy). Add: upgrade path 50K→100K→150K that archives-and-reprovisions (or rescales) the combine with a prorated charge for the remainder of the period, downgrade at next renewal, and split switching (80/20 ↔ 50/50) effective next period. Requires a proration helper in services/pricing.py and a change-plan dialog in the Billing tab.


**Why it matters:** Traders who outgrow the 50K or want to cut costs must cancel and rebuy, losing progress — a churn moment competitors don't impose; it also suppresses natural expansion revenue.


**Industry benchmark:** Subscription-standard; futures firms let traders run multiple sizes and move between them (MFFU up to 10 evals; Topstep multiple combines), and CFD firms sell split/plan changes as paid add-ons at checkout (FundedNext 95%-split add-on, FunderPro 90%-split add-on).


**Verification evidence:** Grep upgrade|downgrade|prorat across backend/services/pricing.py, backend/routers/combines.py, frontend/src/pages/NewCombinePage.tsx, SettingsPage.tsx → single hit: NewCombinePage.tsx:33 marketing copy framing 80/20 as 'a +$10/mo upgrade'. pricing.py docstring confirms path and split are 'chosen at purchase and fixed for the life of the combine'. No change-plan endpoint or dialog exists.


#### Checkout add-ons and upsell layer  `[P2 · effort M · verified missing]`

Checkout in NewCombinePage.tsx sells exactly tier x path x split. Add an add-on framework at checkout and in-lifecycle: better-split purchase (the 50/50→80/20 machinery exists structurally in pricing.py, invert it into a paid 90/10 add-on), faster-payout add-on (skips the review-window timer for clean accounts), and paid reset bundles. Each is a Payment row type plus a flag the existing payout/reset logic reads.


**Why it matters:** Add-on monetization is the sector's highest-margin revenue layer and raises average order value without new acquisition spend.


**Industry benchmark:** Defining 2025–26 trend: FundedNext sells a 95% split add-on (+~30% fee) and payout-speed upgrades at checkout; FunderPro sells 90% split, Swing, and daily-vs-weekly reward choice as add-ons.


**Verification evidence:** Grep add.on|addon|upsell|faster.payout|90/10 across backend and frontend/src → zero relevant hits. Checkout in frontend/src/pages/NewCombinePage.tsx sells only tier x pricing_path x split (mirroring backend/services/pricing.py PricingPath/SplitToken Literals). Payment.status enum (backend/models/payment.py: paid | activation_paid | reset_paid | pending | failed | refunded | migration_grant) has no add-on type.


#### Trust signaling: payout certificates and public payout stats  `[P2 · effort S · verified missing]`

Nothing celebrates or proves payouts. Add shareable payout certificates (image/PDF generated per approved payout: amount, date, account size — shareable link), a combine-passed certificate at funding, and a public stats endpoint/page (total paid out, on-time rate) fed from the payments/payout ledger that already exists.


**Why it matters:** Prop firms sell trust in a scandal-prone sector; trader-shared certificates are free acquisition and the standard social-proof loop — absence reads as 'they don't actually pay'.


**Industry benchmark:** FTMO and FundedNext issue shareable challenge-pass and payout certificates; FundedNext publishes $284M+ paid, FunderPro $21M+, FTMO advertises ~99.8% on-time payouts.


**Verification evidence:** Grep certificate across backend/routers and frontend/src/pages → zero hits ('share' matches are all per-share options math in routers/journal.py and profit_split docs). No public stats endpoint in backend/main.py router list; no shareable artifact generation anywhere; no combine-passed certificate at funding (activate_account in routers/combines.py produces only the CombineOut response and ledger events).


## Product surface, growth & engagement


### P0 — cannot operate as a real business without it


#### Legal & consent surface (ToS, Privacy, Refund policy, risk disclosure)  `[P0 · effort M · verified missing]`

Add routed /terms, /privacy, /refund-policy, and /risk-disclosure pages (static content pages linked from landing footer, signup, and checkout). Add a required 'I agree to the Terms and simulated-trading disclosure' checkbox at signup and at combine purchase, and persist acceptance server-side (user_id, doc version, timestamp) in a new consent table so the firm can prove agreement per document version. The landing footer already has a simulated-trading disclaimer line in frontend/src/pages/LandingPage.tsx but zero actual legal documents exist anywhere in frontend/src.


**Why it matters:** The platform takes money (combine fees, resets, billing periods) and pays money out (payout desk) with no terms governing either. Every payout-denial, reset, or refund dispute is unresolvable without agreed terms; payment processors and payout rails will not onboard a merchant without ToS/Privacy URLs; and the whole simulated-capital model legally depends on a signed disclosure that this is not brokerage.


**Industry benchmark:** Universal: FTMO signs an Account Agreement post-verification; Apex/Topstep/Tradeify payout denials are enforced against ~12 documented TOS categories; every benchmarked firm has ToS/Privacy/refund pages linked from the footer and gates checkout on acceptance.


**Verification evidence:** Full route table in frontend/src/App.tsx (lines 72-95) has no /terms, /privacy, /refund-policy, or /risk-disclosure. grep -riE 'consent|acceptance|tos_version' over backend/*.py returned zero hits (no consent table/model). grep for 'checkbox|agree|terms' in frontend/src/pages/SignUpPage.tsx and NewCombinePage.tsx found no agreement checkbox — only 'Simulated checkout' copy. The only legal-ish text is the disclaimer line at frontend/src/pages/LandingPage.tsx:551 ('Simulated trading only...'), exactly as the claim states.


#### Admin / operator console  `[P0 · effort L · verified missing]`

There is zero operator tier: no is_admin/role field on backend/models/user.py (verified by grep), no admin routes, no admin pages. Build: (1) a role column + admin-gated FastAPI router, (2) an /admin frontend area with user search/detail (accounts, combines, billing history, journal), (3) a real payout-review queue UI replacing the simulated auto-resolve window in backend/routers/combines.py (approve/deny with reason codes that surface to the trader), (4) manual actions: grant reset credit, refund a charge, terminate/reinstate a combine, adjust a balance with an audit-log entry, (5) a flags view for rule-violation events the risk engine already emits.


**Why it matters:** A prop firm's core business operation is human review — payouts, rule disputes, refunds, abuse. Today no human can approve a payout, comp a reset, or answer 'why was my account terminated' because there is no interface to the data. The single-operator can only sqlite3 into the database. This is the single largest missing tier for launch.


**Industry benchmark:** A vertical 'prop-firm OS' market exists precisely for this: FPFX Tech, YourPropFirm, Propriotec, Trade Tech Solutions all sell challenge CRM + admin back office + payout review as the standard stack; Topstep/Apex run human review + audit trail before any ban or payout denial.


**Verification evidence:** grep -riE 'is_admin|\brole\b|superuser|operator' across backend/*.py returned nothing (backend/models/user.py has no role column — only email, password_hash, display_name, active_combine_id, copy_lead_combine_id, reset_credits, DLL/profit-target JSON). No admin router exists (backend/routers/ = account, alerts, analytics, auth, calendar, combines, journal, journal_media, market, news, payments, ticker, ticker_search, user_browse, watchlist, zerodte). grep 'admin' over frontend/src returned zero files. Payout review is indeed the simulated auto-resolve: backend/routers/combines.py:674-675 ('the settle pass approves it after the review window' via jobs/settle_combines.py) — no human review UI.


#### Account recovery + transactional lifecycle email matrix  `[P0 · effort M · verified missing]`

Extends the known 'email infrastructure' deferred item with the full required surface: (1) forgot-password link on frontend/src/pages/SignInPage.tsx (currently only 'Create an account' exists — verified) + token-based reset endpoint in backend/routers/auth.py + reset page; (2) email verification at signup; (3) the transactional matrix a prop firm cannot run without: combine passed/failed/terminated, payout requested/approved/denied/paid, billing charge receipt + upcoming-rebill notice, reset-credit granted, pre-breach warning digest, inactivity warning. Implement as a provider-agnostic mailer service (Resend/Postmark adapter + console/log adapter for the current simulated mode) with a templates directory, so the simulated deployment logs emails and a real deployment sends them.


**Why it matters:** A locked-out user today can never recover their account — a hard launch blocker on its own. Beyond that, every money-state transition (charged, passed, funded, payout paid) is invisible unless the trader happens to be logged in; disputed charges and missed payout-denial reasons become support fires; rebills without advance notice are a chargeback and card-network compliance problem.


**Industry benchmark:** All benchmarked firms run email as the primary lifecycle channel (payout status, pass certificates, rebill notices); notifications at Topstep/Apex/MFFU are 'largely email/Discord, not in-product'. FTMO's ~99.8% on-time payout stat is communicated per-payout by email.


**Verification evidence:** backend/routers/auth.py exposes only POST /signup, /signin, /change-password, /signout, GET /me (lines 74-158) — no forgot-password/reset-token/verification endpoints. frontend/src/pages/SignInPage.tsx has only the 'Create an account' link (lines 53-58), no forgot-password. grep -riE 'mailer|smtp|resend|postmark|sendgrid|send_email' over backend returned only an unrelated comment in routers/payments.py:181. No templates directory, no email adapter of any kind.


### P1 — industry table stakes; traders churn without it


#### Rules help center + FAQ + support channel  `[P1 · effort M · verified missing]`

In-app education is 11 glossary terms (frontend/src/lib/glossary.ts) and ~27 tooltips; combine rules exist only as inline hints. Build a routed /rules (or /help) section: per-tier rule pages generated from the real lib/tierSpecs.ts + lib/pricing.ts (so numbers never drift), with worked examples of EOD-trailing drawdown math, DLL modes, consistency/profit-target-lock, payout eligibility gates, and the 0DTE-specific policies (session-close auto-flatten, cash-settled product set); an FAQ page; and a support contact surface (contact form that writes a support_tickets table the admin console can read, or at minimum a mailto + Discord link in the footer and Help overlay).


**Why it matters:** Rule disputes are the #1 support load at every prop firm, and traders who misunderstand trailing-drawdown math churn angrily and issue chargebacks. Right now a trader who fails a combine has no page explaining why the rule works that way and no way to contact anyone — there is zero support channel in the entire product.


**Industry benchmark:** help.topstep.com, apextraderfunding.com/help-center, help.myfundedfutures.com, help.tradeify.co are all extensive rule-explainer help centers; industry experience is that 'transparent dashboards measurably cut tickets'. Support via Intercom/Zendesk + Discord is the standard stack layer.


**Verification evidence:** No /rules, /help, or FAQ route in frontend/src/App.tsx route table. In-app education is exactly as claimed: frontend/src/lib/glossary.ts has 11 terms, consumed by frontend/src/components/help/HelpOverlay.tsx (glossary search + hotkey reference + tour replay — an overlay, not a routed rules section). frontend/src/lib/tierSpecs.ts and lib/pricing.ts exist as claimed sources. grep -riE 'support_ticket|contact|discord|mailto' found no support surface (backend hits were unrelated: zerodte.py, order_monitor.py). No FAQ, no ticket table, no contact form.


#### SEO, social meta, robots.txt and sitemap  `[P1 · effort S · verified missing]`

frontend/index.html has no meta description, no Open Graph or Twitter card tags (verified); frontend/public/ contains only favicon.svg — no robots.txt, no sitemap.xml, no OG image. Add: meta description + canonical, OG/Twitter tags with a branded 1200x630 share image, robots.txt, sitemap covering the public routes (landing, pricing anchor, rules/FAQ/legal pages once built), and JSON-LD (Organization + Product/Offer for the three tiers). Also add per-route titles via a small document-title hook since this is an SPA.


**Why it matters:** The landing page is invisible to search and renders as a bare link when shared in Discord/Twitter — which is exactly where prop-firm customers are acquired. Every affiliate or word-of-mouth share currently produces an unfurl with no image, no description, no pitch.


**Industry benchmark:** All benchmarked firms are SEO-heavy (comparison-review sites like proptradingvibes/tradetanto drive the funnel) and their share links unfurl into payout-stat cards; affiliates sharing links is the sector's primary acquisition channel.


**Verification evidence:** frontend/index.html read in full: only charset, viewport, favicon link, <title>Trade Desk</title>, and Google Fonts — no meta description, no og:/twitter: tags, no canonical, no JSON-LD. ls frontend/public/ shows only favicon.svg (no robots.txt, sitemap.xml, OG image; find for robots.txt/sitemap*/manifest* outside node_modules returned nothing). grep 'document.title|useTitle|helmet' over frontend/src returned zero — no per-route titles.


#### Product analytics / funnel telemetry  `[P1 · effort S · verified missing]`

No tracking SDK or event capture exists anywhere (verified in map: index.html, main.tsx, package.json clean). Add funnel instrumentation for landing view → signup → checkout started → combine purchased → first trade → passed → funded → payout requested. Given single-operator + SQLite, the pragmatic build is a first-party events endpoint (POST /api/events with event name + properties) written to an analytics table, plus a small admin funnel view; alternatively drop in self-hosted PostHog/Plausible. Instrument the ~10 conversion moments in LandingPage, SignUpPage, NewCombinePage, and the funded/payout flows.


**Why it matters:** The business cannot answer its only existential questions — landing conversion, eval attach rate, pass rate by tier, reset attach rate, payout ratio — which are the levers of prop-firm unit economics. Pricing and discount decisions are currently blind.


**Industry benchmark:** Prop firms live on funnel math: Apex's perpetual 80-90% coupon strategy and Topstep's reset-revenue line are only tunable because they measure eval-purchase → pass → payout ratios; every firm's 'prop-firm OS' (FPFX etc.) ships funnel dashboards.


**Verification evidence:** grep -iE 'posthog|plausible|segment|amplitude|mixpanel|gtag' over frontend/package.json, src/main.tsx, index.html: zero hits. grep 'api/events|track(|telemetry' over backend + frontend/src: no events endpoint or analytics table. backend/routers/analytics.py is trade-journal analytics ('GET /api/analytics — cross-trade aggregations for the analytics tab', + /montecarlo), not funnel telemetry — confirmed by reading its docstring.


#### Referral / affiliate / promo-code engine  `[P1 · effort L · verified missing]`

Zero exists (only the hardcoded SPLIT_DISCOUNT constant). Build in two layers: (1) Promo codes — a promo_codes table (code, % or $ off, applies-to tier/reset, expiry, max redemptions), a code field on the NewCombinePage checkout step wired into backend/services/pricing.py, and admin CRUD for campaigns; (2) Referral/affiliate — per-user referral links (?ref=), cookie/first-touch attribution stored at signup, commission accrual on purchases and resets (12-15% is the norm), and a 'Refer' page showing clicks/signups/earnings with commission payouts flowing through the existing payout machinery.


**Why it matters:** Affiliates are the sector's primary acquisition channel and discount codes are the sector's primary conversion trigger; launching without either means paying full CAC in a market where competitors run 40-90% off codes continuously. Resets and evals without promo support also can't be discounted for retention saves.


**Industry benchmark:** Apex 15% recurring affiliate + near-continuous 80-90% coupons; MFFU 12% on evals+resets; FTMO up to 39% tiered; Tradeify ~40% codes; FunderPro up to $1,200/referral. Coupon+affiliate is universal commercial machinery.


**Verification evidence:** grep -riE 'promo|coupon|referral|affiliate|ref_code' over backend: only SPLIT_DISCOUNT at backend/services/pricing.py:65 (a hardcoded $10 constant), exactly as the claim states. Same grep over frontend/src: zero hits. No promo_codes table in backend/models/, no code field in NewCombinePage checkout, no ?ref= attribution anywhere.


#### Notification preferences, browser push, sound, and history  `[P1 · effort M · verified missing]`

Notifications are in-app toasts + a 15s-poll alerts bell only while the tab is open (map: no Notification API, no Audio, no prefs, no history). Add: (1) a Notifications tab in SettingsPage with per-category toggles (fills, breach warnings, alert triggers, payout/billing status) persisted server-side; (2) Web Push via a service worker + VAPID for breach/fill/payout events so a 0DTE trader away from the screen still gets the MLL-cushion warning; (3) optional fill/alert sounds (Web Audio, respecting a mute pref); (4) a notification-center drawer backed by a notifications table so missed events are reviewable.


**Why it matters:** 0DTE positions can breach in minutes; today a trader who switches tabs gets no warning before liquidation and no record afterward — the pre-liquidation warning system (usePreLiquidationWarnings) only works while staring at the app. This is direct churn: traders blame the firm for 'silent' liquidations.


**Industry benchmark:** Benchmark firms lean on email/Discord pings for breach and payout events; TopstepX surfaces personal-DLL warnings in-platform with sounds. An in-product push channel would actually exceed the (weak) industry norm here.


**Verification evidence:** grep -riE 'new Notification|serviceWorker|vapid|web.?push|new Audio|AudioContext' over frontend/src: zero hits. frontend/src/pages/SettingsPage.tsx tab set is account|billing|risk|copy|trading|appearance (line 40) — no notifications tab. No notifications model in backend/models/ (grep 'notification' over backend/models + routers: empty). Alerts are the 15s poll exactly as claimed: frontend/src/hooks/useAlerts.ts:105 window.setInterval(tick, 15_000), tab-open only.


### P2 — competitive


#### Free trial / practice combine before purchase  `[P2 · effort M · verified missing]`

There is no way to try the terminal before paying — onboarding is a modal tour, not a sandbox. Add a free practice tier: one non-funded practice account per user (e.g. 25K sim, standard rules displayed but pass grants nothing except a discount code), auto-provisioned at signup, reusing the existing paper-fill engine, combine rules engine, and dashboard rails. Gate it: no payout path, watermarked 'Practice', upsell CTA on the dashboard card comparing practice stats to combine objectives.


**Why it matters:** The purchase is the entire funnel and the product's best asset is its terminal — hiding it behind $49-149 forfeits the highest-converting demo in the category. Practice accounts also produce the analytics/journal data that hooks traders before they've paid.


**Industry benchmark:** FTMO's 14-day Free Trial (halved targets, full tooling) is a signature converter; FundedNext runs free monthly competitions ($100k demo, 150 winners/month) as trial-equivalent; Topstep offers free trial periods on TopstepX.


**Verification evidence:** backend/services/account_tiers.py:20-22 hardcodes TierKey = Literal['50K','100K','150K'] with docstring 'Three tiers, fixed parameters. No custom tiers' — no practice/trial tier. grep -riE 'practice|trial|sandbox' over backend (non-test) matched only unrelated comments (config.py allowlist notes, journal demo seed); over frontend/src: zero hits. Onboarding is the modal tour (stores/onboarding.ts), as claimed.


#### Shareable pass/payout certificates and public trust stats  `[P2 · effort M · verified missing]`

Nothing celebratory or shareable exists beyond a plain funded banner (DashboardPage ActivationBanner). Build: (1) server-generated certificate images (combine passed, funded, payout paid: amount, date, tier) with a public verification URL (/verify/:certId) rendering an OG-tagged page; (2) share buttons (X/Discord/download) at the funded moment and on payout completion; (3) a public aggregate trust widget on the landing page — total simulated payouts paid, funded-trader count — fed by real backend numbers.


**Why it matters:** Prop-firm growth is social proof: every funded certificate posted to Twitter/Discord is free acquisition, and public payout totals are the trust signal skeptical buyers check first. The platform currently produces zero shareable artifacts from its happiest moments.


**Industry benchmark:** FTMO and FundedNext issue shareable challenge-pass and payout certificates as an explicit social-proof loop; FundedNext advertises $284M+ paid and FunderPro $21M+ on their landing pages; Trustpilot/payout-proof culture is sector-wide.


**Verification evidence:** grep -riE 'certificate|/verify|share|celebrat' over frontend/src + backend matched only unrelated terms (profit 'share', per-share greeks). No /verify/:certId route in App.tsx, no image-generation code, no share buttons. ActivationBanner exists only in frontend/src/pages/DashboardPage.tsx as claimed. LandingPage numbers ('100K · funded', 'up to 80%') are static marketing copy, not backend-fed aggregate stats.


#### Server-persisted preferences + user profile (display name, timezone)  `[P2 · effort M · verified partial]`

All personalization (trading defaults, chart prefs, appearance, coachmark/onboarding state) lives in zustand persist/localStorage (stores/userSettings.ts, chartPrefs.ts) — a new device or cleared storage resets everything, and per-user defaults can't be inspected by support. Add a user_preferences JSON column (or table) synced through a GET/PUT /api/me/preferences endpoint with localStorage as offline cache; add profile basics: display name (needed later for leaderboards/certificates), timezone (all session-close and daily-boundary displays currently assume one zone), and account-deletion request.


**Why it matters:** Traders who configure risk-display, hotkeys, and chart appearance lose it all on a second device — a recurring complaint category — and timezone-less daily boundaries confuse traders about when their DLL resets and when the 3:50 flatten hits. Deletion requests are also unanswerable today.


**Industry benchmark:** FTMO/Topstep dashboards are fully server-side accounts (settings roam by definition); FTMO's dashboard exposes timezone-aware calendars; account deletion is table-stakes under GDPR/CCPA for any firm taking EU/CA signups.


**Verification evidence:** Display name EXISTS and is wired: backend/models/user.py:62 display_name column, accepted at signup (backend/routers/auth.py:46,91, frontend/src/pages/SignUpPage.tsx:29) and shown in SettingsPage.tsx:212 — though not editable after signup. Some per-user settings ARE server-persisted (dll_overrides_json, dll_disabled_json, profit_target_json on the User model, enforced server-side). But the claim's core is confirmed: no timezone field on User, no GET/PUT /api/me/preferences endpoint (grep 'preferences' over backend/routers: empty), no account-deletion endpoint (grep empty), and trading defaults/chart appearance/coachmarks live only in zustand persist/localStorage (frontend/src/stores/userSettings.ts, chartPrefs.ts, coachmarks.ts — no fetch/API calls in userSettings.ts).


#### In-app announcements / changelog + status surface  `[P2 · effort S · verified missing]`

No mechanism exists to tell logged-in traders anything (no banner system, no changelog page, no status indicator). Add: (1) an announcements table + admin composer, rendered as a dismissible banner in RailShell and an archive page — used for rule changes, fee changes, holiday sessions; (2) a lightweight status surface: the app already detects data-provider degradation (news 503 honest-state, chart rate-limit guard) — aggregate those health signals into a /status page and a header dot so traders can distinguish 'my account broke' from 'data feed degraded'.


**Why it matters:** Prop firms change rules constantly (splits, caps, consistency) and every unannounced change is a trust crisis and a support flood; a trading product with a live data dependency also needs a place to point users during an Alpaca outage instead of eating 'platform is broken' tickets.


**Industry benchmark:** Apex 4.0 and Topstep's Jan-2026 split change were rolled out via dashboard announcements + email; sector rule-change comms are constant. Status pages are standard for anything with market-data dependencies (brokers, Tradovate, TradingView all run them).


**Verification evidence:** grep -riE 'announcement|changelog|status.?page|maintenance' over backend + frontend/src: zero product hits (banner matches were TradeTicket's PassedBanner/LockBanner and NewCombinePage InfoBanner — per-account state, not operator announcements). No announcements model/table. The raw health signals the claim references do exist (MarketDataDegraded handler backend/main.py:349-354, /health probe main.py:396) but are not aggregated into any /status page or header indicator.


#### Watchlist UI (finish the existing stub)  `[P2 · effort S · verified partial]`

backend/routers/watchlist.py is a complete CRUD router and frontend/src/hooks/useWatchlist.ts exists, but no panel component consumes it (verified: only hooks reference it). Build the missing surface: a watchlist panel in the terminal (rail or bottom strip) listing saved symbols with live price/change (reusing the snapshot batching convention), add/remove from the symbol search, and click-to-load into the chart/chain.


**Why it matters:** It is already paid-for backend work delivering zero user value; multi-symbol 0DTE traders (SPY vs QQQ vs NVDA earnings days) currently have to retype tickers, and every real trading terminal ships a watchlist as a baseline expectation.


**Industry benchmark:** TopstepX, Tradovate, and every retail platform (thinkorswim, IBKR, Webull) treat watchlists as a day-one terminal primitive; TopstepX ships symbol blocks/watch panels in its default layout.


**Verification evidence:** The claim's premise is inaccurate in both directions. backend/routers/watchlist.py is NOT a CRUD router — it is a single read-only GET /api/watchlist returning a GLOBAL curated signal feed (categories hot_now/earnings/unusual_options/sentiment_up/down; model backend/models/watchlist_item.py has no user_id), and it IS consumed: frontend/src/hooks/useWatchlist.ts → useLiveFeed.ts → components/positions/LiveFeed.tsx, rendered via BottomNewsFeedTabs.tsx in the terminal. Separately, per-user symbol saving exists as 'stars': backend/models/user_star.py + /api/user/stars endpoints (frontend/src/lib/api.ts:386-394) with a STARRED section + toggle + click-to-load in components/positions/SymbolSearchModal.tsx. What is genuinely missing is the claimed panel itself: a persistent user-watchlist panel with live price/change per saved symbol (stars show symbol+name only, inside the search modal), and frontend/src/components/layout/LeftRail.tsx:22-24 confirms 'WATCH dropped from the rail, and the /watchlist route... until the watchlist concept comes back.'


### P3 — polish


#### Market replay / historical practice mode  `[P3 · effort L · verified missing]`

Add a replay mode to the terminal: pick a past session (e.g. FOMC day, CPI day), stream historical bars + reconstructed option chains at 1x-10x speed against the existing paper-fill engine, in a clearly non-scoring sandbox account. The platform already has historical bar access via Alpaca and a full sim fill engine (spread-crossing model), so the core new work is a replay clock/scheduler and chain snapshot reconstruction (approximate via BS repricing off underlying bars + stored IV where chain history isn't available).


**Why it matters:** 0DTE skill is reps on volatile sessions, and real reps cost combine fees; replay converts the platform from evaluation-only into a practice destination traders return to daily — retention between combine attempts, which is when churn happens.


**Industry benchmark:** FTMO ships an Equity Simulator and Statistical App as trader-development tooling; NinjaTrader/Tradovate market replay is a heavily-used feature among futures prop traders; no options-funding competitor (Options Funding, Black Eagle) has replay — this is a genuine differentiator.


**Verification evidence:** grep -riE 'replay|playback' over backend + frontend/src matched only hotkey-intent stale-replay guards (stores/hotkeyActions.ts, TradeTicket.tsx:160) and 'Replay the walkthrough' (HelpOverlay.tsx:134, CommandPalette.tsx:73). The only scrubber is the theta what-if scrubber in components/positions/BottomStrip.tsx (ScrubberCol/ScrubberTrack — DTE what-if on the live position, not historical bar playback). No replay clock, no session picker, no chain reconstruction.


#### PWA manifest + installability  `[P3 · effort S · verified missing]`

No manifest.json, no service worker, no icons beyond favicon.svg (verified). Add a web app manifest (name, theme colors, maskable icons), a minimal service worker (app-shell caching only — never cache market data), and install prompts. Note the service worker is also the prerequisite for the Web Push gap above, so build them together.


**Why it matters:** The mobile experience already works (MobileBottomNav, responsive terminal) but lives behind a browser URL bar; installability gives a home-screen icon and full-screen terminal, and unlocks push — cheap retention surface for a product traders should open every market day.


**Industry benchmark:** FTMO and FundedNext ship native mobile apps; Topstep is mobile-browser-only (the norm this platform already matches) — a PWA slots between the two at a fraction of native cost.


**Verification evidence:** ls frontend/public/ = favicon.svg only. find for manifest* outside node_modules: nothing. grep -riE 'manifest|service.?worker|workbox|vite-plugin-pwa' over frontend/index.html, vite.config.ts, package.json: zero hits. grep 'serviceWorker' over frontend/src: zero hits.


#### Blog / content-marketing surface + email capture  `[P3 · effort M · verified missing]`

No blog, no email-capture/waitlist form anywhere on the landing page. Add a lightweight content route (/learn or /blog — static markdown rendered by the existing frontend, or a docs subdomain) seeded with the rule explainers from the help-center gap plus 0DTE strategy content, and a footer/hero email-capture form writing to a subscribers table (feeding the future lifecycle-email system).


**Why it matters:** Organic search for '0DTE prop firm' and 'options funded account' is nearly uncontested (the niche has ~2 small competitors), so content compounds unusually well here; without email capture, every landing visitor who doesn't buy immediately is lost forever.


**Industry benchmark:** The5%ers and FundedNext run heavy education-blog funnels; comparison/review content (proptradingvibes, tradetanto) dominates prop-firm SERPs — firms feed it with their own rule/strategy content; FTMO Academy is a core acquisition asset.


**Verification evidence:** No /blog or /learn route in frontend/src/App.tsx (full route table verified: /, /signin, /signup, /dashboard, /accounts, /payouts, /positions, /combines/new, /journal, /analytics, /settings, *). grep -riE 'blog|/learn|subscribe|waitlist|newsletter|email.?capture' over frontend/src + backend: only unrelated chart subscribeClick / store subscribe hits. No subscribers table in backend/models/, no capture form in LandingPage.tsx.


## Admin, support & operations infrastructure


### P0 — cannot operate as a real business without it


#### Admin role, admin API, and back-office panel  `[P0 · effort L · verified missing]`

Add a privilege tier (role/is_admin column on backend/models/user.py, enforced by an admin dependency alongside services/auth.py get_current_user), an admin router, and an /admin frontend area. Minimum console functions: user search/list; per-user detail (combines, trades, payments, combine_events timeline); suspend/ban/unban; manual combine adjustment (grant, reset, extend, un-fail with reason); refund/comp a payment; read-only impersonation view of a trader's dashboard for support triage. There are currently 16 routers and every one is scoped to the cookie-authenticated user — the operator's only tool is sqlite3 against backend/data/dashboard.db.


**Why it matters:** Every human-in-the-loop business function (dispute resolution, wrongly-failed-account fixes, refunds, abuse bans) is impossible today except by hand-editing the database, which is error-prone against Money-typed append-only ledgers. This is the single biggest blocker to operating with more than zero customers.


**Industry benchmark:** A vertical 'prop-firm OS' market exists precisely for this: FPFX Tech (powers PropAccount), YourPropFirm, Propriotec, Trade Tech Solutions all ship CRM/admin back offices with challenge management, manual adjustments, and ban workflows as the standard stack layer.


**Verification evidence:** git grep -il 'admin' -- backend frontend/src returns ZERO files. backend/models/user.py has no role/is_admin column (full read: only email, password_hash, display_name, active_combine_id, copy/DLL/profit-target fields). backend/routers/ contains 17 files (16 routers + __init__.py), none admin-scoped; 9 router files depend on services/auth.get_current_user (52 call sites). No /admin route in frontend/src/App.tsx (routes: /, /signin, /signup, /dashboard, /accounts, /payouts, /positions, /combines/new, /journal, /analytics, /settings). Operator tooling is only backend/scripts/{backfill_earnings.py, wipe_trades.py}.


#### Real payout review desk (approve/reject, reviewer identity, request linkage)  `[P0 · effort M · verified partial]`

Replace the auto-approve timer in backend/jobs/settle_combines.py approve_pending_payouts() (rubber-stamps any payout_requested event older than PAYOUT_REVIEW_WINDOW_H=1.0h) with a genuine review queue: a payout_requests table with schema-linked decision records (current approval matching is positional per combine), an admin queue UI listing pending requests with account context (equity curve, recent trades, consistency stats, flags), approve/reject/hold actions with reviewer id + notes, a reject path that returns funds to the combine balance and notifies the trader, and configurable auto-approve only below a dollar threshold.


**Why it matters:** Payouts are the firm's primary money-out risk. An unconditional 1-hour auto-approve means any exploited fill, rule loophole, or fraud pays out before a human ever sees it. There is also no reject path at all, so even a detected problem cannot be acted on.


**Industry benchmark:** Human review + audit trail before payout/ban is the universal enforcement pattern; payout denials at real firms cluster into ~12 documented TOS categories (news-window trades, EA misuse, risk breaches). Topstep/Apex/MFFU all run manual first-payout review with 1-3 day turnaround.


**Verification evidence:** A simulated review pipeline EXISTS: backend/jobs/settle_combines.py approve_pending_payouts() auto-approves 'payout_requested' events older than PAYOUT_REVIEW_WINDOW_H=1.0 (lines 32-93); backend/routers/combines.py request_payout debits at request time and records the event (lines 671-810); tested in backend/tests/test_payout_review.py. But every claimed review capability is absent: no payout_requests table (models/ has no such model; approval matching is positional per combine via count comparison of payout_requested vs payout_approved events, settle_combines.py:61-92), git grep for 'reviewer|payout_rejected|payout_hold' finds no product code (only a test name for a not-funded 403), no admin queue UI (zero 'admin' hits in frontend/src; PayoutsPage.tsx is trader-facing), no dollar-threshold auto-approve config.


#### KYC / identity verification and sanctions screening at first payout  `[P0 · effort L · verified missing]`

Integrate an identity-verification provider (Sumsub, Veriff, or iDenfy: document + liveness), gate the first payout request on verified status, store verification state on the user, and add OFAC/sanctions + geo screening (block sanctioned jurisdictions at signup or at payout). Wire the verification-pending state into the payout desk queue. Nothing KYC-shaped exists anywhere in the codebase.


**Why it matters:** The moment real money moves, payment processors and banking partners impose BSA/AML obligations regardless of the 'profit share on simulated accounts' framing; the 2025 GENIUS Act extended KYC obligations to stablecoin payout chains too. Paying an unverified or sanctioned person is a business-ending compliance event.


**Industry benchmark:** Universal industry pattern: no KYC to buy a challenge, mandatory ID verification before first payout (FTMO gates 'FTMO Trader' status behind it; Topstep/Apex/MFFU verify at first payout via Sumsub-style providers, 24-48h turnaround).


**Verification evidence:** git grep -il 'kyc|sanction|ofac|sumsub|veriff|idenfy|identity.?verif|liveness' matched only backend/main.py:477, services/realtime_feed.py:190, tests/test_health.py:1 — all 'liveness' as in health-probe liveness, false positives. No verification state on models/user.py, no geo/jurisdiction checks in routers/auth.py signup or routers/combines.py request_payout.


#### Payout rails and tax documentation (W-9/1099, W-8BEN)  `[P0 · effort L · verified missing]`

Integrate at least one real payout rail — Rise or Deel (both generate contractor agreements and jurisdiction-appropriate tax docs automatically), plus ACH for US traders — behind the existing payout-approval event flow, with payout-method collection UI, minimums, processing-status tracking, and failure handling. Collect W-9 (US) / W-8BEN (non-US) at funded onboarding and support 1099-NEC issuance at $600+/yr. Today approval 'never moves money' per the settle_combines docstring, and there is no tax-document machinery at all.


**Why it matters:** A prop firm's entire promise is the payout; with no rails the product cannot fulfill its core transaction. Tax-doc collection is a legal obligation for US contractor payments and retrofitting it after paying traders is painful.


**Industry benchmark:** Dominant stack: Rise (crypto-native payroll, 190+ countries, the prop-firm favorite, $1.5B+ volume), Deel, Wise, ACH/wire; firms run 2-3 rails in parallel. US traders are independent contractors: W-9 at onboarding, 1099-NEC at $600+.


**Verification evidence:** git grep -i 'w-9|w9|1099|w-8|w8ben|tax' matches only false positives ('syntax', 'w-9' Tailwind width class, 'fmtAxis'). git grep -i 'ach\b|deel|rise|wise|paypal|payout_method' finds no rail integration. backend/jobs/settle_combines.py:17-18 docstring confirms 'approval never moves money'. No payout-method collection UI in frontend/src/pages/PayoutsPage.tsx, no tax-doc model in backend/models/.


#### Legal pages, signup consent, and funded-trader agreement  `[P0 · effort M · verified missing]`

Author and serve Terms of Service, Privacy Policy, simulated-trading risk disclosure, refund/reset policy, and a trading-rules document; add a consent checkbox to frontend/src/pages/SignUpPage.tsx (currently none) with versioned acceptance records (user_id, doc version, timestamp, IP); add an e-signed funded-trader/independent-contractor agreement step at the funded transition. Static pages + an acceptances table is enough to start.


**Why it matters:** Taking evaluation fees with no ToS, no refund policy, and no risk disclosure is a launch blocker: no enforceable rules to deny an abusive payout against, chargebacks are indefensible, and the simulated-account model (post-My-Forex-Funds scrutiny) demands explicit disclosure. Acceptance tracking is what makes the docs usable in a dispute.


**Industry benchmark:** FTMO signs an FTMO Account Agreement post-verification making the trader an independent contractor on simulated capital; all four CFD benchmark firms use e-sign agreements at funding; payout-denial enforcement at every firm rests on TOS the trader accepted.


**Verification evidence:** grep -ril 'privacy' across frontend/public, frontend/src, backend returns nothing. git grep -i 'terms of service|privacy policy|consent|disclosure|agreement' matches only two false positives (alpaca_client.py:1077 comment, BottomStrip.tsx:300 OI-proxy disclosure). frontend/src/pages/SignUpPage.tsx has zero checkbox/consent/terms/agree hits. No acceptances table in backend/models/, no legal routes in frontend/src/App.tsx.


#### Transactional email service and lifecycle notifications  `[P0 · effort M · verified missing]`

Extends the known deferred item with the operational spec: a provider-abstracted email service (Postmark/Resend/SES) plus templated, event-driven sends wired to existing lifecycle events — signup verification, forgot-password reset (routers/auth.py currently has no reset path, so a forgotten password is permanent lockout), combine funded/failed, payout requested/approved/rejected/paid, billing receipt, renewal reminder, and inactivity warnings. Add an outbound-email log table for support forensics.


**Why it matters:** Forgot-password lockout alone makes real customer accounts untenable, and a firm that charges monthly rebills without receipts or renewal notices generates chargebacks. Every downstream gap (payout desk, KYC, support) needs a notification channel to close its loop.


**Industry benchmark:** Notifications across Topstep/Apex/MFFU/FTMO are primarily email (+ Discord); FTMO/FundedNext send challenge-pass certificates and payout confirmations by email as a core social-proof loop.


**Verification evidence:** git grep -i 'smtp|postmark|sendgrid|mailgun|send_mail|resend' finds no email code in backend/ (broad 'ses' hits were substring false positives in calculations/). backend/routers/auth.py exposes only signup, signin, change-password, signout, me (lines 74-159) — no forgot-password/reset or verification path, confirming permanent lockout on forgotten password. No outbound-email log table in backend/models/.


#### Backups and tested disaster recovery  `[P0 · effort S · verified missing]`

Add a scheduled backup job for the single SQLite file (sqlite3 .backup or Litestream WAL streaming to S3/B2) plus backend/data/uploads/ journal screenshots, with retention policy, offsite copy, and a documented, actually-rehearsed restore runbook. Also neutralize the booby trap in backend/database.py _additive_migrate_trades, which silently deletes all trades on a restored backup missing the 'tier' column, guarded only by a log line — make it refuse to boot instead.


**Why it matters:** The entire business — user accounts, the append-only combine_event money ledger, payment history — is one unreplicated file on one disk. A single disk failure is total, unrecoverable loss of every customer's financial record, with the current migration code able to destroy a restore that does succeed.


**Industry benchmark:** Not a differentiator anywhere because every operating firm has it; prop-firm back-office vendors (FPFX, YourPropFirm) run managed Postgres with PITR as baseline. Litestream is the standard answer for production SQLite.


**Verification evidence:** backend/jobs/ contains only categories, collect_options_chain, monitor_orders, prewarm_hot_tickers, refresh_watchlist, renew_combines, seed_trades, settle_combines — no backup job; git grep -i 'backup|litestream' hits only comments. The destructive branch is confirmed live: backend/database.py _additive_migrate_trades lines 200-233 executes DELETE FROM trades whenever the 'tier' column is absent, guarded only by logging.warning('...DELETING all %d existing trade row(s)...') — it does not refuse to boot. No restore runbook file anywhere in the repo.


#### Deployment artifacts and a deploy pipeline  `[P0 · effort S · verified missing]`

The production-hardening code already exists (APP_ENV=production cookie/HSTS/CORS hardening, Postgres pool settings in config.py/database.py) but nothing deploys it: add a Dockerfile (+ compose or fly.toml/render.yaml), reverse-proxy config, process supervision, environment/secret documentation, and a CD stage on the existing 4-job CI (.github/workflows/ci.yml has no deploy stage). Include the APScheduler single-process constraint in the deployment doc so nobody scales to 2 replicas and double-fires billing.


**Why it matters:** There is literally no way to put this in front of a customer today except uvicorn --reload on a laptop; the README documents local dev only. All the production-readiness code is dead weight until an artifact exercises it.


**Industry benchmark:** Table stakes; the MetaQuotes fallout (80-100 firms dead 2024-2025 over platform dependency) shows ops fragility kills prop firms — owning a reproducible deploy is the minimum hedge.


**Verification evidence:** No Dockerfile, docker-compose, fly.toml, render.yaml, Procfile, or nginx/caddy config at repo root or backend/ (ls checks). .github/workflows/ci.yml (199 lines) defines exactly 4 jobs — backend, backend-postgres, backend-quality, frontend — with no deploy stage (grep 'deploy|docker' in ci.yml: zero hits). The hardening the claim references does exist: backend/config.py:136-154 app_env='development' with prod-hardening comments, and 7 scheduler.add_job calls in backend/main.py:185-259 confirm the single-process APScheduler constraint.


#### Support channel and ticket queue  `[P0 · effort M · verified missing]`

Minimum viable: a support email address surfaced in-app and on legal pages, plus an in-app 'Contact support' form that creates a row in a tickets table (user, category — rule dispute / billing / payout / bug —, account context auto-attached) feeding an admin queue with status and canned responses. Fuller build: Intercom/Zendesk embed + Discord community. Today frontend/src/components/help/ has only a hotkey glossary and onboarding tour; grep finds no contact route, support email, or feedback mechanism anywhere.


**Why it matters:** A trader whose combine was wrongly failed or whose payout is stuck has no channel to reach the operator at all — that is a refund/chargeback/reputation machine. Rule disputes are the dominant support category at prop firms, and every one currently ends in silent churn.


**Industry benchmark:** Standard prop stack is Intercom/Zendesk + Discord community (FPFX/PropAccount reference stack); transparent dashboards + working support queues measurably cut ticket load. All benchmark firms run help centers and Discord servers.


**Verification evidence:** git grep -i 'support|ticket|contact|feedback|intercom|zendesk|discord' matches only incidental uses ('supported', order-ticket trading UI in TradeTicket.tsx/QuickOrder.tsx, 'contact' absent). frontend/src/components/help/ contains only HelpOverlay.tsx and OnboardingTour.tsx as claimed. No tickets table in backend/models/, no support router in backend/routers/.


### P1 — industry table stakes; traders churn without it


#### Risk desk: cross-account abuse detection feeding payout review  `[P1 · effort L · verified missing]`

Build the analytical layer a payout reviewer needs: cross-user trade-correlation detection (same contracts, entry/exit timestamp deltas, size ratios — copy-trading/group-passing signature), shared IP/device fingerprint clustering at signup and order placement, stale-quote/latency-arbitrage detection (flag sub-second round-trip fills with anomalous win rates — acutely relevant here because fills are simulated against polled Alpaca quotes, so quote-lag exploitation is the house's loss by construction), and 'gambling' flags (no-stop all-in sizing, >3x day-over-day size variance). Surface flags on the payout-desk account view; log dispositions.


**Why it matters:** In the challenge-fee business model, coordinated passing and sim-fill exploitation are the main ways the firm loses money; with a 1-hour auto-approve and zero detection, one Discord group with a quote-lag script can drain payouts systematically.


**Industry benchmark:** Real firms run exactly this: timestamp-delta clustering and ML correlation (~97% correlation flags survive cross-broker review), 30-accounts-one-AWS-IP instant flags, <800ms/>78%-win-rate latency-arb signatures, and TOS rights to void stale-quote fills.


**Verification evidence:** git grep -i 'correlation|fingerprint|device_id|abuse|arbitrage|collusion' in backend/ hits only request-id correlation middleware (main.py:46,418-425) and rate-limit 'abuse' comments (config.py:107,206, file_storage.py:30). services/copy_trade.py implements the copy-trading FEATURE, not detection of it across users. No IP/device storage at signup (models/user.py, models/auth_session.py store neither), no flag surfacing anywhere.


#### Operator business-metrics dashboard  `[P1 · effort M · verified missing]`

An admin-only dashboard (API + page) over data that already exists in payments/combines/combine_events: revenue and MRR by tier, active/passed/failed/funded combine counts and pass rates per tier, reset-purchase attach rate, outstanding payout liability (requested + approved-unpaid), churn/renewal rate, and signup funnel counts. Grep for revenue/MRR/churn currently returns zero hits — the operator cannot see sales at all.


**Why it matters:** Prop-firm economics are actuarial: the business is solvent only if evaluation revenue exceeds payout liability, and pass-rate drift (e.g. from a fill-model change) is a solvency event. Flying blind on these numbers means discovering mispricing only when payouts spike.


**Industry benchmark:** Prop-firm OS vendors (FPFX Tech, YourPropFirm) ship challenge-funnel and liability analytics as core back-office screens; firms publicly tune targets/splits (Apex 4.0, Topstep payout-cap cuts) based on exactly these metrics.


**Verification evidence:** git grep -i 'revenue|mrr|churn' in backend and frontend/src returns zero product hits (only 'churn' as in cache/thread churn comments: services/auth.py:168, timeouts.py:53, AnnotatedChart.tsx:267). backend/routers/analytics.py is trader-scoped performance analytics; no operator/admin metrics endpoint or page exists (zero 'admin' hits repo-wide).


#### Operator alerting and scheduled-job observability  `[P1 · effort M · verified missing]`

Three additions to the existing logging/Sentry/health stack: (1) a job_runs table recording start/end/status/error for the 7 APScheduler jobs with an admin status page, (2) active alerting (email/Slack webhook/PagerDuty) when money-critical jobs — settle_combines, renew_combines, monitor_orders — fail or stop running (dead-man switch), since today failures only reach logs nobody tails, and (3) external uptime monitoring against GET /health plus a minimal public status page.


**Why it matters:** If settle_combines silently stops, payouts freeze and funded terminations stop enforcing; if renew_combines fails, billing stops — and nothing pages anyone. On a single-process in-memory scheduler, jobs dying silently is a matter of when.


**Industry benchmark:** FundedNext contractually pays traders +$1,000 if a payout misses its 24-hour guarantee — that SLA is only possible with ops alerting; FTMO advertises ~99.8% on-time payouts as a trust metric.


**Verification evidence:** No job_runs model (backend/models/ listing) and git grep 'job_run|slack|pagerduty|dead.?man|status.?page' finds nothing. The existing stack the claim builds on is confirmed: Sentry init at backend/main.py:110-117 (config.py:89-96, no-op when DSN blank) and GET /health at main.py:475-491. Job failures land only in logs (e.g. settle_combines.py:136 log.exception on payout-pass failure). No external uptime monitoring config in repo.


#### Admin-action audit log and auth security trail  `[P1 · effort S · verified missing]`

Two append-only tables built alongside the admin panel from day one: (1) admin_actions — actor, action, target user/combine, before/after values, reason, timestamp — written by every admin endpoint; (2) auth_events — login success/failure, IP, user-agent, password change, session revocations (auth_sessions currently stores only token hashes with no history). Add a user-facing active-sessions list with remote revoke in Settings.


**Why it matters:** The moment manual balance adjustments and payout approvals exist, the firm needs to answer 'who changed this account and why' — for internal fraud, disputed bans, and chargeback evidence. Retrofitting an audit trail after an incident is too late by definition.


**Industry benchmark:** Human review + audit trail before ban/denial is the documented enforcement pattern industry-wide; prop-firm CRM back offices log all operator actions for exactly this dispute-evidence purpose.


**Verification evidence:** No admin_actions or auth_events tables — git grep 'admin_action|auth_event|audit' hits only docstring uses of the word 'audit' (combine_event.py:1 calls combine_events an audit trail of combine milestones, not auth/admin actions). backend/models/auth_session.py stores exactly token_hash, user_id, created_at, expires_at — no IP, user-agent, or history; signout deletes rows. frontend/src/pages/SettingsPage.tsx has no active-sessions list (only text at lines 235,269 noting password change signs out other sessions).


#### Account lifecycle compliance: deletion, data export, email change  `[P1 · effort M · verified missing]`

Add (1) self-serve account deletion with a grace period, anonymizing user rows while preserving the financial ledger (combine_events/payments) for the retention window, (2) a user-data export endpoint (JSON bundle of profile, trades, journal entries + uploaded screenshots, events) beyond the existing closed-trades CSV in frontend/src/lib/exportCsv.ts, (3) email change with reverification (depends on the email service), and (4) a documented data-retention policy the privacy policy can reference.


**Why it matters:** The privacy policy shipped in the legal gap will promise GDPR/CCPA rights the platform cannot currently honor — deletion and export requests would have to be hand-worked in sqlite3. EU/UK traders are a large share of prop-firm customers.


**Industry benchmark:** FTMO/FundedNext/The5%ers all operate GDPR data-request processes in their help centers; KYC-provider integrations (Sumsub etc.) contractually require defined retention/deletion handling of identity documents.


**Verification evidence:** git grep -i 'delete.?account|account.?delet|data.?export|anonymi|email.?change|change.?email|retention' in backend/routers and frontend/src/pages returns zero hits. backend/routers/auth.py endpoints are only signup/signin/change-password/signout/me. The only export is the closed-trades CSV at frontend/src/lib/exportCsv.ts (97 lines), as the claim states. No retention-policy doc in repo.


### P2 — competitive


#### Runtime kill switches and feature flags  `[P2 · effort S · verified missing]`

A small DB-backed flag store (flags table + cached reads + admin toggle UI) replacing restart-required env vars in backend/config.py for operational switches: halt-new-signups, halt-purchases, halt-payout-requests, global trading-halt (market/data-feed incident), and per-feature rollout flags (e.g. realtime_feed_enabled, currently env-only). Check flags at router level for the halt switches.


**Why it matters:** When the Alpaca feed goes bad or a fill-model bug is discovered, the operator's only current remedies are editing env vars and restarting, or taking the whole app down — while simulated fills against bad quotes keep creating (or destroying) funded accounts.


**Industry benchmark:** Real firms halt entries and disable payouts during platform incidents (standard practice during the 2024-2025 MetaQuotes migrations); Topstep/Apex routinely toggle product availability without redeploys.


**Verification evidence:** No flags table in backend/models/ and git grep -i 'feature.?flag|kill.?switch|halt' finds only market-halt/stale-quote comments (zerodte.py:175-188, alpaca_client.py:341) and DLL 'disable flags' (a per-user trading setting, not ops switches). realtime_feed_enabled is confirmed env-only at backend/config.py:58 inside pydantic BaseSettings — restart-required. No halt-signups/halt-purchases/halt-payouts checks in any router.


#### Versioned schema migrations (Alembic)  `[P2 · effort M · verified missing]`

Introduce Alembic over the existing hand-rolled additive migrations in backend/database.py: version-stamp the current schema as a baseline, move future changes into versioned revisions with downgrade paths, and keep the CI Postgres leg proving the ladder. Specifically eliminate the destructive missing-'tier'-column branch (it currently DELETEs all trades and merely logs a warning).


**Why it matters:** The hand-rolled system works but has no version tracking and no rollback, which turns every schema mistake in production into a restore-from-backup event — unacceptable once the DB holds real customers' money ledgers.


**Industry benchmark:** Baseline practice for any FastAPI/SQLAlchemy production deployment; prop-firm back-office vendors run versioned migrations on managed Postgres as standard.


**Verification evidence:** No alembic directory or alembic.ini (ls backend); the only mention is backend/database.py:142 comment 'Single-user SQLite — Alembic would be overkill'. Migrations are hand-rolled additive functions in backend/database.py (e.g. _additive_migrate_trades, lines 200-233), including the destructive missing-'tier' branch that DELETEs all trades with only a warning (lines 223-232). CI does have a Postgres leg running the additive migrations (.github/workflows/ci.yml:97 'Run additive migrations on Postgres').


### P3 — polish


#### Multi-replica-safe infrastructure (distributed rate limits, job locking)  `[P3 · effort M · verified missing]`

When the platform outgrows one process: move the three in-memory rate-limit layers (services/rate_limit.py — per-IP global, auth brute-force, per-user financial throttle) to Redis, and give the 7 APScheduler jobs a distributed lock or move them to an external scheduler/worker so a second replica doesn't double-fire settle_combines and the billing cron. Document the single-replica constraint prominently until then.


**Why it matters:** The current design is correct only at exactly one process: the first horizontal scale-out silently double-bills renewals and double-settles payouts, and rate limits stop coordinating — a money-integrity failure mode disguised as an infra upgrade.


**Industry benchmark:** Every multi-tenant prop platform (FPFX/PropAccount-class stacks) runs shared-state rate limiting and queue-backed workers; the benchmark firms all operate multi-instance web tiers.


**Verification evidence:** backend/services/rate_limit.py:1-6 self-describes as 'In-memory per-key rate limiting... for a single-instance dev/prototype deployment; swap for Redis if this ever' and builds the three in-memory layers the claim names (_build_auth_limiter:209, _build_global_limiter per-IP:220-223, _build_financial_limiter per-user:234-237). backend/services/cache.py:1: 'Tiny TTL cache. Replace with Redis once we outgrow a single process.' The 7 APScheduler jobs (backend/main.py:185-259, in-process BackgroundScheduler) have no distributed lock — git grep 'redis|distributed.?lock|advisory.?lock' finds only those two swap-for-Redis comments.
