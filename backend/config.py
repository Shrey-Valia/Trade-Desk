from datetime import timedelta
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=PROJECT_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,
    )

    alpaca_api_key: str = ""
    alpaca_api_secret: str = ""
    alpaca_paper: bool = True
    alpaca_options_feed: str = "indicative"

    # ---------------------------------------------------------------------
    # Alpaca REST call budget. The free tier allows ~200 requests/min
    # (~3.3/s); the TOTAL across both buckets must stay under that. The
    # budget is split so background warming (prewarm / watchlist refresh /
    # chain collect) can never starve a live trader: request handlers draw
    # from a RESERVED interactive share, scheduled jobs from the remainder.
    alpaca_rate_limit_per_s: float = 3.0
    alpaca_interactive_reserve_per_s: float = 1.0
    # Hard deadline (seconds) on every Alpaca SDK network hop. The SDK
    # exposes no request timeout, so without this a stalled call hangs the
    # calling thread (request handler or scheduler job) indefinitely — the
    # circuit breaker only trips on ERRORS, never on a stall. Kept
    # comfortably above a healthy fetch (~1-3s).
    alpaca_sdk_timeout_s: float = 6.0
    # TTL (seconds) for the LIVE option-quote plane
    # (services.alpaca_client.get_live_option_quotes): refresh cadence for
    # the SMALL set of contracts being actively priced — open-position
    # marks, stop/TP/liquidation checks, focused chain rows. One batched
    # request per symbol per window (~0.1 req/s at the default), drawn from
    # the interactive bucket; the 300s chain STRUCTURE cache is unaffected.
    # Also caps how stale a "live" quote may be served — lowering it makes
    # every consumer fresher at the cost of more (still batched) calls.
    live_option_quote_ttl_s: float = 10.0

    # ---------------------------------------------------------------------
    # WS6 — real-time data feed (built behind a flag; ships DORMANT).
    #
    # OFF by default: with the flag False, `get_realtime_feed()` returns the
    # NoOp feed (whose accessors all return None), so `get_quotes`/`get_bars`
    # fall straight through to the unchanged REST + TokenBucket +
    # CircuitBreaker + TTLCache path — byte-for-byte today's behavior. Flip
    # to True ONLY once a paid Alpaca key (Algo Trader Plus) is entitled; the
    # lifespan then starts a background `StockDataStream` consumer over the
    # watchlist and the read paths serve fresh streamed quotes/bars first.
    # See docs/realtime-data-feed-spike.md.
    realtime_feed_enabled: bool = False
    # Staleness windows (seconds) for the in-memory last-value-wins store. A
    # streamed value older than this reads as None → the hot path falls back
    # to REST. The TTL *is* the stall detector: a silently half-open socket
    # stops writing, entries age out, polling resumes. Quotes get a short
    # window (fresh ticks); bars match the streamed 1m grain plus slack.
    realtime_quote_ttl_s: float = 3.0
    realtime_bar_ttl_s: float = 75.0

    finnhub_api_key: str = ""
    fred_api_key: str = ""

    database_url: str = f"sqlite:///{PROJECT_ROOT / 'data' / 'dashboard.db'}"
    log_level: str = "INFO"
    # Emit logs as one JSON object per line (timestamp/level/logger/message +
    # request_id when in a request) instead of the human-readable text format.
    # OFF by default so local dev stays readable; flip LOG_JSON=1 in prod where
    # a log aggregator (Datadog/Loki/CloudWatch) parses structured fields.
    log_json: bool = False

    # ---------------------------------------------------------------------
    # WS5 — Platform hardening: Postgres connection pool (ignored on SQLite,
    # which keeps its single-file check_same_thread shim). pool_size is the
    # steady-state checked-out ceiling; max_overflow is burst headroom above
    # it; pool_recycle proactively retires a connection older than N seconds
    # so we never hand out one the server has already timed out. Additive
    # with safe defaults — behaviour is unchanged until set in .env.
    db_pool_size: int = 5
    db_max_overflow: int = 10
    db_pool_recycle_s: int = 1800

    # Sentry error tracking. No-op when blank: main.py's lifespan skips
    # init entirely so a dev box / CI never phones home. Set SENTRY_DSN in
    # the deployment environment to turn it on.
    sentry_dsn: str = ""
    # Tags events so prod/staging/dev are separable in Sentry.
    sentry_environment: str = "development"
    # Fraction of transactions traced for performance monitoring (0 = off).
    sentry_traces_sample_rate: float = 0.0
    # /health scheduler-liveness window, seconds. A plain liveness probe
    # cannot see the failure that actually costs money: the process up and
    # answering while the in-process APScheduler thread is dead, so billing
    # renewals, settlement and the nightly backup silently stop. /health
    # therefore also checks how long it has been since ANY scheduled job
    # recorded a run, and degrades to 503 past this window. Generous by
    # design — the fastest job runs every few seconds, so 15 minutes of
    # total silence is unambiguous rather than a slow-job false alarm.
    # Set 0 to disable the check (status then reports "off").
    health_scheduler_stale_s: int = 900

    # Release identifier, so an error can be pinned to the deploy that
    # introduced it — without it every event looks like it came from the same
    # build and a regression is indistinguishable from a long-standing bug.
    # Left blank, main.py falls back to Fly's FLY_IMAGE_REF.
    sentry_release: str = ""

    # CORS allowlist. Comma-separated origins in .env (CORS_ALLOW_ORIGINS);
    # defaults to the Vite dev server so local dev keeps working with no
    # config. NEVER "*" — credentialed (cookie) auth forbids the wildcard.
    cors_allow_origins: tuple[str, ...] = (
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    )

    # Global per-IP request throttle (every endpoint, not just auth). A
    # coarse abuse / runaway-client guard layered on top of the
    # auth-specific brute-force limiter. Generous so normal dashboard
    # polling never trips it. attempts <= 0 disables it (e.g. behind an
    # upstream limiter). /health is exempt so probes never 429.
    global_rate_limit_attempts: int = 240
    global_rate_limit_window_s: int = 60

    # Simulated brokerage commission, $ per contract per side (entry and
    # exit each charge this × the position's contract count). The SINGLE
    # place to change the rate. Folded into cost basis / unrealized P&L in
    # the analytics endpoint and into realized P&L on close — display only;
    # the MLL/DLL engine reads net P&L separately (a later prompt).
    commission_per_contract: float = 0.65

    # Blended per-contract REGULATORY/EXCHANGE fee, $ per contract per side
    # (ORF + OCC clearing + sell-side SEC/TAF). Real options trades pay this on
    # top of commission, so omitting it makes paper P&L systematically rosy.
    # Folded into the same per-side cost as commission via `per_contract_fee`.
    regulatory_fee_per_contract: float = 0.04

    # Max age (seconds) of the underlying's LAST TRADE before a 0DTE open is
    # refused — a halted / thinly traded symbol can show a print minutes old
    # even during the session, and filling against it books a price the market
    # isn't at. 300s tolerates normal indicative-feed lag.
    max_spot_staleness_s: float = 300.0

    # FILL-TIME QUOTE GATE (audit wave 6) — a working SELL entry collects
    # credit, so filling it off a model mark when no live market exists is
    # the sim-exploitation vector the audit flagged: rest a sell, wait for a
    # cold feed, book fabricated premium. With this on, any SELL leg of a
    # working entry needs a genuine two-sided live NBBO at FILL time; the
    # order simply stays working through a cold tick (skip, never cancel).
    # BUY legs keep the legacy mid fallback (paying a model price collects
    # no edge). Mirrors the immediate-open path's _require_quote_quality.
    working_sell_fill_requires_quote: bool = True

    # ORDER-MONITOR CADENCE — seconds between trigger passes (working-order
    # fills, brackets, trailing/premium exits, close-limits, liquidation).
    # The audit's execution-quality finding: at 20s, 0DTE gamma can move
    # through a stop and back between ticks. 5s is the practical floor for a
    # POLLED data plane: the underlying quote cache is 5s and the live option
    # plane 10s, so a faster loop would just re-read cached marks. True
    # tick-driven triggers need the streaming feed (separate work).
    order_monitor_interval_s: float = 5.0

    # MARGIN / BUYING POWER — the capital constraint on opens. Requirement per
    # structure: max loss at expiry for defined-risk, Reg-T-style rates for
    # naked short sides (see calculations/margin.py). Checked at open/working
    # placement against the realized balance minus the requirement already
    # committed by the open + working book. Off → legacy behavior (no capital
    # check; contract cap + drawdown floors are the only brakes).
    margin_enforcement_enabled: bool = True
    margin_naked_pct: float = 0.20      # 20% of spot, less OTM amount
    margin_naked_min_pct: float = 0.10  # floor: 10% of spot (calls) / strike (puts)

    # EXPIRATION-DAY CLOSE-OUT — the prop-firm answer to assignment/pin risk
    # on physically-settled ETF options: the monitor force-flattens any open
    # position whose last leg expires TODAY once the clock is within this many
    # minutes of that session's close (half-day aware), and cancels working
    # orders on those dying contracts. Real desks (Topstep et al.) close 0DTE
    # books ~10 minutes before the bell rather than model OCC assignment.
    # 0 disables the policy (positions ride to expiry settlement instead).
    expiry_closeout_minutes: float = 10.0

    # ---------------------------------------------------------------------
    # Deployment environment. "development" (default) keeps the dev-friendly
    # behaviours (e.g. the session cookie is allowed over plain HTTP); set
    # APP_ENV=production in the deployment so security defaults harden
    # automatically — most importantly `cookie_secure` (see below). Kept
    # separate from `sentry_environment` (which only tags error events) so the
    # security posture isn't coupled to whether Sentry is configured.
    app_env: str = "development"

    # Whether to trust the X-Forwarded-For header for client-IP resolution
    # (rate-limit keying). OFF by default: XFF is client-controlled, so trusting
    # it with no proxy in front lets an attacker rotate the header to bypass the
    # brute-force / global throttles. Set TRUST_PROXY=1 ONLY when the app truly
    # sits behind a reverse proxy that appends the real peer address.
    trust_proxy: bool = False

    # ---------------------------------------------------------------------
    # Auth (multi-user prop-firm shell). bcrypt cost factor is 12 for
    # real use; tests drop it to 4 so signup-per-test stays fast.
    #
    # cookie_secure (Secure flag on the session cookie): env-driven and
    # PROD-SAFE BY DEFAULT. Left unset it follows app_env — True in production
    # (the cookie is then never sent over plain HTTP, closing a downgrade /
    # sidejacking hole), False in development so local HTTP dev keeps working.
    # An explicit COOKIE_SECURE in .env always wins (e.g. force True behind a
    # TLS-terminating proxy in staging). The property below resolves it.
    bcrypt_rounds: int = 12
    cookie_secure_override: bool | None = Field(default=None, alias="cookie_secure")
    # Session lifetime (days) — drives both the auth_sessions row TTL and the
    # cookie Max-Age. Shortened from the original 30 to 14: long enough that a
    # daily-driver trader isn't re-logging-in constantly, short enough to bound
    # the blast radius of a stolen session token. Override SESSION_TTL_DAYS in
    # .env per deployment.
    session_ttl_days: int = 14
    dev_user_email: str = "dev@local"
    # No password is committed to source. If left blank, the one-time
    # legacy-DB backfill mints a random one (the dev user is a migration
    # artifact, not a login). Set DEV_USER_PASSWORD in .env only if you need
    # to sign in as it after adopting a pre-multi-user database.
    dev_user_password: str = ""

    # ---------------------------------------------------------------------
    # Stripe (OPT-IN). Payments go live ONLY when stripe_secret_key is set;
    # otherwise the app keeps the free placeholder purchase flow untouched.
    # Per-tier prices are Stripe Price IDs (price_…) — NO dollar amounts are
    # hardcoded anywhere; pricing is owned by the Stripe dashboard, and the
    # paid amount is read back from the completed Checkout Session. A tier
    # whose price ID is blank can't be checked out (503 "pricing not
    # configured") even when Stripe is otherwise enabled.
    stripe_secret_key: str = ""
    stripe_webhook_secret: str = ""
    stripe_price_50k: str = ""
    stripe_price_100k: str = ""
    stripe_price_150k: str = ""
    # Where Stripe redirects after Checkout. Frontend reads ?purchase=… to
    # toast the result. Override per-deployment.
    stripe_success_url: str = "http://localhost:5173/dashboard?purchase=success"
    stripe_cancel_url: str = "http://localhost:5173/dashboard?purchase=cancelled"

    # ---------------------------------------------------------------------
    # Auth brute-force throttle. Per-IP, per-endpoint fixed window: at most
    # `attempts` signin/signup tries per `window_s` seconds before a 429.
    # Set attempts <= 0 to disable (e.g. behind an upstream rate limiter).
    auth_rate_limit_attempts: int = 10
    auth_rate_limit_window_s: int = 60

    # ---------------------------------------------------------------------
    # Closed launch. With signup_require_invite ON, POST /api/auth/signup
    # demands a valid, unredeemed invite code (minted by an admin under
    # /api/admin/invites) — the gate for an invite-only deployment. OFF by
    # default so local dev and the test suite keep their open signup; a
    # closed deployment sets SIGNUP_REQUIRE_INVITE=1. A code supplied when
    # the gate is OFF is still validated and redeemed, so the audit trail
    # never silently drops one.
    signup_require_invite: bool = False
    # Default TTL the admin mint form pre-fills, in days. 0 = never expires.
    invite_default_ttl_days: float = 14.0

    # ---------------------------------------------------------------------
    # Operator back office (P0 wave, 2026-07). Emails auto-promoted to the
    # admin role at signin — the bootstrap path for the first operator seat
    # (afterwards admins can promote/demote via /api/admin).
    admin_emails: tuple[str, ...] = ()

    # ---------------------------------------------------------------------
    # Payout adjudication. auto-approve preserves the simulated review desk
    # for clean sim deployments: a 'requested' payout older than the window
    # approves unattended. Flip PAYOUT_AUTO_APPROVE=0 to require a human on
    # every request (the real-firm posture). The window is the legacy
    # PAYOUT_REVIEW_WINDOW_H, now owned here.
    # PROD-SAFE BY DEFAULT, like cookie_secure above: left unset it follows
    # app_env — OFF in production (a human adjudicates every payout), ON in
    # development so the sim desk and the test suite keep today's behaviour.
    # An explicit PAYOUT_AUTO_APPROVE always wins, in either direction; the
    # property below resolves it, and services.preflight warns when a
    # production deployment has explicitly turned it back on. This is real
    # money leaving on a timer — the default should have to be chosen, not
    # inherited.
    payout_auto_approve_override: bool | None = Field(
        default=None, alias="payout_auto_approve"
    )
    payout_review_window_h: float = 1.0

    # Payout-request prerequisites (each individually toggleable so tests and
    # sim demos can relax them): KYC verified, a tax profile on file, and a
    # default payout method on file.
    payout_require_kyc: bool = True
    payout_require_tax_profile: bool = True
    payout_require_method: bool = True

    # Simulated KYC provider: when True a submission auto-decides instantly
    # (verified unless the declared country is blocked below); when False the
    # submission parks at 'pending' for an admin decision.
    # Also PROD-SAFE BY DEFAULT (see payout_auto_approve above): unset means
    # OFF in production, so a submission parks at 'pending' for a human
    # instead of being rubber-stamped by a simulated provider.
    kyc_auto_verify_override: bool | None = Field(
        default=None, alias="kyc_auto_verify"
    )
    # ISO-3166 alpha-2 country codes refused at KYC (OFAC-comprehensive
    # jurisdictions). Checked case-insensitively.
    ofac_blocked_countries: tuple[str, ...] = ("CU", "IR", "KP", "SY", "RU", "BY")

    # ---------------------------------------------------------------------
    # Transactional email. "console" logs the rendered mail (dev default —
    # nothing leaves the box); "smtp" sends via the server below. The outbox
    # job retries a failed send up to mail_max_attempts times.
    mail_provider: str = "console"
    mail_from: str = "Trade Desk <no-reply@tradedesk.local>"
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_username: str = ""
    smtp_password: str = ""
    smtp_starttls: bool = True
    # Implicit TLS / SMTPS — the socket is wrapped before the greeting,
    # which is what port 465 relays expect. Providers split roughly evenly
    # between this and STARTTLS on 587; set SMTP_SSL=1 (and port 465) for
    # the former. Mutually exclusive with smtp_starttls in practice.
    smtp_ssl: bool = False
    mail_max_attempts: int = 5
    # Base URL the frontend is served from — used to build links in emails
    # (password reset, payout status).
    frontend_base_url: str = "http://localhost:5173"
    # Password-reset token lifetime (hours).
    password_reset_ttl_h: float = 2.0

    # ---------------------------------------------------------------------
    # Backups. Nightly SQLite .backup into backup_dir, pruning files older
    # than the retention window. No-op on non-SQLite databases.
    backup_dir: str = str(PROJECT_ROOT / "data" / "backups")
    backup_retention_days: int = 14
    # Escape hatch for the pre-tier legacy wipe in database.py: by default a
    # trades table MISSING the 'tier' column now refuses to boot (it is almost
    # always a restored pre-tier backup, and the old behavior deleted every
    # trade row). Set ALLOW_LEGACY_TRADE_WIPE=1 only for a genuine one-time
    # adoption of a pre-tier database.
    allow_legacy_trade_wipe: bool = False

    # ---------------------------------------------------------------------
    # OFFSITE backup replication. backup_dir lives on the SAME volume as the
    # live SQLite database (both default under PROJECT_ROOT/data, /app/data
    # in the image), so local backups share their failure domain with the
    # thing they protect. Setting a provider mirrors each nightly snapshot to
    # object storage. "none" (default) = off, nothing is sent anywhere;
    # "s3" = any S3-compatible bucket (Cloudflare R2, Backblaze B2, MinIO,
    # AWS S3) — see services/offsite_backup.py and docs/DEPLOYMENT.md.
    #
    # With provider="s3" an INCOMPLETE configuration is a loud error, not a
    # skip: a backup that silently stopped replicating is the exact failure
    # this exists to catch.
    backup_offsite_provider: str = "none"
    backup_s3_bucket: str = ""
    # R2 requires the literal "auto"; AWS and B2 need their real region.
    backup_s3_region: str = "auto"
    # Empty = bare AWS S3 (virtual-hosted addressing). Set to the provider's
    # endpoint (e.g. https://<account>.r2.cloudflarestorage.com) for anything
    # else, which switches to path-style addressing.
    backup_s3_endpoint_url: str = ""
    backup_s3_prefix: str = "backups/"
    backup_s3_access_key_id: str = ""
    backup_s3_secret_access_key: str = ""
    backup_offsite_timeout_s: float = 60.0
    # Remote retention. 0 (default) = the app NEVER deletes an offsite
    # object; prefer a bucket lifecycle rule, whose blast radius is not this
    # process. A positive value enables app-side pruning, which additionally
    # always keeps the newest few snapshots (see prune_remote).
    backup_offsite_retention_days: int = 0

    # ---------------------------------------------------------------------
    # Trading-universe + quote-quality enforcement on the OPEN path.
    # enforce_tradeable_universe gates opens to zero_dte_universe (minus any
    # platform_state symbol bans); the quote-quality gate refuses option legs
    # whose NBBO is unusable (mid below the floor, or spread wider than the
    # ratio × mid — a market no one actually quotes).
    enforce_tradeable_universe: bool = True
    min_option_mid: float = 0.05
    max_option_spread_ratio: float = 1.0

    # ---------------------------------------------------------------------
    # Single-container deploy: when set to the built frontend's dist
    # directory, the backend serves the SPA (static assets + index.html
    # fallback for client routes). Empty (default) = API-only, frontend on
    # the Vite dev server. Set SERVE_FRONTEND_DIR=/app/frontend/dist in the
    # Docker image.
    serve_frontend_dir: str = ""

    # ---------------------------------------------------------------------
    # Per-USER throttle on the FINANCIAL endpoints (payout request, account
    # activation, combine purchase / Stripe checkout). Keyed by user_id +
    # endpoint scope (not IP) — these are authenticated actions, so the signed-in
    # user is the right subject and one user can't be blocked by another behind
    # the same NAT/proxy. A funded-account holder never needs to fire these more
    # than a handful of times a minute, so the default is deliberately tight to
    # blunt double-click / scripted abuse without ever tripping real use. Set
    # attempts <= 0 to disable.
    financial_rate_limit_attempts: int = 5
    financial_rate_limit_window_s: int = 60

    # ---------------------------------------------------------------------
    # 0DTE-eligible universe — the ONLY symbols Trade Desk allows users
    # to open positions on. Same-day-expiry options are limited to a
    # narrow set in practice; this allowlist gates the symbol search and
    # the chain panel so users can't pick a ticker they won't be able to
    # trade.
    #
    # Current contents (May 2026): index ETFs that list daily expirations
    # on Alpaca's options feed.
    #   - SPY  S&P 500 SPDR — daily 0DTE
    #   - QQQ  Nasdaq-100 — daily 0DTE
    #   - IWM  Russell 2000 — daily 0DTE
    #
    # Index options (SPX, XSP, NDX) are intentionally omitted: Alpaca's
    # free options feed does not list cash-settled index options, so
    # those contracts wouldn't actually be tradeable through this app.
    # Add them here when/if the data source supports them.
    #
    # Edit this list as the market changes — adding a name turns it on
    # everywhere (search, chain, opens) with no other code changes.
    zero_dte_universe: tuple[str, ...] = ("SPY", "QQQ", "IWM")

    # ---------------------------------------------------------------------
    # Demo seed used to auto-populate the journal on a fresh DB. OFF by
    # default — the app starts empty so users build their own paper-trade
    # history. Set SEED_TRADES=1 in .env (or environment) to opt back in
    # for demos / regression. The seed file (jobs/seed_trades.py) is
    # kept on disk regardless; this just gates when it runs.
    seed_trades: bool = False

    # Hardcoded universe for Phase 1. Expand later via a tickers table or env var.
    watchlist_universe: tuple[str, ...] = (
        "NVDA", "TSLA", "AAPL", "AMD", "MSFT", "META", "AMZN", "GOOGL",
        "PLTR", "SMCI", "BA", "INTC", "F", "QQQ", "SPY",
    )

    # Trade Desk Phase 0 — names the symbol search autocomplete suggests
    # and the prewarm job keeps warm. Superset of watchlist_universe with
    # added high-volume optionable names so a demo viewer can type almost
    # any liquid ticker and land it cached. The hot subset (Hot Now +
    # Unusual Options) still warms FIRST inside the per-cycle budget so
    # most-clicked names are always prioritized.
    prewarm_liquid_universe: tuple[str, ...] = (
        # Mega-cap tech (also in watchlist)
        "AAPL", "MSFT", "NVDA", "TSLA", "AMD", "META", "AMZN", "GOOGL",
        "INTC", "MU", "AVGO", "CRM", "ORCL", "ADBE",
        # Index ETFs
        "SPY", "QQQ", "IWM",
        # Consumer / media
        "NFLX", "DIS", "SHOP", "UBER", "ABNB", "SNAP",
        # EVs + autos
        "RIVN", "LCID", "NIO", "F", "GM",
        # Banks / financials
        "JPM", "BAC", "GS", "MS", "C", "WFC", "V", "MA",
        # Speculative + retail favorites
        "PLTR", "SOFI", "COIN", "SMCI", "BA",
        # Energy
        "XOM", "CVX",
        # Retail / staples
        "WMT", "COST", "HD", "LOW", "KO", "PEP", "MCD",
        # Healthcare / pharma
        "JNJ", "PFE", "LLY", "UNH", "ABBV",
        # Apparel / brands
        "NKE", "SBUX",
    )

    # Names used for ML training data (Phase 6+). Most don't appear in the
    # watchlist UI. SPY/QQQ are also included here so the LSTM can predict
    # vol for the indices themselves — users want to see the market regime.
    # ETFs are skipped during the earnings backfill (no earnings prints).
    training_universe: tuple[str, ...] = (
        # Index ETFs (vol forecasting, no earnings)
        "SPY", "QQQ",
        # Mega-cap stable
        "JNJ", "PG", "KO", "WMT", "V", "MA", "COST", "UNH",
        # Mega-cap volatile
        "TSLA", "NFLX", "CRM", "ADBE", "ORCL",
        # Mid-cap with active options
        "COIN", "RBLX", "SNAP", "U", "RIVN", "AFRM",
        # Financials
        "JPM", "BAC", "GS", "MS", "C", "WFC",
        # Healthcare / Pharma
        "PFE", "MRK", "LLY", "ABBV", "BMY",
        # Industrials / Consumer
        "CAT", "DE", "HD", "LOW", "NKE", "SBUX",
    )

    @property
    def is_production(self) -> bool:
        return self.app_env.strip().lower() in {"production", "prod"}

    @property
    def cookie_secure(self) -> bool:
        """Effective Secure flag for the session cookie.

        An explicit COOKIE_SECURE in the environment always wins; otherwise it
        follows the deployment environment — Secure in production (cookie never
        leaves over plain HTTP), open in development for local HTTP."""
        if self.cookie_secure_override is not None:
            return self.cookie_secure_override
        return self.is_production

    @property
    def payout_auto_approve(self) -> bool:
        """Effective payout auto-approval. Explicit env wins; otherwise OFF in
        production (a human on every payout) and ON in development."""
        if self.payout_auto_approve_override is not None:
            return self.payout_auto_approve_override
        return not self.is_production

    @property
    def kyc_auto_verify(self) -> bool:
        """Effective KYC auto-verification. Explicit env wins; otherwise OFF in
        production (submissions park at 'pending') and ON in development."""
        if self.kyc_auto_verify_override is not None:
            return self.kyc_auto_verify_override
        return not self.is_production

    @property
    def session_ttl(self) -> timedelta:
        """Session lifetime as a timedelta (from session_ttl_days)."""
        return timedelta(days=self.session_ttl_days)

    @property
    def per_contract_fee(self) -> float:
        """Total per-contract, per-side transaction cost: commission + the
        blended regulatory/exchange fee. The single number every commission
        helper folds into cost basis / realized P&L (entry and exit)."""
        return self.commission_per_contract + self.regulatory_fee_per_contract


settings = Settings()
