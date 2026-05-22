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

logging.basicConfig(
    level=settings.log_level,
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
)
log = logging.getLogger("dashboard")


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()

    # One-shot demo seed for Trade Desk journal. No-ops once the trades
    # table is non-empty, so it's safe to keep enabled across restarts.
    try:
        seed_example_trades()
    except Exception:  # noqa: BLE001
        log.exception("startup seed_example_trades failed")

    scheduler = BackgroundScheduler(timezone="America/New_York")

    # One-shot priming run at startup so the API isn't empty before the
    # first scheduled tick. Forced past the market-hours gate so we get
    # data even when running outside market hours.
    try:
        refresh_watchlist(force=True)
    except Exception:  # noqa: BLE001
        log.exception("startup refresh_watchlist failed")

    # Prime hot-ticker caches once at boot so the first click after restart
    # isn't a cold 8-15s wait. Forced past the market-hours gate for the
    # same reason as refresh_watchlist above.
    try:
        prewarm_hot_tickers(force=True)
    except Exception:  # noqa: BLE001
        log.exception("startup prewarm_hot_tickers failed")

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

    try:
        yield
    finally:
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


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
