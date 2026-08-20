import asyncio
import json
import logging
import os
import time
import uuid
from contextlib import asynccontextmanager
from contextvars import ContextVar
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
from fastapi import Depends, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from config import settings
from database import get_session, init_db
from services.job_runs import run_logged
from services.rate_limit import _client_ip, global_limiter
from jobs.backup_db import backup_db, backup_db_if_stale
from jobs.collect_options_chain import collect_options_chain
from jobs.notify_events import notify_events
from jobs.prewarm_hot_tickers import prewarm_hot_tickers
from jobs.refresh_watchlist import refresh_watchlist
from jobs.seed_trades import seed_example_trades
from jobs.send_outbox import send_outbox
from jobs.evaluate_alerts import evaluate_alerts
from jobs.monitor_orders import monitor_orders
from jobs.renew_combines import renew_combines
from jobs.settle_combines import settle_combines
from routers.ticker import MarketDataDegraded
from routers import account as account_router
from routers import admin as admin_router
from routers import alerts as alerts_router
from routers import analytics as analytics_router
from routers import auth as auth_router
from routers import combines as combines_router
from routers import calendar as calendar_router
from routers import journal as journal_router
from routers import journal_media as journal_media_router
from routers import legal as legal_router
from routers import market as market_router
from routers import news as news_router
from routers import notifications as notifications_router
from routers import payments as payments_router
from routers import support as support_router
from routers import ticker as ticker_router
from routers import ticker_search as ticker_search_router
from routers import user_browse as user_browse_router
from routers import verification as verification_router
from routers import watchlist as watchlist_router
from routers import zerodte as zerodte_router

# Per-request correlation id. Set by the request-id middleware on each
# inbound request and read by the log filter below so EVERY log line emitted
# while handling a request carries its id — even from deep service code that
# never sees the Request object. Defaults to "-" outside a request (startup,
# scheduler jobs, shutdown).
request_id_ctx: ContextVar[str] = ContextVar("request_id", default="-")


class RequestIdFilter(logging.Filter):
    """Inject the current request id onto every record as `request_id` so both
    the JSON and text formatters can reference it. A filter (not a formatter)
    is used so the field is present on records from any logger in the tree."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = request_id_ctx.get()
        return True


class JsonFormatter(logging.Formatter):
    """One JSON object per line: timestamp (UTC ISO-8601), level, logger,
    message, request_id, plus the exception text when present. Stable key set
    so a log aggregator can index on them."""

    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "timestamp": datetime.fromtimestamp(
                record.created, tz=timezone.utc
            ).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "request_id": getattr(record, "request_id", "-"),
        }
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


def _configure_logging() -> None:
    """Install a single root handler with either the JSON formatter (LOG_JSON=1
    — for prod log aggregators) or the human-readable text format (default —
    local dev). Both carry the request id. Replaces the previous
    logging.basicConfig so request-correlation works everywhere."""
    handler = logging.StreamHandler()
    handler.addFilter(RequestIdFilter())
    if settings.log_json:
        handler.setFormatter(JsonFormatter())
    else:
        handler.setFormatter(
            logging.Formatter(
                "%(asctime)s %(levelname)s [%(name)s] "
                "(req=%(request_id)s) %(message)s"
            )
        )
    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(settings.log_level)


_configure_logging()
log = logging.getLogger("dashboard")

# Wall-clock process start, for /health's scheduler-staleness grace window.
_PROCESS_STARTED_AT = time.time()


_SCRUB_HEADERS = frozenset({"cookie", "set-cookie", "authorization", "x-api-key"})


def _sentry_scrub(event: Any, _hint: Any) -> Any:
    """Strip credential-bearing headers before an event leaves the process.

    sentry-sdk already omits most PII while send_default_pii is False, but
    this app carries session cookies, KYC legal names, tax profiles and
    payout destinations — so the scrub is explicit and independent of that
    default rather than trusting it not to change. Belt and braces: an
    error report is never worth leaking a live session token into a
    third-party dashboard.
    """
    headers = (event.get("request") or {}).get("headers")
    if isinstance(headers, dict):
        for key in list(headers):
            if key.lower() in _SCRUB_HEADERS:
                headers[key] = "[scrubbed]"
    return event


def _init_sentry() -> None:
    """Initialise Sentry error tracking — a clean no-op when unconfigured.

    Skips entirely when `settings.sentry_dsn` is blank (the default), so a
    dev box / CI never phones home. Also degrades gracefully if the SDK
    isn't installed: logs and moves on rather than crashing startup. The
    FastAPI integration is auto-enabled by sentry-sdk[fastapi] on init.

    Scheduled-job failures arrive here for free: services/job_runs.run_logged
    re-raises, APScheduler logs the exception at ERROR, and the SDK's default
    logging integration turns ERROR records into events. That is the path
    that makes a 3am settlement or backup failure visible at all, so
    tests/test_sentry_wiring.py pins it.

    `release` defaults to Fly's FLY_IMAGE_REF when SENTRY_RELEASE is unset —
    without some release marker every event looks like the same build and a
    fresh regression is indistinguishable from an old bug.
    """
    if not settings.sentry_dsn:
        log.info("sentry_dsn unset; error tracking disabled")
        return
    try:
        import sentry_sdk
    except ImportError:
        log.warning("SENTRY_DSN set but sentry-sdk not installed; skipping")
        return
    release = settings.sentry_release or os.environ.get("FLY_IMAGE_REF") or None
    sentry_sdk.init(
        dsn=settings.sentry_dsn,
        environment=settings.sentry_environment,
        traces_sample_rate=settings.sentry_traces_sample_rate,
        release=release,
        # Which machine emitted it — Fly runs one, but a restart loop is much
        # easier to read when the events are attributable.
        server_name=os.environ.get("FLY_MACHINE_ID") or None,
        # Never attach user identity / request bodies automatically.
        send_default_pii=False,
        before_send=_sentry_scrub,
    )
    log.info(
        "sentry initialised (env=%s release=%s)",
        settings.sentry_environment,
        release or "unset",
    )


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup is fast by design.

    Anything that hits the network — watchlist refresh, hot-ticker
    prewarm, earnings calendar fetch — runs off the critical path.
    Previously these were called synchronously inside lifespan and
    blocked the server from accepting traffic for ~3 minutes; that
    looked like a hang. They're now scheduled as background tasks so
    "Application startup complete" fires within a few seconds.

    Endpoints already degrade gracefully against empty data (watchlist
    returns empty buckets, chart returns 404 with a clean message, etc.)
    so the frontend's existing loading states render correctly until
    the background warm completes.
    """
    # Error tracking first so failures during the rest of startup are
    # captured. No-op when SENTRY_DSN is unset (the default).
    _init_sentry()

    init_db()

    # Demo seed for the Trade Desk journal — OFF by default. The app
    # starts with an empty trades table so users build their own paper-
    # trade history. Set SEED_TRADES=1 to opt back in for demos.
    if settings.seed_trades:
        try:
            seed_example_trades()
        except Exception:  # noqa: BLE001
            log.exception("startup seed_example_trades failed")
    else:
        log.info("seed_trades=False; skipping demo seed (set SEED_TRADES=1 to enable)")

    # misfire_grace_time bounds how far past a missed scheduled time a
    # job will still be allowed to fire. Without it, a tick that misses
    # its slot (e.g. because the previous run ran long against a slow
    # Alpaca/Finnhub call) is silently skipped indefinitely — the symptom
    # is "the scheduler stops working" until restart. 30s gives us a
    # one-half-cycle window: missed by up to 30s → re-fire; older than
    # that → drop. Paired with max_instances=1 + coalesce=True so a
    # missed run never stacks behind a still-running one.
    _SCHED_GRACE = 30
    _SCHED_TZ = ZoneInfo("America/New_York")

    def _sweep_cache() -> None:
        from services.cache import cache

        removed = cache.sweep()
        if removed:
            log.info("cache sweep: dropped %d expired entries", removed)

    scheduler = BackgroundScheduler(timezone="America/New_York")
    scheduler.add_job(
        run_logged("refresh_watchlist", refresh_watchlist),
        trigger=IntervalTrigger(seconds=60),
        id="refresh_watchlist",
        max_instances=1,
        coalesce=True,
        misfire_grace_time=_SCHED_GRACE,
    )
    # Stagger the second 60s job by ~25s. Both refresh_watchlist and
    # prewarm_hot_tickers fan out per-symbol Alpaca calls on the SINGLE
    # account key; firing them in phase doubled the burst and collided on
    # the quota (a big driver of the 429 cascade behind the stuck-loading
    # chart). An IntervalTrigger with start_date in the future offsets the
    # whole cadence so the two jobs interleave instead of overlapping.
    _PREWARM_OFFSET_S = 25
    scheduler.add_job(
        run_logged("prewarm_hot_tickers", prewarm_hot_tickers),
        trigger=IntervalTrigger(
            seconds=60,
            start_date=datetime.now(_SCHED_TZ) + timedelta(seconds=_PREWARM_OFFSET_S),
        ),
        id="prewarm_hot_tickers",
        max_instances=1,
        coalesce=True,
        misfire_grace_time=_SCHED_GRACE,
    )
    scheduler.add_job(
        run_logged("collect_options_chain", collect_options_chain),
        trigger=CronTrigger(
            day_of_week="mon-fri",
            hour=16,
            minute=30,
            timezone="America/New_York",
        ),
        id="collect_options_chain",
        max_instances=1,
        coalesce=True,
        misfire_grace_time=_SCHED_GRACE,
    )
    # Combine settlement / auto-fail / auto-fund every 5 minutes so the
    # rules fire on a clock, not only when account state is read. DB+CPU
    # only (no network), so the short interval is cheap; idempotent.
    scheduler.add_job(
        run_logged("settle_combines", settle_combines),
        trigger=IntervalTrigger(minutes=5),
        id="settle_combines",
        max_instances=1,
        coalesce=True,
        misfire_grace_time=_SCHED_GRACE,
    )
    # Billing renewal — daily boundary pass over paid_through: auto-renew
    # (simulated rebill + banked reset credit) or archive combines canceled
    # at period end. Idempotent + multi-period-aware, so a missed day
    # self-heals on the next run.
    scheduler.add_job(
        run_logged("renew_combines", renew_combines),
        trigger=CronTrigger(hour=0, minute=15, timezone="America/New_York"),
        id="renew_combines",
        max_instances=1,
        coalesce=True,
        misfire_grace_time=_SCHED_GRACE,
    )
    # Order monitor — fill working limit/stop orders + auto-close SL/TP
    # brackets during market hours. Cadence is config-driven (default 5s —
    # the practical floor for the polled data plane; see config). No-ops out
    # of session.
    scheduler.add_job(
        run_logged("monitor_orders", monitor_orders),
        trigger=IntervalTrigger(seconds=settings.order_monitor_interval_s),
        id="monitor_orders",
        max_instances=1,
        coalesce=True,
        misfire_grace_time=_SCHED_GRACE,
    )
    # Price alerts — server-side evaluation every 30s so alerts fire with no
    # tab open (the frontend's 15s poll remains the instant-toast path). One
    # batched quote fetch across every active alert symbol; trips land in the
    # notification bell + email outbox.
    scheduler.add_job(
        run_logged("evaluate_alerts", evaluate_alerts),
        trigger=IntervalTrigger(seconds=30),
        id="evaluate_alerts",
        max_instances=1,
        coalesce=True,
        misfire_grace_time=_SCHED_GRACE,
    )
    # Cache sweep — TTLCache expires only on same-key reads, so date-rotated
    # keys (bars:{sym}:{tf}:{date}, …) leak until swept. Cheap; hourly is fine.
    scheduler.add_job(
        _sweep_cache,
        trigger=IntervalTrigger(hours=1),
        id="sweep_cache",
        max_instances=1,
        coalesce=True,
        misfire_grace_time=_SCHED_GRACE,
    )
    # P0 wave (2026-07): transactional-email outbox drain (30s), lifecycle
    # notifier tailing combine_events (60s), nightly DB backup with retention
    # (02:30 ET, off trading hours and clear of the 00:15 billing run).
    scheduler.add_job(
        run_logged("send_outbox", send_outbox),
        trigger=IntervalTrigger(seconds=30),
        id="send_outbox",
        max_instances=1,
        coalesce=True,
        misfire_grace_time=_SCHED_GRACE,
    )
    scheduler.add_job(
        run_logged("notify_events", notify_events),
        trigger=IntervalTrigger(seconds=60),
        id="notify_events",
        max_instances=1,
        coalesce=True,
        misfire_grace_time=_SCHED_GRACE,
    )
    scheduler.add_job(
        run_logged("backup_db", backup_db),
        trigger=CronTrigger(hour=2, minute=30, timezone="America/New_York"),
        id="backup_db",
        max_instances=1,
        coalesce=True,
        misfire_grace_time=_SCHED_GRACE,
    )
    scheduler.start()
    log.info("scheduler started")

    # Background warm — kick off both jobs in a worker thread so the
    # lifespan returns immediately. The jobs themselves are sync; we run
    # them via to_thread so they don't block the event loop, and so the
    # async-running-loop landmine in prewarm doesn't fire.
    async def _background_warm() -> None:
        log.info("background warm: starting refresh_watchlist + prewarm")
        # Billing CATCH-UP on boot. The renew_combines cron only fires at
        # 00:15 ET; with an in-memory jobstore a process that is down at that
        # instant (a dev box, a market-hours-only host) drops the run and never
        # rebills — subscriptions drift past-due while staying tradeable. The
        # job is idempotent + multi-period-aware, so running it once at startup
        # settles every boundary missed while the app was down.
        try:
            await asyncio.to_thread(renew_combines)
        except Exception:  # noqa: BLE001
            log.exception("startup billing catch-up (renew_combines) failed")
        # Backup CATCH-UP on boot — same in-memory-jobstore gap as billing:
        # the 02:30 ET backup cron is dropped on a host that is down at that
        # instant, so a non-24/7 box would never back up (and never prune the
        # JobRun table). Staleness-gated, so a 24/7 host that already ran the
        # cron overnight no-ops instead of writing a redundant boot backup.
        try:
            await asyncio.to_thread(run_logged("backup_db", backup_db_if_stale))
        except Exception:  # noqa: BLE001
            log.exception("startup backup catch-up (backup_db_if_stale) failed")
        try:
            await asyncio.to_thread(refresh_watchlist, force=True)
        except Exception:  # noqa: BLE001
            log.exception("background refresh_watchlist failed")
        try:
            await asyncio.to_thread(prewarm_hot_tickers, force=True)
        except Exception:  # noqa: BLE001
            log.exception("background prewarm_hot_tickers failed")
        log.info("background warm: complete")

    warm_task = asyncio.create_task(_background_warm())
    log.info("startup complete; warm in background")

    # WS6 — real-time data-feed consumer. Started ONLY when the flag is on
    # (default OFF → this whole block is skipped and nothing changes). When
    # on, it runs the WebSocket stream + subscribes the watchlist universe,
    # writing into the in-memory store that get_quotes/get_bars read first.
    # `get_realtime_feed()` returns the process-wide singleton the read-through
    # also consults, so no wiring is needed beyond starting run().
    feed_task = None
    feed = None
    if settings.realtime_feed_enabled:
        from services.realtime_feed import get_realtime_feed

        feed = get_realtime_feed()
        feed.subscribe(settings.watchlist_universe)

        async def _run_feed() -> None:
            log.info(
                "realtime feed: starting stream consumer over %d symbols",
                len(settings.watchlist_universe),
            )
            try:
                await feed.run()  # blocks; internal reconnect loop
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001
                log.exception("realtime feed consumer crashed")

        feed_task = asyncio.create_task(_run_feed())
        log.info("realtime feed consumer task started (REALTIME_FEED_ENABLED=1)")
    else:
        log.info(
            "realtime_feed_enabled=False; stream consumer not started "
            "(read paths use REST polling)"
        )

    try:
        yield
    finally:
        # Cancel any still-running warm so shutdown is fast too.
        warm_task.cancel()
        if feed is not None:
            feed.stop()
        if feed_task is not None:
            feed_task.cancel()
        scheduler.shutdown(wait=False)
        log.info("scheduler stopped")


app = FastAPI(title="Options Dashboard", version="0.1.0", lifespan=lifespan)


@app.exception_handler(MarketDataDegraded)
async def _market_data_degraded_handler(_request, exc: MarketDataDegraded):
    """Render the typed degraded body the frontend keys on. Without this,
    FastAPI's default HTTPException handler would emit a bare
    `{"detail": ...}` — the richer `{"error": "market_data_unavailable"}`
    shape lets api.ts detect the degraded state distinctly from a 404/500."""
    return exc.to_response()

app.add_middleware(
    CORSMiddleware,
    # Allowlist from settings (env CORS_ALLOW_ORIGINS), defaulting to the
    # Vite dev server. Session-cookie auth means origins must stay an
    # explicit list (never "*") once credentials are allowed.
    allow_origins=list(settings.cors_allow_origins),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def _security_headers(request: Request, call_next):
    """Baseline security response headers for the authenticated SPA.

    - `X-Frame-Options: DENY` + `frame-ancestors 'none'` — the app can't be
      framed, so the session-cookie UI can't be clickjacked.
    - `X-Content-Type-Options: nosniff` — the browser won't MIME-sniff a
      response into an executable type (defense in depth for the
      user-uploaded screenshot bytes served by journal_media).
    - `Referrer-Policy: same-origin` — don't leak internal URLs cross-site.
    - HSTS only in production (never on plain-HTTP dev, where it would pin
      localhost to HTTPS).
    """
    response = await call_next(request)
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("Referrer-Policy", "same-origin")
    response.headers.setdefault("Content-Security-Policy", "frame-ancestors 'none'")
    if settings.is_production:
        response.headers.setdefault(
            "Strict-Transport-Security", "max-age=31536000; includeSubDomains"
        )
    return response


# Paths exempt from the global throttle: health/readiness probes must never
# be 429'd (a load balancer would mark the box unhealthy and pull it).
_RATE_LIMIT_EXEMPT_PATHS = frozenset({"/health"})


@app.middleware("http")
async def _global_rate_limit(request: Request, call_next):
    """Coarse per-IP throttle across EVERY endpoint (not just auth).

    A runaway client or basic abuse gets a 429 with Retry-After before it
    touches a route. No-op when the limiter is disabled
    (global_rate_limit_attempts <= 0) or for exempt probe paths. The
    auth-specific brute-force limiter still applies on top for /api/auth."""
    if global_limiter.enabled and request.url.path not in _RATE_LIMIT_EXEMPT_PATHS:
        allowed, retry_after = global_limiter.hit(f"global:{_client_ip(request)}")
        if not allowed:
            return JSONResponse(
                status_code=429,
                content={"detail": "rate limit exceeded — slow down"},
                headers={"Retry-After": str(int(retry_after) + 1)},
            )
    return await call_next(request)


# Header clients/proxies use to carry a correlation id. Honor an inbound one
# (so a request traced from the edge keeps its id) and generate one otherwise.
_REQUEST_ID_HEADER = "X-Request-ID"


@app.middleware("http")
async def _request_id(request: Request, call_next):
    """Assign every request a correlation id, bind it to the logging context
    for the duration of the request, and echo it back as `X-Request-ID`.

    Added last → outermost middleware, so the id is set before the rate-limit
    layer runs and the response header is attached even to a 429 it returns.
    The ContextVar token is reset in finally so ids never leak across the
    worker's reused tasks. A slow request (>1s) is logged at WARNING with its
    timing so ops can spot latency without a separate APM."""
    incoming = request.headers.get(_REQUEST_ID_HEADER)
    rid = incoming or uuid.uuid4().hex
    token = request_id_ctx.set(rid)
    # Expose on request.state so handlers/exception handlers can read it.
    request.state.request_id = rid
    start = time.perf_counter()
    try:
        response = await call_next(request)
        response.headers[_REQUEST_ID_HEADER] = rid
        return response
    finally:
        elapsed_ms = (time.perf_counter() - start) * 1000.0
        if elapsed_ms > 1000.0:
            log.warning(
                "slow request %s %s took %.0fms",
                request.method,
                request.url.path,
                elapsed_ms,
            )
        # Reset last so the slow-request log above still carries this id.
        request_id_ctx.reset(token)


app.include_router(watchlist_router.router)
app.include_router(ticker_router.router)
app.include_router(calendar_router.router)
app.include_router(market_router.router)
app.include_router(news_router.router)
app.include_router(journal_router.router)
app.include_router(journal_media_router.router)  # WS4: screenshot upload/serve
app.include_router(analytics_router.router)
app.include_router(zerodte_router.router)
app.include_router(account_router.router)
app.include_router(auth_router.router)
app.include_router(combines_router.router)
app.include_router(payments_router.router)
app.include_router(ticker_search_router.router)
app.include_router(user_browse_router.router_user)
app.include_router(user_browse_router.router_ticker)
app.include_router(alerts_router.router)  # WS6: price/earnings/fill alerts
# P0 wave (2026-07): operator back office, legal consent, payout
# prerequisites (KYC/tax/methods), support tickets, notification center.
app.include_router(admin_router.router)
app.include_router(legal_router.router)
app.include_router(verification_router.router)
app.include_router(support_router.router)
app.include_router(notifications_router.router)


def _scheduler_health(session) -> str:
    """"ok" | "stale" | "unknown" | "off" — is the in-process scheduler alive?

    THE failure this exists for: the process answers HTTP perfectly while the
    APScheduler thread is dead. Liveness and a `SELECT 1` both pass, so an
    uptime check goes green while billing renewals, combine settlement, EOD
    settlement and the nightly backup have silently stopped. The only
    evidence available from outside is that nothing has written a JobRun row
    in a while.

    Two deliberate non-alarms:
      * "unknown" when no JobRun rows exist at all — a fresh database, not a
        fault. Reporting stale here would 503 every first boot.
      * a startup grace of one full window: the process must have been up
        LONGER than the staleness window before silence can mean anything.
        Without it a restart inside the window looks like a dead scheduler.
    """
    window = settings.health_scheduler_stale_s
    if window <= 0:
        return "off"
    if (time.time() - _PROCESS_STARTED_AT) < window:
        return "ok"
    try:
        from sqlalchemy import func, select

        from models.job_run import JobRun

        newest = session.execute(select(func.max(JobRun.started_at))).scalar()
    except Exception:  # noqa: BLE001 — a health probe must never raise
        log.exception("/health scheduler check failed")
        return "unknown"
    if newest is None:
        return "unknown"
    # started_at comes back tz-aware — database.UTCDateTime stamps UTC on
    # every result — so .timestamp() is exact and no tz constant is needed.
    age = time.time() - newest.timestamp()
    return "ok" if age <= window else "stale"


@app.get("/health")
def health(session: Session = Depends(get_session)) -> JSONResponse:
    """Liveness + DB readiness + scheduler liveness.

    A healthy 200 means the app can reach its database AND the in-process
    scheduler has run something recently — not merely that the process is up.
    Either failing → 503 "degraded" so a load balancer pulls the box, Fly
    restarts the machine (which is the right remediation for a dead
    scheduler thread), and an external uptime check actually fires. Exempt
    from the global rate limit (see _RATE_LIMIT_EXEMPT_PATHS).

    Intentionally says nothing about WHICH job is late: this endpoint is
    unauthenticated. Job-level detail lives behind the admin jobs view.
    """
    from sqlalchemy import text

    db_ok = True
    try:
        session.execute(text("SELECT 1"))
    except Exception:  # noqa: BLE001
        db_ok = False
        log.exception("/health DB check failed")

    # Same session as the probe above: one connection per health check, and
    # it honours the get_session dependency override (a self-built
    # SessionLocal would silently read a DIFFERENT database under test).
    scheduler = _scheduler_health(session)
    ok = db_ok and scheduler != "stale"
    body = {
        "status": "ok" if ok else "degraded",
        "database": "up" if db_ok else "down",
        "scheduler": scheduler,
    }
    return JSONResponse(status_code=200 if ok else 503, content=body)


def _safe_spa_file(dist: "Path", spa_path: str):
    """Resolve a SPA request path to a real file INSIDE `dist`, or None.

    SECURITY: the returned file is guaranteed to sit within `dist`. A naive
    `".." not in spa_path` substring check is insufficient — a percent-encoded
    leading slash (`GET /%2Fetc%2Fpasswd`) arrives as an ABSOLUTE path with no
    "..", and `dist / "/abs"` discards the base in pathlib, which would turn
    the SPA fallback into an unauthenticated arbitrary-file read (the prod DB
    lives at /app/data/dashboard.db in the container). resolve() + a
    containment check closes both the absolute-path and the traversal vectors.
    Returns None for anything not a contained real file → caller serves
    index.html (the client-route fallback)."""
    if not spa_path:
        return None
    dist_resolved = dist.resolve()
    candidate = (dist / spa_path).resolve()
    if candidate.is_file() and (
        candidate == dist_resolved or dist_resolved in candidate.parents
    ):
        return candidate
    return None


# Single-container deploy: serve the built SPA from the backend process.
# Assets mount under /assets (hashed filenames, cache-friendly); every
# non-API path falls back to index.html so client-side routes deep-link.
# Registered LAST — Starlette matches routes in registration order, so the
# catch-all must come after every API route and /health. No-op in dev
# (SERVE_FRONTEND_DIR unset → Vite serves the frontend).
if settings.serve_frontend_dir:
    from pathlib import Path as _Path

    from fastapi.responses import FileResponse
    from fastapi.staticfiles import StaticFiles

    _dist = _Path(settings.serve_frontend_dir)
    _index = _dist / "index.html"
    if _index.is_file():
        if (_dist / "assets").is_dir():
            app.mount(
                "/assets", StaticFiles(directory=_dist / "assets"), name="assets"
            )

        @app.get("/{spa_path:path}", include_in_schema=False)
        def _spa(spa_path: str):
            # An unknown /api/* path is a genuine 404 — NOT a client route.
            # Falling it back to index.html (200 text/html) would mask dead or
            # typo'd endpoints as healthy and break client error handling,
            # caches, and monitoring. The real API routes are registered
            # earlier and always win; only unmatched /api/* reaches here.
            if spa_path == "api" or spa_path.startswith("api/"):
                return JSONResponse(status_code=404, content={"detail": "not found"})
            # Real files at the dist root (favicon.svg, robots.txt) serve
            # directly; anything else (client route, or a traversal attempt)
            # falls back to index.html. Containment enforced in _safe_spa_file.
            safe = _safe_spa_file(_dist, spa_path)
            return FileResponse(safe if safe is not None else _index)
    else:
        log.warning(
            "SERVE_FRONTEND_DIR=%s has no index.html; SPA serving disabled",
            settings.serve_frontend_dir,
        )
