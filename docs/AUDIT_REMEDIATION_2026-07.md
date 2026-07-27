# Trade-desk audit remediation — July 2026

**What this is:** the fixes shipped in response to the 2026-07-22 full trade-desk
audit (admin/ops, option execution, UI/usability, and half-built work). All work
landed on `main` across **PRs #10–#20**, each behind green CI (backend pytest on
SQLite + Postgres, ruff/mypy/pip-audit, frontend typecheck + build + vitest, and
the Docker build). A follow-up three-agent verification pass re-reviewed the whole
diff and found no bugs or regressions.

Test baseline after remediation: **backend 1126 pass, frontend 220 pass, tsc clean.**

---

## TL;DR — what to know

- **Money/risk paths are now concurrency-safe.** The order-open, funded-account
  activation, and reset paths take a real per-combine write lock, so a
  double-click / retry can no longer bypass the scaling cap or double-charge.
- **A trader can no longer hide a locked-in loss from their own limits** by
  scaling out of a loser and holding a runt near breakeven.
- **Admin decisions (KYC, payout) now write their audit row in the same
  transaction as the decision** — no more window where a crash lands a decision
  with no audit trail.
- **Destructive UI actions now confirm** (mouse close/scale-out, "close all",
  admin payout approve/mark-paid, platform close-only) to match their
  already-guarded keyboard equivalents.
- **The heavyweight unused ML dependencies were removed** (torch/catboost/
  scikit-learn/pyarrow), which also **fixed the long-red Docker CI job** and cut
  the deploy image by ~5GB.
- **Accessibility, responsive layout, and the journal's visual consistency** were
  brought in line with the rest of the app.

---

## Backend — money, risk, and data integrity

| Area | Problem | Fix | PR |
|------|---------|-----|----|
| Order-open concurrency | `_require_tradeable` read the combine's open-contract count / margin / DLL with no lock, so two concurrent opens both passed the scaling-cap & MLL/DLL gate and over-opened past the funded cap. | `zerodte._require_tradeable` now takes a real write lock on the combine row (`_lock_combine_row`, the SQLite-safe `UPDATE settled_hwm=settled_hwm` idiom) after the snapshot and before the read-decide, held until the booking commit. | #10 |
| Paid-action double-submit | A double-click on `activate-account` could charge the $149 fee twice; `reset_combine`'s credit spend was a lost-update (free extra reset or double charge). | Both lock the combine row, `refresh`, and re-check state under the lock; the loser sees the winner's committed state and 409s. | #10 |
| Payout stale-balance | `request_payout` recomputed prior requests under the lock but not the balance/MLL, so a loss booked in the snapshot→lock window could pass a stale MLL-floor check. | Re-snapshots balance/MLL under the lock (re-acquiring the lock after, since a snapshot can commit a settlement). | #10 |
| Personal risk triggers | `_personal_triggers` used `today_realized + urpl`, ignoring `open_realized` (scale-out P&L booked onto still-open rows), so a trader who scaled 9/10 lots out at a loss and held 1 near breakeven never tripped their own daily-loss limit or profit target. | Threads `open_realized` into both checks, matching `_auto_liquidate`'s loss-only DLL convention. | #10 |
| NaN/Inf in the ledger | `quantize_money` didn't reject non-finite Decimals — a degenerate calc could persist a silent `NaN` or throw a bare `InvalidOperation` inside a write. | Rejects non-finite values at the storage boundary. | #10 |
| Admin audit atomicity | `verification.decide_kyc` and `payout_desk.decide` committed internally *before* the router staged its audit row, leaving a window where a crash landed the decision with **no audit trail** — on the two most sensitive admin actions. | Both gained `commit=False`; the admin router stages the audit row and commits once, atomically. Kill-switch (`platform.update`) now also captures a `reason`. | #10 |
| Copy-trade ratio distortion | `mirror_open` clamped each leg of a ratio structure to the follower cap independently, silently turning e.g. a 1-2-1 butterfly into a different position. | Single-leg still clamps (proportional copy); multi-leg with any leg over cap is **skipped**, not distorted. | #10 |
| Admin ticket queue | `/support/admin/tickets` returned every ticket in one unbounded payload with only a status filter. | Paginated (`page`/`page_size`, mirrors `/admin/users`) + case-insensitive search over subject + owner email; response gained `total`/`page`. | #17 |

## Frontend — safety, correctness, usability

| Area | Problem | Fix | PR |
|------|---------|-----|----|
| Mouse vs keyboard parity | "Close all", per-position close/scale-out, admin payout approve/mark-paid, and platform close-only fired instantly on click while their keyboard equivalents were double-press-guarded. | Click paths now arm/confirm (or route through the guarded hotkey bus). | #10 |
| Double-submit | StrategyBuilder, WorkingOrders edit, and the journal entry modal could fire twice on a fast double-click (the `isPending` flag flips a render too late). | `submittingRef` synchronous guard, reset on settle/finally. | #10 |
| Journal P&L integrity | Closing a trade with a blank P&L silently booked `0`, corrupting win-rate / R-multiple stats. | An explicit realized P&L is now required (typing `0` for a true scratch is fine). | #10 |
| Payout country list | A hardcoded 28-country select hard-blocked anyone outside it from completing KYC/tax → from being paid. | Full ISO-3166 list via `Intl.DisplayNames` (`lib/countries.ts`). | #10 |
| QuickOrder stale seed | The popover snapshotted the cell premium at open; a limit/stop **trigger** (what the monitor fills against) defaulted to a stale price if left open across a 10s refetch. (Market fills were already safe — the backend ignores the client price and re-prices server-side.) | Parent feeds a live premium; the trigger re-seeds to live while unedited, respects a typed value, shows a `live X.XX` readout + drift flag. | #16 |
| Stale-quote indicator | The chain quote timestamp was plain text with no cue when the feed stalled. | During market hours a timestamp older than 30s (≈3 missed refetches) flags `⚠ … STALE` in warning color; a 5s tick surfaces silent stalls. | #15 |
| Accessibility | Two journal modals skipped the shared focus-trap; admin table rows were bare `<tr onClick>`; the SL/TP bracket strip claimed `role="slider"` but wasn't keyboard-operable; a disabled payout button's reason lived only in a tooltip. | Modals use the shared `Modal` (Escape/focus-trap/restore); admin rows got `tabIndex`/`role`/keydown/aria; the slider got arrow/Page nudging + `aria-value*`; the payout reason is visible text + `aria-describedby`. | #13 |
| Responsive width | The trade desk split chart | chain-rail side-by-side at `md` (768px), but the rail is a hard 452px, squeezing the chart to ~316px until ~1200px. | Split moved to `xl` (1280px); below that it stacks full-width. Payout rows now wrap instead of forcing horizontal page scroll. | #14 |
| BottomStrip clipping | The fixed-height 280px management columns used `overflow-hidden`, silently clipping tall (multi-leg) content. | The shared column wrapper now scrolls (`overflow-y-auto`) instead of clipping. | #18 |
| Journal visual consistency | Journal controls hardcoded `borderRadius: 0` while the rest of the app uses the `rounded-btn` token. | Controls → `rounded-btn` (4px), chips → `rounded-hair` (2px), segmented controls rounded + clipped; panels/grid/images stay 0 per the token rule. | #19 |

## Dependencies & build

| Change | Detail | PR |
|--------|--------|----|
| Docker CI fixed | The "Docker image (build only)" job had been red on `main`: `torch` pulled ~5GB of Linux CUDA libraries that exhausted the runner disk. Interim fix pinned Linux torch to the CPU wheel index. | #11 |
| Dormant ML deps removed | `torch`, `catboost`, `scikit-learn`, `pyarrow` were declared but **never imported** (no `/api/models` or `/api/signal` routes exist — that claim in the README was stale). Removed entirely. | #12 |
| — Result | `uv.lock` **125 → 82 packages**; deploy image ~5GB smaller; Docker CI green with much less to build. `numpy`/`scipy`/`pandas` stay (the live analytics layer). | — |

---

## Behavior changes to be aware of

- **Journal trade close now requires a realized P&L value.** Existing flows that
  relied on the blank-defaults-to-0 behavior must enter an explicit number
  (including `0` for a scratch).
- **Tablets / small laptops (768–1279px) now see the stacked trade-desk layout**
  (chart over rail) instead of the old cramped side-by-side. Side-by-side
  requires ≥1280px.
- **The platform kill switch now records a reason** and destructive admin/trade
  actions require a confirming second click.
- **The deploy image no longer contains torch/CUDA.** If anyone was relying on
  those being importable in the container, they aren't — they were unused.

## Still open (deferred, low-priority / externally blocked)

Not correctness issues; each needs an external dependency or a dedicated project:

- **Real-time streaming** (`realtime_feed`, flagged off) — needs a paid Alpaca
  tier + an SDK bump for options streaming.
- **Transactional email** — `mail_provider="console"` with no SMTP creds set, so
  password-reset / payout emails only log server-side. Needs SMTP credentials
  (not vendor-blocked).
- **Stripe billing** and **Sentry** — no-op'd pending real keys.
- **Finnhub sentiment** — free tier only; surfaced as "unavailable," not faked.

## Verification

After all fixes landed, a three-agent adversarial re-review of the full
`3191298..HEAD` diff independently confirmed every fix correct with no new bugs
or regressions; the only follow-up was a stale Dockerfile comment (#20). New
regression tests were added for the money finiteness guard, the scale-out risk
gate, copy-trade ratio preservation, quote staleness, the QuickOrder seed, and
ticket pagination/search.
