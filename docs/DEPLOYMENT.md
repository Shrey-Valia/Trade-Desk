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
| `PAYOUT_AUTO_APPROVE` | `true` | Set `0` to require a human on every payout (the real-firm posture). |
| `MAIL_PROVIDER` | `console` | `console` logs mail to stdout; `smtp` sends via the `SMTP_*` settings. |
| `MAIL_FROM`, `SMTP_HOST`, `SMTP_PORT`, `SMTP_USERNAME`, `SMTP_PASSWORD`, `SMTP_STARTTLS` | see `backend/config.py` | Only used when `MAIL_PROVIDER=smtp`. |
| `STRIPE_SECRET_KEY`, `STRIPE_WEBHOOK_SECRET`, `STRIPE_PRICE_50K/100K/150K` | empty | Opt-in; payments stay simulated while unset. |
| `BACKUP_RETENTION_DAYS` | `14` | Nightly-backup retention window. |
| `ALLOW_LEGACY_TRADE_WIPE` | `false` | **Leave unset.** See "restored pre-tier backup" below. |

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

## Backups & restore

**Where they land.** A scheduler job (`backup_db`, 02:30 ET nightly) writes
`dashboard-YYYYMMDD-HHMMSS.db` (UTC stamp) into `/app/data/backups` using
sqlite3's online-backup API — safe against concurrent writers, always a
consistent snapshot. Files older than `BACKUP_RETENTION_DAYS` are pruned on
each run. Job outcomes are visible in the admin jobs-health view (`job_runs`).

Copy backups off the box regularly — the volume is not offsite storage:

```bash
docker compose cp app:/app/data/backups ./offsite-backups
```

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
no-ops on Postgres — use `pg_dump` / managed snapshots instead. The
single-replica constraint **still applies** on Postgres: it's the
scheduler, not the database, that forbids replicas.

## CI

`.github/workflows/ci.yml` job `docker-image` builds this Dockerfile on
every push (build only, no registry push — no credentials exist) so the
deploy artifact can't silently rot.
