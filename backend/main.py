import asyncio
import logging
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from config import settings
from database import init_db
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

    try:
        yield
    finally:
        # Cancel any still-running warm so shutdown is fast too.
        warm_task.cancel()
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
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    # Session-cookie auth. Origins must stay an explicit list (never
    # "*") once credentials are allowed.
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

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
def health() -> dict[str, str]:
    return {"status": "ok"}
