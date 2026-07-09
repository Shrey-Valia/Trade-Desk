# PROP-FIRM SHELL BUILD — 2026-06-12

Branch: `propfirm-shell` (off main @ e12882f). Plan approved in plan mode; built in 7 phases,
each its own commit(s). This log is the review map.

## What was built

Trade Desk went from a single-user trading terminal to a multi-user prop-firm product:

1. **Landing page** (`/` for guests) — hero, rules band, tier pricing cards, how-it-works,
   features, CTA funnel into signup→purchase. **$XX prices and XX% profit split are
   placeholders by your instruction — no numbers invented.**
2. **Auth** — real local auth: bcrypt passwords, HttpOnly SameSite=Lax session cookies
   (DB-backed, revocable), signup/signin/signout/me, sign-out row in Settings.
3. **Combines** — users own up to **5 non-archived combines** (paid tier instances with own
   name, Topstep-style account code `50KTC-{uid}-{8digits}`, own HWM/balance/trade history).
   Purchase wizard at `/combines/new`: tier cards → **placeholder payment** (clearly marked,
   records a `placeholder_paid` payment row; Stripe swaps in later) → name & launch.
   Archive frees a slot and keeps history. Header TierPill became a Topstep-style combine
   selector; Settings shows your combines.
4. **Management dashboard** (`/dashboard`, the new home) — summary pills, account balance
   over time (per-combine equity curve), performance tracker, **Path to Funding** rail
   (profit-target progress 50K→$3K / 100K→$6K / 150K→$9K, MLL cushion, DLL remaining —
   all display-only), combine cards with activate/rename/archive, first-purchase hero.

## Architecture decisions worth knowing

- **Frozen code untouched**: `account_tiers.py` (consumed per combine via new
  `services/combine_state.py`), `black_scholes.py`, chart overlay/synthetic candle.
  **Flagged exception (pre-approved in the plan): `zerodte.py`** got a ~10-line mechanical
  touch — `get_active_combine` dependency + `combine_id` stamp on `/open` and `/open-leg`,
  `_current_tier()` deleted. No fill/pricing logic changed.
- **Back-compat**: `GET /api/account/state` keeps every old field name (+ combine identity
  fields); legacy `POST /state/switch` survives as a deprecated shim. Old AccountState table
  stays on disk as the migration source only.
- **Migration**: `_backfill_multiuser()` adopts a pre-multi-user DB — creates `dev@local`
  (password `devpassword`, both in Settings/env), one combine per legacy tier with HWM
  carried, `migration_grant` payment rows, maps every trade. Fresh DBs skip it entirely
  (signup-first). **Verified against the real dev DB**: dev@local owns the 50K combine with
  the exact pre-migration balance ($50,269.34) and HWM ($50,547.37).
- **Gating**: journal/account/analytics/combines/stars/selections require auth and are
  scoped per user (cross-user access → 404). Market-data endpoints stay open.
- **Status columns are plain VARCHAR** (no SQLAlchemy Enum) so `passed`/`failed` can become
  persisted states later without a SQLite table rebuild. Today pass/fail is display-only:
  **nothing settles a combine automatically** — the dashboard says so honestly.

## Verification done

- Backend: **330 tests pass** (was 295; +35: auth, migration backfill, combines/5-cap,
  account-per-combine, analytics scoping). tsc 0 errors, eslint 0 errors, prod build clean.
- Live funnel (headless browser): landing CTA → signup (`?next=` honored) → tier pick →
  placeholder payment → provisioned (`100KTC-2-…`) → rename → terminal header on the new
  combine → journal trade bound to it (+$150 → bal $50,150, 5% objective) → bought to the
  5-cap (6th purchase 409 with clear message; wizard shows banner + disabled cards) →
  archive frees slots → dashboard reflects everything.
- Isolation: three users in the dev DB now (`dev@local`/`devpassword`,
  `trader2@test.local`/`password123` with "Eval Alpha" 100K, `trader3@test.local`/
  `password123` with cap-test combines + 1 trade). Each sees only their own data —
  cross-user reads/mutations 404.

## Needs verification at market open

- **0DTE open path with combines**: `/api/zerodte/open` + `/open-leg` stamping was a
  mechanical change verified by inspection + the shared dependency's tests, but a live BUY
  through the chain (market hours only) should be confirmed to land on the active combine.
- DLL/MLL pill behavior across combine switches during a live session.

## Decisions you may want to reverse / finish later

- **Test users in the dev DB** (trader2/trader3 + cap-test combines) — delete rows from
  users/combines/payments/auth_sessions/trades if you want a clean dev DB.
- **Old DashboardPage replaced** — the retired Analysis-mode composition (CalendarStrip +
  WatchlistColumn + StockDetailView) was overwritten by the management dashboard; children
  remain on disk, old composition in git history.
- **Signin lands on /dashboard** (was /positions). Terminal is one click away
  ("Launch terminal →").
- **Archive is the only "delete"** — hard delete deferred so trade history is never orphaned.
- **Dead endpoint `/api/zerodte/mark`** and the unused legacy `/state/switch` shim can be
  retired once nothing references them.
- When Stripe lands: `POST /api/combines/purchase` becomes the post-checkout fulfillment
  hook; payments rows gain real amounts/status; replace the wizard's placeholder step and
  the landing page's $XX / XX%.
