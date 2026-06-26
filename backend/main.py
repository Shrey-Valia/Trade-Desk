import asyncio
import logging
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from config import settings
from database import init_db
from services.rate_limit import _client_ip, global_limiter
from jobs.collect_options_chain import collect_options_chain
from jobs.prewarm_hot_tickers import prewarm_hot_tickers
from jobs.refresh_watchlist import refresh_watchlist
from jobs.seed_trades import seed_example_trades
from jobs.monitor_orders import monitor_orders
from jobs.settle_combines import settle_combines
from routers.ticker import MarketDataDegraded
from routers import account as account_router
from routers import analytics as analytics_router
from routers import auth as auth_router
from routers import combines as combines_router
from routers import calendar as calendar_router
from routers import journal as journal_router
from routers import journal_media as journal_media_router
from routers import market as market_router
from routers import news as news_router
from routers import payments as payments_router
from routers import ticker as ticker_router
from routers import ticker_search as ticker_search_router
from routers import user_browse as user_browse_router
from routers import watchlist as watchlist_router
from routers import zerodte as zerodte_router

logging.basicConfig(
    level=settings.log_level,
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
)
log = logging.getLogger("dashboard")


def _init_sentry() -> None:
    """Initialise Sentry error tracking — a clean no-op when unconfigured.

    Skips entirely when `settings.sentry_dsn` is blank (the default), so a
    dev box / CI never phones home. Also degrades gracefully if the SDK
    isn't installed: logs and moves on rather than crashing startup. The
    FastAPI integration is auto-enabled by sentry-sdk[fastapi] on init."""
    if not settings.sentry_dsn:
        log.info("sentry_dsn unset; error tracking disabled")
        return
    try:
        import sentry_sdk
    except ImportError:
        log.warning("SENTRY_DSN set but sentry-sdk not installed; skipping")
        return
    sentry_sdk.init(
        dsn=settings.sentry_dsn,
        environment=settings.sentry_environment,
        traces_sample_rate=settings.sentry_traces_sample_rate,
    )
    log.info("sentry initialised (env=%s)", settings.sentry_environment)


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

    scheduler = BackgroundScheduler(timezone="America/New_York")
    scheduler.add_job(
        refresh_watchlist,
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
        prewarm_hot_tickers,
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
        collect_options_chain,
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
        settle_combines,
        trigger=IntervalTrigger(minutes=5),
        id="settle_combines",
        max_instances=1,
        coalesce=True,
        misfire_grace_time=_SCHED_GRACE,
    )
    # Order monitor — fill working limit/stop orders + auto-close SL/TP
    # brackets every 20s during market hours. No-ops out of session.
    scheduler.add_job(
        monitor_orders,
        trigger=IntervalTrigger(seconds=20),
        id="monitor_orders",
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


@app.get("/health")
def health() -> JSONResponse:
    """Liveness + DB readiness. Probes a `SELECT 1` so a healthy 200 means
    the app can actually reach its database, not merely that the process is
    up. DB-down → 503 with status "degraded" so a load balancer pulls the
    box. Exempt from the global rate limit (see _RATE_LIMIT_EXEMPT_PATHS)."""
    from sqlalchemy import text

    from database import engine

    db_ok = True
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
    except Exception:  # noqa: BLE001
        db_ok = False
        log.exception("/health DB check failed")

    body = {
        "status": "ok" if db_ok else "degraded",
        "database": "up" if db_ok else "down",
    }
    return JSONResponse(status_code=200 if db_ok else 503, content=body)
