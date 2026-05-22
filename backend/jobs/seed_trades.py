"""One-shot seed for the Trade Desk journal — Phase 1 demo data.

Runs once at backend startup. If the trades table is empty, drops in a
handful of representative paper trades so the journal panel and (Phase
2) the chart overlays have something to show on first boot. If the
table already has rows we leave it alone, so restarts don't duplicate.

Strikes/expiries are anchored on today's date so they always look fresh
on whatever day the demo runs. Underlying prices use rough recent
levels — they don't need to be live since these are paper trades meant
for visual demo, not P&L accuracy.
"""

from __future__ import annotations

import json
import logging
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import select

from database import SessionLocal
from models.trade import Trade

log = logging.getLogger(__name__)


def _next_monthly_friday(reference: date, weeks_out: int = 4) -> date:
    """Return the Friday `weeks_out` weeks ahead — close enough to a
    monthly options expiry for demo purposes."""
    target = reference + timedelta(weeks=weeks_out)
    while target.weekday() != 4:  # 4 = Friday
        target += timedelta(days=1)
    return target


def _legs(*legs: dict) -> str:
    return json.dumps(legs)


def seed_example_trades() -> None:
    with SessionLocal() as session:
        existing = session.execute(select(Trade.id).limit(1)).first()
        if existing is not None:
            log.debug("trades table not empty; skipping seed")
            return

        now = datetime.now(timezone.utc)
        today = now.date()
        near_expiry = _next_monthly_friday(today, weeks_out=3).isoformat()
        far_expiry = _next_monthly_friday(today, weeks_out=6).isoformat()

        trades = [
            # 1. NVDA long straddle — pre-earnings vol play. Paper, open.
            Trade(
                symbol="NVDA",
                strategy="long_straddle",
                legs_json=_legs(
                    {"side": "call", "action": "buy", "strike": 220.0, "expiry": near_expiry, "contracts": 1, "entry_price": 9.40},
                    {"side": "put",  "action": "buy", "strike": 220.0, "expiry": near_expiry, "contracts": 1, "entry_price": 8.60},
                ),
                entry_date=now - timedelta(days=2),
                entry_underlying_price=219.85,
                net_debit_credit=1800.0,           # (9.40 + 8.60) * 1 * 100
                status="open",
                is_paper=True,
                notes="Pre-earnings vol play. IV elevated vs LSTM forecast.",
            ),
            # 2. AAPL bull call spread — directional bullish, defined risk.
            Trade(
                symbol="AAPL",
                strategy="bull_call_spread",
                legs_json=_legs(
                    {"side": "call", "action": "buy",  "strike": 230.0, "expiry": near_expiry, "contracts": 2, "entry_price": 6.20},
                    {"side": "call", "action": "sell", "strike": 240.0, "expiry": near_expiry, "contracts": 2, "entry_price": 2.10},
                ),
                entry_date=now - timedelta(days=5),
                entry_underlying_price=231.10,
                net_debit_credit=820.0,            # (6.20 - 2.10) * 2 * 100
                status="open",
                is_paper=True,
                notes="Upside through earnings; spread caps cost at $4.10 max loss.",
            ),
            # 3. SPY short iron condor — premium-selling on a range-bound expectation.
            Trade(
                symbol="SPY",
                strategy="iron_condor",
                legs_json=_legs(
                    {"side": "call", "action": "sell", "strike": 750.0, "expiry": far_expiry, "contracts": 1, "entry_price": 4.10},
                    {"side": "call", "action": "buy",  "strike": 760.0, "expiry": far_expiry, "contracts": 1, "entry_price": 2.30},
                    {"side": "put",  "action": "sell", "strike": 720.0, "expiry": far_expiry, "contracts": 1, "entry_price": 3.80},
                    {"side": "put",  "action": "buy",  "strike": 710.0, "expiry": far_expiry, "contracts": 1, "entry_price": 2.05},
                ),
                entry_date=now - timedelta(days=1),
                entry_underlying_price=738.20,
                net_debit_credit=-355.0,           # net credit of $3.55 × 100
                status="open",
                is_paper=True,
                notes="Range-bound expectation through monthly OPEX.",
            ),
            # 4. TSLA long call — CLOSED, realized P&L populated.
            Trade(
                symbol="TSLA",
                strategy="long_call",
                legs_json=_legs(
                    {"side": "call", "action": "buy", "strike": 410.0, "expiry": near_expiry, "contracts": 1, "entry_price": 11.80},
                ),
                entry_date=now - timedelta(days=14),
                entry_underlying_price=405.40,
                net_debit_credit=1180.0,
                status="closed",
                exit_date=now - timedelta(days=3),
                exit_underlying_price=422.15,
                realized_pnl=420.0,                # exited at ~$16.00, +$420 / contract
                is_paper=True,
                notes="Closed into strength; took +$420 ahead of CPI print.",
            ),
        ]

        for t in trades:
            session.add(t)
        session.commit()

        log.info("seeded %d example trades", len(trades))
