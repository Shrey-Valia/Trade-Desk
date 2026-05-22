"""Resumable backfill of historical earnings events for the ML training table.

Run from the backend directory:

    python -m scripts.backfill_earnings              # both universes
    python -m scripts.backfill_earnings --tickers AAPL NVDA   # subset

Resumability: per-ticker we look up MAX(earnings_date) already stored and
only insert events strictly after that watermark. Re-running after a
partial failure is safe and fast.
"""

from __future__ import annotations

import argparse
import logging
import time
from datetime import date, datetime, timedelta, timezone

import pandas as pd
from sqlalchemy import func, select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from config import settings
from database import SessionLocal, init_db
from models.historical_earnings_event import HistoricalEarningsEvent
from services.alpaca_client import get_daily_bars_history
from services.finnhub_client import company_earnings, earnings_calendar_for_symbol
from services.yfinance_client import historical_earnings as yf_historical_earnings

# Threshold below which we trigger the yfinance fallback. 8 quarters = 2y;
# below that the model can't see two full earnings cycles per ticker.
FINNHUB_FALLBACK_THRESHOLD = 8
# Per-ticker spacing for yfinance calls. Yahoo throttles aggressively.
YF_SPACING_SECONDS = 1.0

logging.basicConfig(
    level="INFO",
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
)
log = logging.getLogger("backfill")


def _bars_to_series(bars: list) -> pd.Series:
    """Convert Alpaca bars → pd.Series of close indexed by tz-naive midnight."""
    if not bars:
        return pd.Series(dtype=float)
    closes = {pd.Timestamp(b.timestamp.date()): float(b.close) for b in bars}
    return pd.Series(closes).sort_index()


def _next_trading_day_after(closes: pd.Series, d: date) -> date | None:
    cutoff = pd.Timestamp(d)
    after = closes[closes.index > cutoff]
    if after.empty:
        return None
    return after.index[0].date()


def _last_trading_day_before(closes: pd.Series, d: date) -> date | None:
    cutoff = pd.Timestamp(d)
    before = closes[closes.index < cutoff]
    if before.empty:
        return None
    return before.index[-1].date()


def _compute_move(
    closes: pd.Series, event_date: date, bmo_amc: str
) -> tuple[float, float, float] | None:
    """Returns (prev_close, realized_close, abs_move_pct).

    BMO: prev_close = T-1 close, realized = T close.
    AMC (or unknown): prev_close = T close, realized = T+1 close.
    """
    is_amc = (bmo_amc or "").lower() == "amc"
    event_ts = pd.Timestamp(event_date)
    if is_amc:
        if event_ts not in closes.index:
            # AMC requires the earnings_date to be a trading day; if not, fall
            # back to BMO logic (use prior trading day as prev).
            is_amc = False
        else:
            prev_close = float(closes.at[event_ts])
            next_day = _next_trading_day_after(closes, event_date)
            if next_day is None:
                return None
            realized_close = float(closes.at[pd.Timestamp(next_day)])
    if not is_amc:
        prior = _last_trading_day_before(closes, event_date)
        if prior is None or event_ts not in closes.index:
            return None
        prev_close = float(closes.at[pd.Timestamp(prior)])
        realized_close = float(closes.at[event_ts])
    if prev_close == 0:
        return None
    return prev_close, realized_close, abs(realized_close - prev_close) / prev_close * 100


def _eps_surprise_for(date_: date, eps_history: list) -> tuple[float | None, float | None, float | None]:
    """Match an earnings date to the closest prior EPS surprise quarter.

    Finnhub `company_earnings` returns rows keyed by `period` (quarter end),
    NOT by report date. We match by picking the row whose period falls in
    the quarter immediately before `date_`.
    """
    candidates = []
    for r in eps_history:
        period = r.get("period")
        if not period:
            continue
        try:
            period_date = date.fromisoformat(period)
        except ValueError:
            continue
        if period_date < date_:
            candidates.append((period_date, r))
    if not candidates:
        return None, None, None
    # Most recent quarter strictly before this earnings date.
    candidates.sort(key=lambda x: x[0], reverse=True)
    row = candidates[0][1]
    actual = row.get("actual")
    estimate = row.get("estimate")
    surprise_pct = row.get("surprisePercent")
    return (
        float(actual) if actual is not None else None,
        float(estimate) if estimate is not None else None,
        float(surprise_pct) if surprise_pct is not None else None,
    )


def _watermark(symbol: str) -> date | None:
    with SessionLocal() as session:
        return session.execute(
            select(func.max(HistoricalEarningsEvent.earnings_date)).where(
                HistoricalEarningsEvent.symbol == symbol
            )
        ).scalar()


def _upsert_events(rows: list[dict]) -> int:
    if not rows:
        return 0
    with SessionLocal() as session:
        stmt = sqlite_insert(HistoricalEarningsEvent).values(rows)
        # SQLite "INSERT OR REPLACE" via on_conflict_do_update on the unique
        # constraint. Lets re-runs idempotently update if anything changed.
        update_cols = {c.name: c for c in stmt.excluded if c.name not in ("id",)}
        stmt = stmt.on_conflict_do_update(
            index_elements=["symbol", "earnings_date"],
            set_=update_cols,
        )
        session.execute(stmt)
        session.commit()
    return len(rows)


def backfill_one_ticker(symbol: str, years_back: int = 5) -> tuple[int, dict]:
    """Returns (rows_written, source_breakdown) where breakdown counts dates
    by provenance: finnhub_only / yfinance_only / both."""
    log.info("backfilling %s …", symbol)
    bars = get_daily_bars_history(symbol, years_back=years_back)
    if not bars:
        log.warning("%s: no Alpaca bars; skipping", symbol)
        return 0, {"finnhub_only": 0, "yfinance_only": 0, "both": 0}
    closes = _bars_to_series(bars)

    today = datetime.now().date()
    earliest = today - timedelta(days=years_back * 366)

    # 1. Finnhub: per-symbol calendar in 1y chunks.
    finnhub_dates: dict[date, str] = {}
    chunk_start = earliest
    while chunk_start < today:
        chunk_end = min(chunk_start + timedelta(days=365), today)
        rows = earnings_calendar_for_symbol(
            symbol, chunk_start.isoformat(), chunk_end.isoformat()
        )
        for r in rows:
            try:
                d = date.fromisoformat(r.date)
            except ValueError:
                continue
            if d < today:  # past only — future dates don't have realized moves
                finnhub_dates.setdefault(d, (r.hour or "").lower())
        chunk_start = chunk_end + timedelta(days=1)

    # 2. yfinance fallback when Finnhub is sparse.
    yf_rows_by_date: dict = {}
    if len(finnhub_dates) < FINNHUB_FALLBACK_THRESHOLD:
        log.info(
            "%s: Finnhub returned %d events (< %d); falling back to yfinance",
            symbol, len(finnhub_dates), FINNHUB_FALLBACK_THRESHOLD,
        )
        for r in yf_historical_earnings(symbol):
            yf_rows_by_date[r.earnings_date] = r
        time.sleep(YF_SPACING_SECONDS)

    if not finnhub_dates and not yf_rows_by_date:
        log.warning("%s: no earnings dates from either source; skipping", symbol)
        return 0, {"finnhub_only": 0, "yfinance_only": 0, "both": 0}

    eps_history = company_earnings(symbol, limit=20)
    watermark = _watermark(symbol)

    all_dates = sorted(set(finnhub_dates) | set(yf_rows_by_date))
    new_rows: list[dict] = []
    breakdown = {"finnhub_only": 0, "yfinance_only": 0, "both": 0}

    for event_date in all_dates:
        if watermark is not None and event_date <= watermark:
            continue
        in_fh = event_date in finnhub_dates
        in_yf = event_date in yf_rows_by_date
        if in_fh and in_yf:
            date_source = "both"
            breakdown["both"] += 1
        elif in_fh:
            date_source = "finnhub"
            breakdown["finnhub_only"] += 1
        else:
            date_source = "yfinance"
            breakdown["yfinance_only"] += 1

        hour = finnhub_dates.get(event_date, "")
        move = _compute_move(closes, event_date, hour)
        if move is None:
            continue
        prev_close, realized_close, abs_move = move

        # EPS: Finnhub first; yfinance only fills quarters Finnhub doesn't have.
        eps_actual, eps_estimate, eps_surprise_pct = _eps_surprise_for(event_date, eps_history)
        if eps_surprise_pct is None and event_date in yf_rows_by_date:
            yf_r = yf_rows_by_date[event_date]
            eps_actual = eps_actual if eps_actual is not None else yf_r.eps_actual
            eps_estimate = eps_estimate if eps_estimate is not None else yf_r.eps_estimate
            eps_surprise_pct = yf_r.eps_surprise_pct

        new_rows.append(
            dict(
                symbol=symbol,
                earnings_date=event_date,
                bmo_amc=hour,
                prev_close=prev_close,
                realized_close=realized_close,
                abs_move_pct=abs_move,
                eps_actual=eps_actual,
                eps_estimate=eps_estimate,
                eps_surprise_pct=eps_surprise_pct,
                date_source=date_source,
                created_at=datetime.now(timezone.utc),
            )
        )

    written = _upsert_events(new_rows)
    log.info(
        "%s: wrote %d events (watermark=%s, sources=%s)",
        symbol, written, watermark, breakdown,
    )
    return written, breakdown


def main() -> None:
    parser = argparse.ArgumentParser(description="Backfill earnings history for ML training.")
    parser.add_argument("--tickers", nargs="*", default=None, help="Subset of tickers; default = both universes")
    parser.add_argument("--years", type=int, default=5, help="Years of history to pull (default 5)")
    args = parser.parse_args()

    init_db()
    universe = (
        list(args.tickers)
        if args.tickers
        else sorted(set(settings.watchlist_universe) | set(settings.training_universe))
    )
    # ETFs / indices in the watchlist don't have earnings.
    universe = [t for t in universe if t not in ("QQQ", "SPY")]

    log.info("backfill start: %d tickers, %d years", len(universe), args.years)
    total = 0
    aggregate = {"finnhub_only": 0, "yfinance_only": 0, "both": 0}
    for sym in universe:
        try:
            written, breakdown = backfill_one_ticker(sym, years_back=args.years)
            total += written
            for k in aggregate:
                aggregate[k] += breakdown[k]
        except Exception:  # noqa: BLE001
            log.exception("backfill failed for %s; continuing", sym)
    log.info("backfill done: %d total events; sources=%s", total, aggregate)


if __name__ == "__main__":
    main()
