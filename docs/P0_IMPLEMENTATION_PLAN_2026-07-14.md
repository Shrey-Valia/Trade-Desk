# P0 Implementation Plan — 2026-07-14

Implements the ten deduped P0 launch blockers from `docs/GAP_ANALYSIS_2026-07-13.md`,
within the standing product decisions:

- **Money movement stays SIMULATED.** Stripe checkout wiring, real KYC providers, and
  real payout rails are NOT called. Every external money/identity integration is built
  behind a provider-agnostic adapter with a simulated default, so flipping to a real
  provider later is configuration + one adapter, not a schema change.
- **OPRA/market-data licensing** (gap #7) is a business procurement task — no code here.
- **Card-on-file dunning** (gap #8) is deferred with Stripe wiring; billing periods
  already model the subscription.

## Scope (what ships)

1. **Admin role + operator back office** — `users.role`, `require_admin` dependency,
   `routers/admin.py`, `/admin` frontend console, `admin_actions` append-only audit log.
2. **Human payout adjudication** — `payout_requests` workflow table
   (requested → under_review → approved | denied | held → paid), deny re-credits the
   epoch-scoped balance, reason codes, admin queue; configurable auto-approve fallback.
3. **KYC gate** — `kyc_verifications` state machine (unverified → pending → verified |
   rejected), simulated provider (auto-verifies unless OFAC-blocked country), hard gate
   on first payout request.
4. **Payout methods + tax docs** — `payout_methods` (ach | wire | crypto),
   `tax_profiles` (W-9 / W-8BEN), both gate payout requests; admin 1099-NEC aggregation
   (≥ $600/yr of PAID payouts).
5. **Legal & consent** — versioned ToS / privacy / refund / risk-disclosure acceptance
   (`agreement_acceptances`), consent gates at signup (frontend) + purchase
   (server-side), typed-name e-sign of the funded-trader agreement gating activation;
   static legal pages + landing footer links.
6. **Transactional email + notifications** — provider-agnostic mailer (console default,
   SMTP via env), `email_outbox` drained by a scheduler job, forgot-password /
   reset flow, lifecycle notifier tailing `combine_events` → email + in-app
   `notifications`, notification bell in the header.
7. **Support** — `support_tickets` + contact form + admin queue.
8. **Backups/DR** — nightly SQLite `.backup` job with retention; the
   `_additive_migrate_trades` tier-wipe now REFUSES TO BOOT (env escape hatch) instead
   of silently deleting trades.
9. **Deploy artifacts** — multi-stage Dockerfile (frontend build → backend serves the
   SPA), docker-compose, CI image-build job, `docs/DEPLOYMENT.md` documenting the
   single-process APScheduler constraint.
10. **Risk controls (near-bug + kill switch)** — `zero_dte_universe` actually enforced
    on the open path; `platform_state` KV backing a global trading mode
    (normal | close_only | halted) + per-symbol ban list, admin-settable with no
    market-data dependency; option-quote quality gates at open.
11. **Ops observability** — `job_runs` table wrapping every scheduled job; admin jobs
    health endpoint.

## Conventions (all agents MUST follow)

- Path has a space: always quote `"/Users/shreyvalia/Desktop/Trade Dashboard"`.
- Money columns use `services/money.py` `Money` type; timestamps use
  `database.UTCDateTime` with `default=lambda: datetime.now(timezone.utc)`.
- Cross-table user/combine refs: `ForeignKey` where the existing models use one
  (user_id/combine_id on event-like tables), plain `Integer` where circularity forbids.
- Event/audit tables are append-only; `type`/`status` are plain VARCHAR, no Enum.
- Schema changes to EXISTING tables go through the additive-migration lists in
  `database.py`; NEW tables come free via `create_all` + the model import list in
  `init_db` (already wired in Phase A).
- No FK PRAGMA changes, no Alembic (out of scope).
- Tests: pytest, in-memory SQLite per the existing `backend/tests/conftest.py`
  patterns; every new endpoint/service gets coverage, including authz (403 for
  non-admin) and the money-math edge cases. Run
  `cd "…/backend" && uv run pytest -q` before declaring done.
- Frontend: React Query + zod validation per existing patterns; new API client code
  goes in NEW `frontend/src/lib/<domain>Api.ts` modules — do NOT edit shared
  `lib/api.ts`. Run `npx tsc --noEmit` + `npm run build` (and vitest) before done.
- Admin authz: every `/api/admin/*` endpoint depends on
  `services.auth.require_admin`; every admin MUTATION writes an `AdminAction` row
  (actor, action, target, before/after JSON, reason).

## File ownership (conflict avoidance)

| Workstream | Owns (edits) | Must NOT touch |
|---|---|---|
| A: foundation (inline) | models/*, config.py, database.py, main.py, services/auth.py (require_admin), services/job_runs.py, routers/auth.py (/me role), App.tsx scaffolds, scaffold routers/jobs | — |
| B1 legal+support | services/legal.py, routers/legal.py, routers/support.py, their tests | routers/combines.py, main.py |
| B2 kyc+tax+methods | services/verification.py, routers/verification.py, tests | routers/combines.py, main.py |
| B3 email+recovery | services/mailer.py, services/notify.py, jobs/send_outbox.py, jobs/notify_events.py, routers/auth.py, routers/notifications.py, tests | main.py (jobs pre-registered), combines.py |
| B4 ops-infra | jobs/backup_db.py, database.py (booby trap only), Dockerfile, docker-compose.yml, .dockerignore, .github/workflows/ci.yml, docs/DEPLOYMENT.md, services/job_runs.py (flesh out), tests | main.py, combines.py |
| B5 risk-controls | services/platform_state.py, routers/zerodte.py (_require_tradeable), services/order_monitor.py (halt awareness), tests | main.py, combines.py, admin.py |
| C1 payout-desk | services/payout_desk.py, routers/combines.py (payout + activation gates), services/combine_state.py (denied re-credit math), jobs/settle_combines.py, tests | admin.py |
| C2 admin-api | routers/admin.py, services/admin_audit.py, tests | combines.py, zerodte.py |
| D1 frontend-admin | pages/admin/*, lib/adminApi.ts | pages/PayoutsPage.tsx, App.tsx (routes pre-scaffolded) |
| D2 frontend-trader-legal | pages/legal/*, pages/ForgotPasswordPage.tsx, pages/ResetPasswordPage.tsx, pages/SupportPage.tsx, SignUpPage.tsx, SignInPage.tsx, NewCombinePage.tsx (consent), AccountsPage.tsx (e-sign at activation), LandingPage.tsx (footer links only), lib/legalApi.ts | PayoutsPage.tsx, TradeDeskHeader.tsx |
| D3 frontend-trader-payouts | PayoutsPage.tsx, components/positions/TradeDeskHeader.tsx (bell), components/notifications/*, lib/verificationApi.ts, lib/notificationsApi.ts | App.tsx, admin pages |

## Key contracts

### Payout adjudication (C1)
- `PayoutRequest` row created in the same transaction as today's `payout_requested`
  event (events remain the MONEY ledger; payout_requests is the WORKFLOW state).
- Balance math: available = split-of-profit − (requested − denied). Denial writes a
  `payout_denied` combine_event carrying the amount; `combine_state` payout-debit
  arithmetic subtracts denied amounts back. Property-test the invariant: request→deny→
  request leaves available unchanged; approve/hold do not move money (debit stays at
  request time).
- `approve_pending_payouts` now operates on `payout_requests` rows: auto-approve only
  when `settings.payout_auto_approve` is true AND age > window AND state='requested'.
  Existing legacy event pairs are left untouched (history), not backfilled.
- Gates wired into `POST /api/combines/{id}/payout` (all raise typed 4xx with a
  machine-readable `code` so the frontend can route the user):
  `verification.assert_payout_eligible(db, user)` (KYC verified + tax profile +
  default payout method; each check individually toggleable via settings) and the
  existing eligibility checks.
- `POST /api/combines/{id}/activate-account` additionally requires
  `legal.assert_funded_agreement_signed(db, user)` → 403 `code="agreement_required"`.
- Purchase endpoints require `legal.assert_consented(db, user)` (tos + risk at current
  versions) → 403 `code="consent_required"`.

### KYC / tax / methods (B2) — `routers/verification.py`, prefix `/api/verification`
- `GET /status` → {kyc: {status, reject_reason?}, tax: {form_type?, submitted: bool},
  payout_methods: [...], requirements: {kyc, tax, method} } (requirements reflect settings).
- `POST /kyc/submit` {legal_name, dob, country, document_type} → pending; sim provider
  immediately verifies unless country ∈ settings.ofac_blocked_countries → rejected.
- `POST /tax/submit` {form_type W9|W8BEN, legal_name, country, address, tin_last4}.
- `POST /methods` {type ach|wire|crypto, label, details} / `DELETE /methods/{id}` /
  `POST /methods/{id}/default`. Details stored as JSON; NEVER log them.
- Service functions for C1: `assert_payout_eligible(db, user)`.

### Legal (B1) — `services/legal.py` owns `LEGAL_DOC_VERSIONS = {"tos": 1, "privacy": 1,
"refund": 1, "risk": 1, "funded_agreement": 1}`
- `GET /api/legal/status`, `POST /api/legal/accept` {doc_keys: [...]},
  `POST /api/legal/sign-funded-agreement` {typed_name} (records signature_name).
- Service functions for C1: `assert_consented`, `assert_funded_agreement_signed`.

### Email / notifications (B3)
- `services/mailer.py`: `get_mailer()` → ConsoleMailer (default) | SMTPMailer
  (settings.mail_provider="smtp"). `services/notify.py`:
  `notify(db, user, kind, title, body, email=True)` writes `notifications` +
  `email_outbox` (to user.email, subject=title). No template engine — f-strings.
- `jobs/send_outbox.py` drains queued outbox rows (attempts, last_error, max 5).
- `jobs/notify_events.py` tails combine_events past a watermark stored in
  platform_state KV (key "notify_events_watermark") and maps event types → notify():
  funded, failed, payout_requested/approved/denied, renewal, reset, day-lock.
- Forgot password: `POST /api/auth/forgot` {email} → ALWAYS 200; creates
  PasswordResetToken (sha256 stored, 2h TTL), enqueues email with
  `{settings.frontend_base_url}/reset-password?token=…`.
  `POST /api/auth/reset` {token, new_password} → set hash, revoke ALL sessions, mark used.
- `GET /api/notifications` (recent 50 + unread count), `POST /api/notifications/read`.

### Platform state (B5)
- `services/platform_state.py`: `get_value(db, key, default)` / `set_value(db, key, value)`
  (JSON) + typed helpers `get_trading_mode`, `set_trading_mode`, `get_banned_symbols`.
- `_require_tradeable` additions (order matters, cheapest first): user.suspended_at →
  403; trading mode halted → 503 code="trading_halted"; close_only and the request is
  an OPEN → 409; symbol banned or ∉ settings.zero_dte_universe (when
  settings.enforce_tradeable_universe) → 422 code="symbol_not_tradeable".
  order_monitor: entry-order fills respect halted/close_only; exits always allowed.
- Quote-quality gate at open (settings-driven, defaults conservative):
  reject option leg when mid < settings.min_option_mid ($0.05) or
  (ask−bid)/mid > settings.max_option_spread_ratio (1.0) → 422 code="quote_quality".

### Admin API (C2) — `routers/admin.py`, prefix `/api/admin`, all `require_admin`
- Users: `GET /users?q=&page=`, `GET /users/{id}` (combines, payments, events, tickets,
  kyc, payout requests), `POST /users/{id}/suspend|unsuspend|promote|demote|grant-reset-credit`.
- Combines: `POST /combines/{id}/adjust` {action: fail|unfail|extend_billing, reason}.
- Payments: `POST /payments/{id}/refund` {reason} (reuses payments.py refund logic).
- Payouts: `GET /payouts?state=`, `POST /payouts/{id}/approve|deny|hold`
  {reason_code?, note?} via services/payout_desk.py.
- `GET /metrics` (MRR = active combines' monthly price sum, tier counts, pass/fail
  rates, outstanding payout liability), `GET /jobs` (latest JobRun per job),
  `GET /platform` + `PUT /platform` {trading_mode, banned_symbols},
  `GET /tax/1099?year=`.
- Support queue: `GET /support/tickets?status=`, `POST /support/tickets/{id}` {status, admin_note}.

## Sequencing

Phase A (done inline) → Phase B: B1–B5 in parallel → Phase C: C1 then C2 →
Phase D: D1–D3 in parallel → Phase E: full suites green → Phase F: adversarial review.
