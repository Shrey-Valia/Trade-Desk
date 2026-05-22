"""Thin yfinance wrapper for historical earnings dates + EPS estimates.

yfinance scrapes Yahoo's HTML and breaks every ~6 months when Yahoo
redesigns. Every call is wrapped in try/except — a yfinance failure must
never crash the backfill. Pin the version in pyproject.toml.

Rate limiting: Yahoo throttles aggressively. Caller is expected to space
calls ~1s apart per ticker. We don't sleep inside this module — that's
the backfill's responsibility (it already paces Finnhub, doing the same
here keeps the policy in one place).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, datetime

log = logging.getLogger(__name__)


@dataclass
class YfinanceEarningsRow:
    earnings_date: date
    eps_estimate: float | None
    eps_actual: float | None
    eps_surprise_pct: float | None


def historical_earnings(symbol: str) -> list[YfinanceEarningsRow]:
    """Return historical earnings rows (date strictly before today).

    yfinance's `Ticker.earnings_dates` returns BOTH past and future dates;
    we filter to past. Empty list on any failure (yfinance redesign,
    rate limit, network) — caller treats this as "no fallback data."
    """
    try:
        import yfinance as yf  # imported lazily so the rest of the app
                               # doesn't pay the import cost at startup
    except Exception as exc:  # noqa: BLE001
        log.warning("yfinance import failed for %s: %s", symbol, exc)
        return []

    try:
        ticker = yf.Ticker(symbol)
        df = ticker.earnings_dates
    except Exception as exc:  # noqa: BLE001
        log.warning(
            "yfinance call failed for %s — Yahoo may have changed their HTML "
            "structure, check yfinance version: %s",
            symbol, exc,
        )
        return []

    if df is None or len(df) == 0:
        return []

    today = date.today()
    out: list[YfinanceEarningsRow] = []
    for ts, row in df.iterrows():
        try:
            d = ts.date() if hasattr(ts, "date") else datetime.fromisoformat(str(ts)).date()
        except Exception:  # noqa: BLE001
            continue
        if d >= today:
            continue
        # yfinance column names — dataframe-tolerant lookup.
        eps_est = _col(row, "EPS Estimate")
        eps_act = _col(row, "Reported EPS")
        surprise_pct = _col(row, "Surprise(%)")
        out.append(
            YfinanceEarningsRow(
                earnings_date=d,
                eps_estimate=eps_est,
                eps_actual=eps_act,
                eps_surprise_pct=surprise_pct,
            )
        )
    out.sort(key=lambda r: r.earnings_date)
    return out


def _col(row, name: str) -> float | None:
    if name not in row.index:
        return None
    val = row[name]
    if val is None:
        return None
    try:
        v = float(val)
    except (TypeError, ValueError):
        return None
    if v != v:  # NaN check
        return None
    return v
