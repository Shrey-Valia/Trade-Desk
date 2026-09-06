# Deployment Runbook

Single-container deployment: the FastAPI backend serves the API **and** the
built React SPA. Built by the multi-stage `Dockerfile` at the repo root,
run via `docker-compose.yml` locally or `fly.toml` in production.

**Production target: Fly.io** — see [Deploying to Fly.io](#deploying-to-flyio).
The compose path below stays the local/self-hosted route and the way to
smoke-test the image before shipping it.

## Quick start

```bash
cd "Trade Dashboard"
# put secrets in a .env file next to docker-compose.yml (compose reads it)
docker compose up -d --build
# app + SPA on http://localhost:8000 ; health probe on /health
docker compose logs -f app
```

The image bakes in `SERVE_FRONTEND_DIR=/app/frontend/dist`,
`DATABASE_URL=sqlite:////app/data/dashboard.db`, and `APP_ENV=production`.
Everything under `/app/data` (SQLite DB, journal-screenshot uploads,
nightly backups) lives on the `trade_data` named volume.

## THE single-replica constraint (do not skip)

**Run exactly one container per database, with exactly one uvicorn worker.**
APScheduler runs *in-process*: every scheduled job — billing renewals,
combine settlement, payout auto-approval, EOD settlement, the nightly
backup — fires from inside the app process. A second replica (or
`uvicorn --workers 2`) runs a second scheduler and **double-fires billing
and settlement**, corrupting money state. The Dockerfile's CMD is already a
single worker with no `--reload`; never override it with more. Scale reads
with a cache/CDN in front, not with more app processes.

## Environment variables

Compose passes these through from the host shell or a `.env` file beside
`docker-compose.yml`. Unset = the default below.

> **Format note:** list-valued settings (`CORS_ALLOW_ORIGINS`,
> `ADMIN_EMAILS`) are parsed by pydantic-settings as **JSON arrays**, e.g.
> `CORS_ALLOW_ORIGINS=["https://app.example.com"]`. Comma-separated strings
> fail to parse and abort boot.

> **Compose passthrough trap — read before adding a variable.** A bare
> `- VAR` in the compose `environment:` list does **not** mean "use the
> host's value if set, otherwise keep the image's". When the host doesn't
> set it, compose **unsets the variable in the container**, erasing any
> `ENV` baked into the image; when the host *does* set it (including from
> the dev `.env` beside the compose file), that value is injected verbatim,
> even if it only makes sense outside a container. Both of these bit us for
> real: `APP_ENV` was erased, so the app fell back to `development` and
> dropped the `Secure` flag from the session cookie, and the dev
> `DATABASE_URL`'s **relative** sqlite path was injected, putting the
> database in the container's writable layer instead of the `/app/data`
> volume. Any variable whose image default must survive needs an explicit
> `- VAR=${VAR:-default}`, as `APP_ENV` and `DATABASE_URL` now have.

| Variable | Default | Prod guidance |
|---|---|---|
| `APP_ENV` | `production` (image) | Leave as `production`; hardens cookie defaults. |
| `COOKIE_SECURE` | follows `APP_ENV` (`true` in prod) | Set `0` only for plain-HTTP LAN testing — browsers will otherwise drop the session cookie off-localhost. |
| `CORS_ALLOW_ORIGINS` | Vite dev origins | Only needed if the SPA is served from a *different* origin than the API. Same-origin (this image's default) needs nothing. JSON array. |
| `TRUST_PROXY` | `false` | Set `1` **only** behind a reverse proxy that appends real client IPs to `X-Forwarded-For`; otherwise rate-limit keying is spoofable. |
| `FRONTEND_BASE_URL` | `http://localhost:5173` | Public URL of the app — used to build links in emails (password reset, payout status). Set to your real origin. |
| `DATABASE_URL` | `sqlite:////app/data/dashboard.db` | See "SQLite → Postgres" below. |
| `SENTRY_DSN` / `SENTRY_ENVIRONMENT` | empty / `development` | Empty = error tracking fully off — a crash is then invisible. See "Error tracking" below. |
| `HEALTH_SCHEDULER_STALE_S` | `900` | `/health` 503s when no scheduled job has recorded a run in this many seconds — the only external signal that the in-process scheduler died. `0` disables. |
| `SENTRY_RELEASE` | empty | Pins events to a deploy. Falls back to Fly's `FLY_IMAGE_REF`; without either, a regression is indistinguishable from an old bug. |
| `LOG_LEVEL` / `LOG_JSON` | `INFO` / `false` | `LOG_JSON=1` emits one JSON object per line for log aggregators. |
| `ALPACA_API_KEY` / `ALPACA_API_SECRET` / `ALPACA_PAPER` | empty / `true` | Required for live quotes, chains, fills. |
| `FINNHUB_API_KEY`, `FRED_API_KEY` | empty | News / macro data. |
| `ADMIN_EMAILS` | `[]` | JSON array; listed emails are auto-promoted to admin at signin — the bootstrap for the first operator seat. |
| `SIGNUP_REQUIRE_INVITE` | `false` | `1` closes signup: `POST /api/auth/signup` then demands a valid invite code. See "Invite-only launch" below. |
| `INVITE_DEFAULT_TTL_DAYS` | `14` | TTL the admin mint form pre-fills. `0` = codes never expire. |
| `PAYOUT_AUTO_APPROVE` | **follows `APP_ENV`** — off in production, on in dev | Unset is the safe answer: in production a payout waits for a human. Setting `1` in production restores unattended approval on a timer with `reviewer_id=None`, and the preflight warns about it every boot. |
| `KYC_AUTO_VERIFY` | **follows `APP_ENV`** — off in production, on in dev | Unset is the safe answer: submissions park at `pending` for an admin decision. `1` restores the simulated instant-verify provider. |
| `MAIL_PROVIDER` | `console` | `console` logs mail to stdout; `smtp` sends via the `SMTP_*` settings. |
| `MAIL_FROM`, `SMTP_HOST`, `SMTP_PORT`, `SMTP_USERNAME`, `SMTP_PASSWORD`, `SMTP_STARTTLS`, `SMTP_SSL` | see `backend/config.py` | Only used when `MAIL_PROVIDER=smtp`. `SMTP_SSL=1` for implicit TLS (port 465) instead of STARTTLS (587). **`MAIL_FROM` must be a real domain** — the transport refuses to start otherwise. See "Transactional email" below. |
| `STRIPE_SECRET_KEY`, `STRIPE_WEBHOOK_SECRET`, `STRIPE_PRICE_50K/100K/150K` | empty | Opt-in; payments stay simulated while unset. |
| `BACKUP_RETENTION_DAYS` | `14` | Nightly-backup retention window. |
| `BACKUP_OFFSITE_PROVIDER` | `none` | `none` = backups never leave the volume they are protecting. `s3` = mirror every nightly snapshot to an S3-compatible bucket. See "Offsite copies" below. |
| `BACKUP_S3_BUCKET`, `BACKUP_S3_REGION`, `BACKUP_S3_ENDPOINT_URL`, `BACKUP_S3_PREFIX`, `BACKUP_S3_ACCESS_KEY_ID`, `BACKUP_S3_SECRET_ACCESS_KEY` | empty / `auto` / empty / `backups/` / empty / empty | Only used when `BACKUP_OFFSITE_PROVIDER=s3`, and then **all of bucket/region/keys are required** — an incomplete set fails the backup job instead of silently not replicating. Leave the endpoint blank for bare AWS S3; set it for R2/B2/MinIO. |
| `BACKUP_OFFSITE_RETENTION_DAYS` | `0` | `0` = the app never deletes a remote object (prefer a bucket lifecycle rule, whose blast radius isn't this process). A positive value enables app-side pruning, which still always keeps the newest 3 snapshots. |
| `ALLOW_LEGACY_TRADE_WIPE` | `false` | **Leave unset.** See "restored pre-tier backup" below. |
| `LEGAL_ENTITY_NAME`, `LEGAL_ENTITY_JURISDICTION`, `LEGAL_CONTACT_EMAIL`, `LEGAL_CONTACT_ADDRESS` | empty | Who the public Terms/Privacy/Refund pages name as the counterparty, and how to reach them. Unset = the pages omit the entity and governing-law clause and point at the in-app Support page. See "Legal identity" below. |

Full list with inline docs: `backend/config.py`.

## Deploying to Fly.io

`fly.toml` at the repo root is the production config. It pins **one machine
on one volume**, keeps `auto_stop_machines` off, forces HTTPS, and sets the
closed-launch posture (`SIGNUP_REQUIRE_INVITE=1`, human payout/KYC review).

### One-time setup

```bash
brew install flyctl && fly auth login
```

1. **Create the app** without deploying (reserves the name; edit `app =` in
   `fly.toml` if `trade-desk` is taken):

   ```bash
   fly apps create trade-desk
   ```

2. **Create the volume** — 3GB is ample for a SQLite database, screenshot
   uploads and 14 days of backups. It must live in `primary_region`:

   ```bash
   fly volumes create trade_data --region iad --size 3
   ```

3. **Set the secrets.** These are the ones that must NOT sit in `fly.toml`.
   Note `ADMIN_EMAILS` is parsed as a **JSON array** — the shell quoting
   below matters, and a comma-separated string aborts boot:

   ```bash
   fly secrets set \
     ALPACA_API_KEY=... \
     ALPACA_API_SECRET=... \
     FINNHUB_API_KEY=... \
     FRED_API_KEY=... \
     ADMIN_EMAILS='["you@yourdomain.com"]'
   ```

   Setting secrets restarts the machine, so do it before the first deploy
   (or expect one extra restart).

4. **Deploy:**

   ```bash
   fly deploy
   ```

5. **Verify** — health, then the real thing:

   ```bash
   fly status
   curl -sS https://trade-desk.fly.dev/health
   fly logs
   ```

   `/health` returns 200 only when the database answers. Then sign in with
   the `ADMIN_EMAILS` address, confirm **Admin → Invites** loads *without*
   the "signup is open" warning banner (its absence is the proof the gate
   is live), mint a code, and redeem it from a private window.

### Custom domain

```bash
fly certs add app.yourdomain.com
```

Add the DNS records it prints, wait for `fly certs show app.yourdomain.com`
to go green, then **update `FRONTEND_BASE_URL` in `fly.toml` to the new
origin** and redeploy. Leaving it on the `.fly.dev` name sends every
password-reset and payout email out with links pointing at the wrong host.

### Things that will bite you

- **Never `fly scale count 2`.** One volume attaches to one machine, and a
  second machine means a second APScheduler double-firing billing and
  settlement. Read the banner at the top of `fly.toml`.
- **Never let the machine auto-stop.** Fly suspends idle machines by
  default; `fly.toml` disables it. A suspended machine silently skips
  billing renewals, settlement and the nightly backup — nothing alerts you,
  the jobs just never run. Check **Admin → Jobs** for staleness after any
  config change.
- **Deploys are downtime.** `strategy = "immediate"` is forced by the
  single-volume constraint: there is nowhere to stand up a replacement.
  Deploy outside market hours.
- **Fly volume snapshots are not your backup.** They default to 5-day
  retention and live in the same failure domain. The nightly `backup_db`
  job writes into `/app/data/backups` on that same volume, so pull copies
  off the machine on a schedule:

  ```bash
  fly ssh sftp get /app/data/backups/dashboard-YYYYMMDD-HHMMSS.db
  ```

- **Memory.** `[[vm]] memory = "1gb"` is not padding: pandas + numpy +
  scipy are resident from first import and 512MB OOMs during startup.

## Error tracking (Sentry)

Until `SENTRY_DSN` is set, **a crash is invisible**: mail is console-only, so
a user can't tell you, and nothing else is watching. This is the cheapest
risk reduction available before handing out invites.

Setup — the DSN is the only thing you need, and it is a **secret**:

1. Create a free Sentry account and a **Python / FastAPI** project.
2. Copy the DSN it shows (`https://<key>@<org>.ingest.sentry.io/<id>`).
3. `fly secrets set SENTRY_DSN='https://...'` — this restarts the machine.

`SENTRY_ENVIRONMENT=production` is already set in `fly.toml`. Confirm it took
by watching for the startup line, which reports the release it tagged:

```bash
fly logs | grep "sentry initialised"
# sentry initialised (env=production release=<image ref>)
```

**What you get for free.** Scheduled-job failures are the reason this
matters, and they arrive without extra wiring: `run_logged` re-raises,
APScheduler logs the exception at ERROR, and the SDK's default logging
integration promotes ERROR records to events. So a settlement, billing
renewal, or nightly backup that dies at 3am becomes an issue in Sentry
rather than a line in an untailed log. That chain is indirect enough to
break quietly, so `backend/tests/test_sentry_wiring.py` pins it.

**Release tagging.** `release` falls back to Fly's `FLY_IMAGE_REF` when
`SENTRY_RELEASE` is unset, so each deploy is distinguishable and a
regression can be pinned to the build that introduced it.

**PII.** `send_default_pii=False`, and a `before_send` hook scrubs
`Cookie` / `Set-Cookie` / `Authorization` / `X-API-Key` before anything
leaves the process — an error report is never worth leaking a live session
token. `User-Agent` and the path survive, since those are what let you
reproduce the failure.

**Sentry catches crashes, not silence.** A machine that is up but wedged, or
one that never restarted after an OOM, produces no events at all. That is
what the uptime check below is for — the two are complements, not
alternatives.

## Uptime check

`/health` returns 200 only when **both** hold:

- the database answers a `SELECT 1`, and
- some scheduled job has recorded a run within `HEALTH_SCHEDULER_STALE_S`
  (default 900s).

That second condition is the one worth understanding. A plain liveness probe
cannot see the failure that actually costs money: the process answering HTTP
perfectly while the in-process APScheduler thread is dead, so billing
renewals, combine settlement, EOD settlement and the nightly backup have
silently stopped. Nothing user-visible breaks for hours. Since every job
writes a `job_runs` row, total silence is the one externally observable
symptom — so `/health` degrades to 503 on it, which makes Fly restart the
machine (the correct remediation for a dead thread) and makes any external
monitor fire.

Two deliberate non-alarms: an empty `job_runs` table reports `unknown`, not
stale (a fresh database is not a fault), and there is a startup grace of one
full window (a restart inside the window must not look like a dead
scheduler). A check that cries wolf gets muted, which is worse than no check.

The endpoint is unauthenticated, so it never names which job is late —
job-level detail lives behind **Admin → Jobs**.

### The monitor

`.github/workflows/uptime.yml` polls it every 10 minutes and fails the run
when unhealthy; GitHub emails you on a failed scheduled run. Enable it by
adding a repository **variable** (not a secret) under Settings → Secrets and
variables → Actions → Variables:

```
HEALTH_URL = https://trade-desk.fly.dev/health
```

Until that variable exists, every run exits 0 with a skip notice — safe to
merge before the first deploy. `workflow_dispatch` is enabled so you can
prove it works without waiting for the cron. It retries 3× over ~40s, so a
single dropped connection or a deploy restart is not treated as an outage.

**Know what this is not.** GitHub cron granularity is 5 minutes minimum and
scheduled runs are frequently delayed 10+ minutes under load, so this
detects "down for a while", not "down for 30 seconds". Scheduled workflows
are also **disabled automatically after 60 days of repo inactivity** — a
quiet month silently turns the monitor off. And the only notification is a
workflow-failure email: no SMS, no escalation.

A free tier of a real monitor (UptimeRobot, Better Stack, Healthchecks.io)
beats it on every one of those axes and takes about five minutes to point at
the same URL. Do that when the beta has real users; the workflow is what
works today with no signup.

## Transactional email (real SMTP)

While `MAIL_PROVIDER=console` (the default) mail is only **logged**, so a
locked-out user can't self-serve recovery. The stopgap is **Admin → Users →
_user_ → Password reset link…**, which mints a single-use link you hand over
directly (see "Recovering a locked-out user" below). Real SMTP is still what
you want before the beta grows.

### Setup

1. Pick a provider and verify a sending domain (Resend, Postmark, SES,
   Mailgun — any of them speaks SMTP). **Verifying the domain, i.e. adding
   the SPF and DKIM DNS records they give you, is the step that decides
   whether mail lands in an inbox or a spam folder.** It is not optional.
2. Set the secrets — password and host are secrets, the rest is config:

   ```bash
   fly secrets set \
     MAIL_PROVIDER=smtp \
     MAIL_FROM='Trade Desk <no-reply@yourdomain.com>' \
     SMTP_HOST=smtp.provider.com \
     SMTP_PORT=587 \
     SMTP_USERNAME=... \
     SMTP_PASSWORD=...
   ```

   For a provider on port **465**, add `SMTP_SSL=1` (implicit TLS) instead of
   relying on STARTTLS.

3. **Prove it before trusting a password reset to it:**

   ```bash
   backend/.venv/bin/python backend/scripts/send_test_email.py you@yourdomain.com
   ```

   It prints the resolved config (credentials shown only as set/unset),
   sends one real message, and names the likely cause on failure. **Check the
   spam folder too** — a message that arrives but is filtered is a failure,
   and it is the most likely outcome of a sending domain without SPF/DKIM.

### What the transport guarantees

- **`MAIL_FROM` must be routable.** The transport refuses to start on the
  shipped `@tradedesk.local` default (or `.invalid` / `.example` / `.test` /
  no domain at all). A real provider cannot deliver an unroutable From, so
  the alternative was every reset silently vanishing with no error anywhere.
  The refusal surfaces as a loud job failure — visible in Sentry and
  **Admin → Jobs** — and leaves the mail queued rather than marking it dead.
- **Messages are RFC-valid.** `Date` and `Message-ID` are set explicitly.
  smtplib adds neither, so mail previously went out without a `Date` — which
  RFC 5322 requires and which spam filters score heavily.
- **Retries survive an outage.** A transient failure is retried on a backoff
  of roughly 1m / 5m / 20m / 1h / 3h — about 4.5 hours across five attempts,
  rather than the ~2.5 minutes the old 30s job cadence allowed. A brief
  provider incident no longer permanently drops a queued password reset.
- **Permanent refusals fail fast.** An SMTP 5xx (bad mailbox, rejected
  message) goes terminal on the first attempt instead of pretending for
  hours that it might land.

Queued mail lives in `email_outbox`; `jobs/send_outbox.py` drains it every
30s. A row that goes `failed` is terminal — the log line and `last_error`
say why.

## Recovering a locked-out user

**Admin → Users → _the user_ → Password reset link…** mints a single-use
link, shows it once, and queues a copy to the user's own address. Send it
over any channel you trust; they choose their own password.

It deliberately **does not set a password.** An operator who knows a
trader's password can open positions and request payouts as them — that
destroys non-repudiation on a platform that moves money and makes the audit
log unfalsifiable. The operator only ever handles a link.

Worth knowing before you use it:

- **The link is shown exactly once.** Only its sha256 is stored, so it
  cannot be retrieved later. Minting a replacement invalidates the previous
  one — there is at most one live link per account.
- **It expires** after `PASSWORD_RESET_TTL_H` (default 2 hours).
- **Minting does not sign the user out.** Their current session keeps
  working until they complete the reset. To block access right now,
  **suspend** the account instead — that is the tool for a suspected
  compromise.
- **Completing the reset revokes every session** for that account.
- **A reason is required** and lands in the audit log. The raw token never
  does — an audit row is long-lived and widely readable, and logging the
  token beside a hashed column would defeat hashing it.
- Resetting another **admin** is allowed: operators legitimately recover a
  colleague, and forbidding it buys nothing when the same admin could
  demote, reset, and re-promote. It is audited like everything else.

## Invite-only launch

`SIGNUP_REQUIRE_INVITE=1` is the gate for a closed launch: with it set,
signup refuses any request without a valid, unredeemed invite code
(`403 invite_required: …`). Without it, **anyone with the URL can create an
account** — minting codes alone does not close the door, which is why the
admin Invites tab shows a warning banner whenever the flag is off.

Codes are minted in the operator console under **Admin → Invites** (or
`POST /api/admin/invites`). Each is single-use, optionally bound to one
email, optionally expiring, and revocable until it's redeemed; both minting
and revoking write `AdminAction` audit rows. The mint dialog also builds a
`/signup?invite=CODE` link that prefills the form, so an invitee gets one
link instead of a link plus a code to retype.

Two things to know before flipping it:

- **It gates new accounts only.** Existing users keep signing in normally,
  so turning it on mid-flight locks nobody out.
- **A code supplied while the gate is OFF is still validated and redeemed.**
  A wrong code is refused either way — the ledger never silently drops one.

```bash
SIGNUP_REQUIRE_INVITE=1
ADMIN_EMAILS=["you@yourdomain.com"]   # you need the console to mint codes
```

## Legal identity

The public legal pages (`/terms`, `/privacy`, `/refund-policy`,
`/risk-disclosure`) are a contract with real people, and a contract needs a
counterparty: who is bound, where disputes are heard, and a contact that
reaches a human. None of that can live in source, so the pages read it from
four settings via the public `GET /api/legal/identity`:

```bash
fly secrets set \
  LEGAL_ENTITY_NAME="Your Company LLC" \
  LEGAL_ENTITY_JURISDICTION="Delaware, United States" \
  LEGAL_CONTACT_EMAIL="legal@yourdomain.com" \
  LEGAL_CONTACT_ADDRESS="1 Main St, Dover DE 19901"   # optional
```

`LEGAL_ENTITY_JURISDICTION` is free text, written as it should read in a
clause ("organised under the laws of …", "governed by the laws of …"). One
contact address is deliberate: a small operator has one inbox, and three
aliases that all forward to it help nobody.

**Unset is handled honestly, not papered over.** The pages previously
hard-coded `legal@tradedesk.example`, `privacy@…` and `billing@…` — addresses
that bounce. A contact that silently fails is worse than no contact: someone
with a GDPR request follows the instruction, hears nothing, and reasonably
concludes they were ignored. So while these are blank:

- the email clause is omitted entirely and the sentence falls back to the
  in-app **Support page**, which always reaches someone;
- the entity and governing-law clause is **omitted**, rather than filled with
  boilerplate naming a jurisdiction nobody chose;
- the production preflight warns on every boot.

`LEGAL_ENTITY_NAME` and `LEGAL_CONTACT_EMAIL` are both required before the
clause appears — a name with no way to reach it, or an inbox belonging to
nobody named, is not a counterparty.

> **This is plumbing, not counsel.** Filling these in makes the documents
> name a real party and offer a real contact. It does not make the text
> right for your entity, your jurisdiction, or your product — the legal
> pages still need a lawyer's read before you take real users.

## Configuration preflight

Every serious near-miss this project has had came from configuration, not
code: the demo dry-run nearly died on an empty `ADMIN_EMAILS`, the container
smoke test found the session cookie shipping without `Secure` because compose
had erased `APP_ENV`, and `MAIL_FROM` defaulted to an unroutable `.local`
domain. In each case the app booted happily and looked fine.

So `APP_ENV=production` now runs a preflight at startup
(`backend/services/preflight.py`) that reports every setting whose value means
something different in a deployment than it does on a laptop. Read it in
`fly logs` right after a deploy:

```
WARNING preflight: 5 production configuration warning(s) —
  [WARN] SIGNUP_REQUIRE_INVITE: off, so POST /api/auth/signup is open to the public internet → …
  [WARN] MAIL_PROVIDER: 'console': every transactional mail is written to stdout instead of sent → …
  [WARN] SENTRY_DSN: unset, so an unhandled exception — including a scheduled job dying — is invisible → …
  [WARN] BACKUP_OFFSITE_PROVIDER: 'none': nightly backups are written beside the live database → …
  [WARN] COOKIE_SECURE: explicitly off in production: the session cookie is sent over plain HTTP → …
```

The same findings appear in **Admin → Overview**, at the top of the tab, via
`GET /api/admin/preflight`. Boot logs scroll away within minutes of a deploy;
the settings they describe do not. Both surfaces name the *setting* and what
its current value implies — a value is never echoed, so the panel is safe to
have on screen.

**Two levels, and the split is deliberate.** A `WARN` is logged and shown, and
the app serves — these are posture choices, not broken flows. A `REFUSE` stops
the boot, and there is currently exactly one, because a refusal that fires on
a merely-risky setting turns the next restart of a healthy deployment into an
outage:

| Level | Condition | Why this line |
|---|---|---|
| **REFUSE** | `MAIL_PROVIDER` is real **and** `FRONTEND_BASE_URL` is localhost / an unroutable TLD | Every link the app mails — password reset, admin-minted reset, payout status — is built from that base URL. Real recipients would get a URL resolving to their own machine: delivered, no error, account unrecoverable. It can only fire once someone has deliberately configured real mail. |
| WARN | `ADMIN_EMAILS` empty | No operator seat exists and `/admin` 403s for everyone. |
| WARN | `SIGNUP_REQUIRE_INVITE` off | Signup is open to the public internet. |
| WARN | `MAIL_PROVIDER=console` | Password resets go to stdout; recovery means fishing a token out of the logs. |
| WARN | `PAYOUT_AUTO_APPROVE` explicitly on | Real money approving itself on a timer with no human in the audit trail. |
| WARN | `KYC_AUTO_VERIFY` explicitly on | Identity documents rubber-stamped by the simulated provider. |
| WARN | `SENTRY_DSN` unset | Crashes and dying scheduled jobs are invisible outside the container logs. |
| WARN | `BACKUP_OFFSITE_PROVIDER=none` | Backups share a failure domain with the database — see below. |
| WARN | `COOKIE_SECURE` forced off | Session cookie sent over plain HTTP. |
| WARN | `TRUST_PROXY` off on Fly / on with no proxy | Either the throttle keys every user to the proxy's IP, or `X-Forwarded-For` is spoofable straight past it. |

The database-URL refusal in `backend/database.py` (a relative sqlite path
under production) predates this and still fires first, at import.

**Nothing fires outside production.** A dev box and CI get an empty list by
design — on a laptop every one of these defaults is the right answer, and a
check that cries wolf is one people learn to scroll past.

To see it locally, run the backend in production posture against a throwaway
database:

```bash
APP_ENV=production COOKIE_SECURE=0 ADMIN_EMAILS='["you@example.com"]' DATABASE_URL=sqlite:////tmp/td-preflight.db uv run --directory backend uvicorn main:app --port 8000
```

## Backups & restore

**Where they land.** A scheduler job (`backup_db`, 02:30 ET nightly) writes
`dashboard-YYYYMMDD-HHMMSS.db` (UTC stamp) into `/app/data/backups` using
sqlite3's online-backup API — safe against concurrent writers, always a
consistent snapshot. Files older than `BACKUP_RETENTION_DAYS` are pruned on
each run, and the snapshot is mirrored offsite when a provider is
configured (below). Job outcomes are visible in the admin jobs-health view
(`job_runs`).

### Offsite copies (the volume is not a backup)

`/app/data/backups` sits on **the same Fly volume as the live database**.
Losing that volume — hardware, a region incident, a mistaken `fly volumes
destroy` — takes the database and every backup of it in one step. Fly volume
snapshots don't fix this either: 5-day retention, same provider, same region,
and nothing you have ever restored from.

Set `BACKUP_OFFSITE_PROVIDER=s3` and the nightly job mirrors each snapshot to
an S3-compatible bucket right after writing it locally. Works with Cloudflare
R2, Backblaze B2, MinIO, or AWS S3. Setup with R2 (cheapest for this: no
egress fees, and the free tier covers a database this size):

1. Create a bucket, then an **R2 API token scoped to that bucket only** with
   Object Read & Write. Note the account ID from the endpoint R2 shows you.
2. Set the secrets (all in one command — a partial set fails the job):

   ```bash
   fly secrets set \
     BACKUP_OFFSITE_PROVIDER=s3 \
     BACKUP_S3_BUCKET=trade-desk-backups \
     BACKUP_S3_REGION=auto \
     BACKUP_S3_ENDPOINT_URL=https://<account-id>.r2.cloudflarestorage.com \
     BACKUP_S3_ACCESS_KEY_ID=<token-id> \
     BACKUP_S3_SECRET_ACCESS_KEY=<token-secret>
   ```

   R2 requires the literal `auto` region. AWS and B2 need their real region,
   and for bare AWS leave `BACKUP_S3_ENDPOINT_URL` unset.
3. **Don't wait for 02:30 ET to find out whether it works.** Force one now
   and then verify from the other end:

   ```bash
   fly ssh console -C "/app/backend/.venv/bin/python /app/backend/scripts/offsite_backup_check.py put"
   fly ssh console -C "/app/backend/.venv/bin/python /app/backend/scripts/offsite_backup_check.py list"
   ```

   `list` prints every remote snapshot with its age and exits non-zero when
   the newest is older than `--max-age-h` (default 48), so the same command
   doubles as a monitor check.
4. Set a bucket **lifecycle rule** for retention (e.g. delete after 90 days)
   and leave `BACKUP_OFFSITE_RETENTION_DAYS=0`. App-side pruning exists
   (`BACKUP_OFFSITE_RETENTION_DAYS=N`) and refuses to delete the newest 3
   snapshots whatever their age, but a lifecycle rule can't be triggered by a
   bug in this process.

**A failed upload fails the whole `backup_db` job**, on purpose: the local
snapshot and both prunes have already happened by then, so the only thing
left to report is that the copy which survives losing the volume didn't
happen. A green job next to an empty bucket is the failure this feature
exists to prevent. The error in Admin → Jobs leads with `LOCAL snapshot
… OK; OFFSITE copy FAILED — …`, so a red row doesn't mean there is no
backup at all.

**Run the restore drill.** A backup nobody has ever restored is not a
backup:

```bash
backend/.venv/bin/python backend/scripts/offsite_backup_check.py restore /tmp/restored.db
```

That downloads the newest remote snapshot, runs `PRAGMA integrity_check` on
it and prints row counts for `users` / `combines` / `trades`. Do it once at
setup and after any change to the bucket, credentials or prefix.

**Restore procedure** (SQLite):

1. Stop the app: `docker compose stop app`
2. Copy the chosen backup over the live DB (and clear stale WAL sidecars):
   ```bash
   docker compose run --rm --no-deps app sh -c \
     'cp /app/data/backups/dashboard-YYYYMMDD-HHMMSS.db /app/data/dashboard.db \
      && rm -f /app/data/dashboard.db-wal /app/data/dashboard.db-shm'
   ```
3. Start it again: `docker compose start app`

**Boot refusal on a restored pre-tier backup.** If the restored `trades`
table predates the `tier` column *and has rows*, the app **refuses to
boot** with a loud `RuntimeError` instead of running the legacy migration
(which would delete every trade row). That refusal almost always means you
restored a much-too-old backup — restore a newer one. Only for a genuine
one-time adoption of a pre-tier legacy database whose trade history is
expendable, set `ALLOW_LEGACY_TRADE_WIPE=1` for a single boot, then unset it.

## SQLite → Postgres

Supported via configuration only — the image ships the psycopg driver:

```bash
DATABASE_URL=postgresql+psycopg://user:pass@host:5432/trade
```

`init_db()` creates the schema and runs the additive migrations on first
boot (CI proves this against postgres:16 on every push). Pool knobs
(`DB_POOL_SIZE`, `DB_MAX_OVERFLOW`, `DB_POOL_RECYCLE_S`) exist in
`backend/config.py`; SQLite ignores them. The nightly `backup_db` job
no-ops on Postgres — use `pg_dump` / managed snapshots instead, and note
that offsite mirroring rides on that job, so it no-ops too. The
single-replica constraint **still applies** on Postgres: it's the
scheduler, not the database, that forbids replicas.

## CI

`.github/workflows/ci.yml` job `docker-image` builds this Dockerfile on
every push (build only, no registry push — no credentials exist) so the
deploy artifact can't silently rot.
