"""Daily job: snapshot every universe ticker's options chain to SQLite.

Runs Mon-Fri at 16:30 ET via APScheduler. The NYSE calendar gate skips
holidays even when they fall on weekdays. Each ticker's fetch is wrapped
in its own try/except so one bad chain can't kill the whole batch.

This dataset is what the IV-Rank percentile + Phase 6+ ML training read
from. We don't backfill — start collecting forward and the window grows
day by day.
"""

from __future__ import annotations

import logging
from datetime import datetime
from zoneinfo import ZoneInfo

from config import settings
from database import SessionLocal
from models.options_snapshot import OptionsSnapshot
from services.alpaca_client import get_chain_snapshot
from services.market_calendar import is_market_open
from services.timeouts import CallTimeout, run_with_timeout

log = logging.getLogger(__name__)
_ET = ZoneInfo("America/New_York")

# Chain snapshots can be large (hundreds of contracts × 15 symbols) and
# the Alpaca SDK has no init-level request timeout. Bound each fetch so
# one stuck symbol can't run the daily job past the next scheduler tick.
_PER_SYMBOL_TIMEOUT_SECONDS = 20.0


def collect_options_chain() -> None:
    today_et = datetime.now(_ET).date()
    # Job fires after close; check that today was a trading day. We piggyback
    # on `is_market_open` by passing 12:00 ET — that's between open and close
    # on any real session day and definitively outside on holidays/weekends.
    noon_today = datetime.combine(today_et, datetime.min.time().replace(hour=12), tzinfo=_ET)
    if not is_market_open(noon_today):
        log.info("collect_options_chain: %s was not a trading day; skipping", today_et)
        return

    log.info("collect_options_chain: starting for %d symbols", len(settings.watchlist_universe))
    total_rows = 0
    with SessionLocal() as session:
        for symbol in settings.watchlist_universe:
            try:
                rows = run_with_timeout(
                    get_chain_snapshot, symbol, True,
                    timeout_s=_PER_SYMBOL_TIMEOUT_SECONDS,
                )
            except CallTimeout:
                log.warning(
                    "collect_options_chain: %s exceeded %.0fs; skipping",
                    symbol, _PER_SYMBOL_TIMEOUT_SECONDS,
                )
                continue
            except Exception:
                log.exception("collect_options_chain: fetch failed for %s; skipping", symbol)
                continue
            if not rows:
                log.warning("collect_options_chain: empty chain for %s", symbol)
                continue
            for r in rows:
                session.add(
                    OptionsSnapshot(
                        symbol=symbol,
                        snapshot_date=today_et,
                        strike=r.strike,
                        expiry=r.expiry,
                        option_type=r.type,
                        bid=r.bid,
                        ask=r.ask,
                        last=r.last,
                        volume=r.volume,
                        open_interest=r.open_interest,
                        iv=r.iv,
                        delta=r.delta,
                        gamma=r.gamma,
                    )
                )
                total_rows += 1
        session.commit()
    log.info("collect_options_chain: wrote %d rows for %s", total_rows, today_et)
