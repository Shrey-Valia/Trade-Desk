import asyncio
import logging
from contextlib import asynccontextmanager

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
from routers import analytics as analytics_router
from routers import bs as bs_router
from routers import calendar as calendar_router
from routers import journal as journal_router
from routers import market as market_router
from routers import mc as mc_router
from routers import models as models_router
from routers import regime as regime_router
from routers import signal as signal_router
from routers import ticker as ticker_router
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

    scheduler = BackgroundScheduler(timezone="America/New_York")
    scheduler.add_job(
        refresh_watchlist,
        trigger=IntervalTrigger(seconds=60),
        id="refresh_watchlist",
        max_instances=1,
        coalesce=True,
    )
    scheduler.add_job(
        prewarm_hot_tickers,
        trigger=IntervalTrigger(seconds=60),
        id="prewarm_hot_tickers",
        max_instances=1,
        coalesce=True,
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

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(watchlist_router.router)
app.include_router(ticker_router.router)
app.include_router(calendar_router.router)
app.include_router(mc_router.router)
app.include_router(bs_router.router)
app.include_router(models_router.router)
app.include_router(market_router.router)
app.include_router(regime_router.router)
app.include_router(signal_router.router)
app.include_router(journal_router.router)
app.include_router(analytics_router.router)
app.include_router(zerodte_router.router)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
