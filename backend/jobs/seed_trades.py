"""Demo seed for the Trade Desk journal — Phase 4 overnight polish.

Runs once at backend startup. If the trades table has fewer than ~10
rows it tops the journal up to a realistic spread (~35 closed paper
trades plus the existing few open ones) so the analytics tab populates
densely on first boot. Idempotent across restarts — won't duplicate
once the table is healthy.

The seeded story has a deliberate shape: iron condors win, long
straddles lose. That's a real "I overpay for premium" pattern and
makes the by-strategy view demonstrably useful as an edge-finding
tool. The mistake-cost view is similarly populated — ~40% of losers
carry a tag from the canonical vocabulary so the behavior-improvement
analytics tell a story too.
"""

from __future__ import annotations

import json
import logging
import random
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Literal

from sqlalchemy import select

from database import SessionLocal
from models.trade import Trade

log = logging.getLogger(__name__)

# Threshold for "is the table populated enough?". Below this we top up;
# at or above this, hands off (real user data lives here).
_MIN_TRADES_BEFORE_SEED = 10


def _next_friday(reference: date, weeks_out: int) -> date:
    target = reference + timedelta(weeks=weeks_out)
    while target.weekday() != 4:
        target += timedelta(days=1)
    return target


# ---------------------------------------------------------------------------
# Story spec — what trades to fabricate.
#
# The shape:
#   - ~13 iron condors with ~75% win rate, mostly small wins (premium
#     collection works in the demo's regime).
#   - ~10 long straddles with ~30% win rate, deeper losers (the
#     "premium addict" pattern — overpays for vol).
#   - ~7 bull/bear vertical spreads, mixed.
#   - ~5 long calls / puts, mixed.
#   - 4 OPEN trades (one of each: long straddle on NVDA — the existing
#     hero trade; bull call spread on AAPL; iron condor on SPY; long
#     call on TSLA closed earlier).
#
# Strikes/expiries are scaled to plausible recent prices. None of this
# is real fills — it's demo data, flagged is_paper=true throughout.
# ---------------------------------------------------------------------------


@dataclass
class _Tpl:
    symbol: str
    strategy: str
    underlying: float
    legs: list[dict]
    risk: float
    confidence: int
    thesis: str
    planned_exit: str
    tags: list[str]


def _leg(side: Literal["call", "put"], action: Literal["buy", "sell"],
         strike: float, expiry_iso: str, contracts: int, premium: float) -> dict:
    return {
        "side": side, "action": action, "strike": strike,
        "expiry": expiry_iso, "contracts": contracts, "entry_price": premium,
    }


def _build_closed_scenarios(today: date) -> list[tuple[_Tpl, float, list[str], int, int]]:
    """Returns list of (template, realized_pnl, mistake_tags, days_held, days_ago_closed)."""
    NF = lambda w: _next_friday(today, weeks_out=w).isoformat()  # noqa: E731
    scenarios: list[tuple[_Tpl, float, list[str], int, int]] = []

    # ---- IRON CONDORS — the "edge" story (mostly winners) ------------------
    ic_template = lambda sym, spot, w_out: _Tpl(  # noqa: E731
        symbol=sym, strategy="iron_condor", underlying=spot,
        legs=[
            _leg("call", "sell", round(spot * 1.04, 2), NF(w_out), 1, round(spot * 0.012, 2)),
            _leg("call", "buy",  round(spot * 1.07, 2), NF(w_out), 1, round(spot * 0.005, 2)),
            _leg("put",  "sell", round(spot * 0.96, 2), NF(w_out), 1, round(spot * 0.012, 2)),
            _leg("put",  "buy",  round(spot * 0.93, 2), NF(w_out), 1, round(spot * 0.005, 2)),
        ],
        risk=350,
        confidence=4,
        thesis="Premium-rich, range-bound expectation through expiry.",
        planned_exit="50% profit or 21 DTE; cut at -2x credit.",
        tags=["premium selling", "range-bound"],
    )
    ic_cases = [
        # (symbol, spot, weeks_out, pnl, days_ago_closed, mistakes)
        ("SPY",  738.0, 4,  280.0, 60,  []),
        ("SPY",  742.0, 5,  310.0, 50,  []),
        ("QQQ",  712.0, 4,  240.0, 75,  []),
        ("QQQ",  706.0, 5,  180.0, 65,  []),
        ("IWM",  238.0, 4,  205.0, 88,  []),
        ("AAPL", 230.0, 4,  165.0, 45,  []),
        ("AAPL", 234.0, 5,  -240.0, 35, ["held too long"]),  # one real loser
        ("MSFT", 425.0, 4,  150.0, 28,  []),
        ("NVDA", 215.0, 4,  -420.0, 18, ["ignored regime"]),  # a flagged loser
        ("META", 612.0, 5,  220.0, 22,  []),
        ("GOOGL",195.0, 5,  140.0, 70,  []),
        ("AMZN", 225.0, 4,  185.0, 52,  []),
        ("TSLA", 410.0, 4,  -310.0, 12, ["ignored regime"]),
    ]
    for sym, spot, weeks, pnl, days_ago, mistakes in ic_cases:
        tpl = ic_template(sym, spot, weeks)
        scenarios.append((tpl, pnl, mistakes, weeks * 7 - days_ago + 10, days_ago))

    # ---- LONG STRADDLES — the "leak" story (mostly losers) -----------------
    ls_template = lambda sym, spot, w_out, leg_prem: _Tpl(  # noqa: E731
        symbol=sym, strategy="long_straddle", underlying=spot,
        legs=[
            _leg("call", "buy", round(spot, 2), NF(w_out), 1, leg_prem),
            _leg("put",  "buy", round(spot, 2), NF(w_out), 1, leg_prem),
        ],
        risk=round(leg_prem * 2 * 100 * 0.5, 2),  # 50% of cost as planned risk
        confidence=3,
        thesis="Vol elevated into earnings/event; long premium for expansion.",
        planned_exit="Close into vol expansion or 1 DTE.",
        tags=["earnings", "vol expansion"],
    )
    ls_cases = [
        # winners (smaller, fewer)
        ("NVDA", 217.0, 4, 9.0,   380.0, 22, []),
        ("TSLA", 405.0, 4, 12.5,  520.0, 33, []),
        ("META", 620.0, 4, 15.5,  -340.0, 18, ["chased IV crush"]),
        ("AAPL", 228.0, 4, 5.6,   -180.0, 28, ["chased IV crush"]),
        ("AAPL", 232.0, 4, 6.4,   -210.0, 45, ["no exit plan"]),
        ("MSFT", 422.0, 4, 10.5,  -260.0, 38, ["chased IV crush"]),
        ("AMD",  140.0, 4, 7.2,   -360.0, 14, ["revenge trade", "oversized"]),
        ("GOOGL",193.0, 4, 6.0,   -240.0, 52, ["chased IV crush"]),
        ("NFLX", 540.0, 4, 22.0,  580.0, 41, []),
        ("PLTR", 38.0,  4, 2.4,   -300.0, 25, ["chased IV crush"]),
    ]
    for sym, spot, weeks, leg_prem, pnl, days_ago, mistakes in ls_cases:
        tpl = ls_template(sym, spot, weeks, leg_prem)
        scenarios.append((tpl, pnl, mistakes, weeks * 7 - days_ago + 12, days_ago))

    # ---- BULL/BEAR VERTICALS — mixed -------------------------------------
    bcs_template = lambda sym, spot, w_out, debit: _Tpl(  # noqa: E731
        symbol=sym, strategy="bull_call_spread", underlying=spot,
        legs=[
            _leg("call", "buy",  round(spot, 2), NF(w_out), 2, debit + 2),
            _leg("call", "sell", round(spot * 1.04, 2), NF(w_out), 2, 2.0),
        ],
        risk=round((debit) * 2 * 100, 2),
        confidence=4,
        thesis="Bullish momentum continuation, defined-risk debit.",
        planned_exit="50% of max profit or stop on trend break.",
        tags=["momentum", "directional"],
    )
    bps_template = lambda sym, spot, w_out, debit: _Tpl(  # noqa: E731
        symbol=sym, strategy="bear_put_spread", underlying=spot,
        legs=[
            _leg("put",  "buy",  round(spot, 2), NF(w_out), 1, debit + 2),
            _leg("put",  "sell", round(spot * 0.96, 2), NF(w_out), 1, 2.0),
        ],
        risk=round(debit * 100, 2),
        confidence=3,
        thesis="Bearish thesis, defined-risk debit.",
        planned_exit="50% of max profit or invalidation.",
        tags=["mean reversion", "directional"],
    )
    vert_cases = [
        (bcs_template, "MSFT", 419.0, 4, 4.0,  640.0,  20, []),
        (bcs_template, "NVDA", 211.0, 4, 4.5,  -460.0, 30, ["cut winner early"]),
        (bcs_template, "AAPL", 227.0, 5, 3.8, 380.0,  18, []),
        (bcs_template, "COIN", 280.0, 4, 6.5, -780.0, 11, ["oversized"]),
        (bps_template, "TSLA", 415.0, 4, 5.5,  280.0,  9,  []),
        (bps_template, "AMD",  142.0, 4, 4.0, -200.0, 24, []),
        (bps_template, "NFLX", 542.0, 4, 7.0,  410.0,  35, []),
    ]
    for fn, sym, spot, weeks, debit, pnl, days_ago, mistakes in vert_cases:
        tpl = fn(sym, spot, weeks, debit)
        scenarios.append((tpl, pnl, mistakes, weeks * 7 - days_ago + 8, days_ago))

    # ---- SINGLE LEGS — small, mixed --------------------------------------
    long_call = lambda sym, spot, w_out, prem: _Tpl(  # noqa: E731
        symbol=sym, strategy="long_call", underlying=spot,
        legs=[_leg("call", "buy", round(spot, 2), NF(w_out), 1, prem)],
        risk=round(prem * 100, 2),
        confidence=3,
        thesis="Speculative upside.",
        planned_exit="Trail stop after +50%.",
        tags=["directional", "speculative"],
    )
    long_put = lambda sym, spot, w_out, prem: _Tpl(  # noqa: E731
        symbol=sym, strategy="long_put", underlying=spot,
        legs=[_leg("put", "buy", round(spot, 2), NF(w_out), 1, prem)],
        risk=round(prem * 100, 2),
        confidence=3,
        thesis="Speculative downside.",
        planned_exit="Trail stop after +50%.",
        tags=["directional", "speculative"],
    )
    single_cases = [
        (long_call, "TSLA", 408.0, 3,  12.0,  680.0, 15, []),   # the existing TSLA winner
        (long_call, "NVDA", 209.0, 3,  10.0, -540.0,  6, ["rolled too soon"]),
        (long_call, "AAPL", 228.0, 4, 6.5,   210.0,  29, []),
        (long_put,  "META", 615.0, 3,  14.0, -460.0,  8, ["chased IV crush"]),
        (long_put,  "BA",   165.0, 4,  4.5,  180.0,  21, []),
    ]
    for fn, sym, spot, weeks, prem, pnl, days_ago, mistakes in single_cases:
        tpl = fn(sym, spot, weeks, prem)
        scenarios.append((tpl, pnl, mistakes, weeks * 7 - days_ago + 6, days_ago))

    return scenarios


def _open_scenarios(today: date, now: datetime) -> list[Trade]:
    """The hero open positions — the same four trades the original seed
    had, so cold-open with NVDA still works and the chart overlay path
    is exercised in the demo."""
    NF = lambda w: _next_friday(today, weeks_out=w).isoformat()  # noqa: E731
    return [
        Trade(
            symbol="NVDA",
            strategy="long_straddle",
            legs_json=json.dumps([
                _leg("call", "buy", 220.0, NF(3), 1, 9.40),
                _leg("put",  "buy", 220.0, NF(3), 1, 8.60),
            ]),
            entry_date=now - timedelta(days=2),
            entry_underlying_price=219.85,
            net_debit_credit=1800.0,
            status="open",
            is_paper=True,
            notes="Pre-earnings vol play. IV elevated vs LSTM forecast.",
            tags_json=json.dumps(["earnings", "vol expansion"]),
            mistake_tags_json="[]",
            confidence=4,
            thesis="NVDA reports in 3 days; IV31 ~85% vs LSTM 7d RV ~35% → premium pricing-in big move.",
            planned_exit="Close into vol expansion (target +30%) or night before print.",
            risk_amount=900.0,
        ),
        Trade(
            symbol="AAPL",
            strategy="bull_call_spread",
            legs_json=json.dumps([
                _leg("call", "buy",  230.0, NF(3), 2, 6.20),
                _leg("call", "sell", 240.0, NF(3), 2, 2.10),
            ]),
            entry_date=now - timedelta(days=5),
            entry_underlying_price=231.10,
            net_debit_credit=820.0,
            status="open",
            is_paper=True,
            notes="Upside through earnings; spread caps cost at $4.10 max loss.",
            tags_json=json.dumps(["momentum", "directional"]),
            mistake_tags_json="[]",
            confidence=4,
            thesis="Trend continuation + bullish flow into earnings.",
            planned_exit="50% of max profit ($410) or close on close <225.",
            risk_amount=820.0,
        ),
        Trade(
            symbol="SPY",
            strategy="iron_condor",
            legs_json=json.dumps([
                _leg("call", "sell", 750.0, NF(6), 1, 4.10),
                _leg("call", "buy",  760.0, NF(6), 1, 2.30),
                _leg("put",  "sell", 720.0, NF(6), 1, 3.80),
                _leg("put",  "buy",  710.0, NF(6), 1, 2.05),
            ]),
            entry_date=now - timedelta(days=1),
            entry_underlying_price=738.20,
            net_debit_credit=-355.0,
            status="open",
            is_paper=True,
            notes="Range-bound expectation through monthly OPEX.",
            tags_json=json.dumps(["premium selling", "range-bound"]),
            mistake_tags_json="[]",
            confidence=4,
            thesis="VIX compressed, regime stable, 30D realized vol low.",
            planned_exit="50% of max profit or 21 DTE.",
            risk_amount=645.0,
        ),
        # Hero CLOSED trade — TSLA long call that paid +$420 (kept for
        # continuity with prior phases; analytics will absorb it into
        # the equity curve and KPIs alongside the new closed batch).
        Trade(
            symbol="TSLA",
            strategy="long_call",
            legs_json=json.dumps([
                _leg("call", "buy", 410.0, NF(3), 1, 11.80),
            ]),
            entry_date=now - timedelta(days=14),
            entry_underlying_price=405.40,
            net_debit_credit=1180.0,
            status="closed",
            exit_date=now - timedelta(days=3),
            exit_underlying_price=422.15,
            realized_pnl=420.0,
            is_paper=True,
            notes="Closed into strength; took +$420 ahead of CPI print.",
            tags_json=json.dumps(["directional"]),
            mistake_tags_json="[]",
            confidence=4,
            thesis="Trend continuation through technical level.",
            planned_exit="Take profits before CPI print.",
            risk_amount=1180.0,
        ),
    ]


def seed_example_trades() -> None:
    with SessionLocal() as session:
        existing_count = session.execute(select(Trade.id)).all()
        if len(existing_count) >= _MIN_TRADES_BEFORE_SEED:
            log.debug(
                "trades table already populated (%d rows); skipping seed",
                len(existing_count),
            )
            return

        # Wipe and rebuild only when the table is essentially empty —
        # ≤ MIN_TRADES rows means this is a fresh DB or a Phase-1 seed
        # we want to upgrade with the richer Phase-4 spread.
        if existing_count:
            for t in session.execute(select(Trade)).scalars().all():
                session.delete(t)
            session.commit()

        now = datetime.now(timezone.utc)
        today = now.date()

        # Deterministic ordering so the equity curve has a stable shape
        # across cold starts.
        rng = random.Random(42)

        # Open positions (the hero set).
        seeded = _open_scenarios(today, now)

        # Closed positions — fabricated from the scenario list.
        for tpl, pnl, mistakes, _days_held, days_ago_closed in _build_closed_scenarios(today):
            cost_basis = 0.0
            for leg in tpl.legs:
                sign = 1 if leg["action"] == "buy" else -1
                cost_basis += sign * leg["entry_price"] * leg["contracts"] * 100
            # Spread exit times slightly so the equity curve has texture.
            jitter_hours = rng.randint(0, 23)
            exit_dt = now - timedelta(days=days_ago_closed, hours=jitter_hours)
            entry_dt = exit_dt - timedelta(days=rng.randint(3, 18))
            seeded.append(
                Trade(
                    symbol=tpl.symbol,
                    strategy=tpl.strategy,
                    legs_json=json.dumps(tpl.legs),
                    entry_date=entry_dt,
                    entry_underlying_price=tpl.underlying,
                    net_debit_credit=round(cost_basis, 2),
                    status="closed",
                    exit_date=exit_dt,
                    exit_underlying_price=round(
                        tpl.underlying * (1.0 + rng.uniform(-0.05, 0.05)),
                        2,
                    ),
                    realized_pnl=round(pnl, 2),
                    is_paper=True,
                    notes=None,
                    tags_json=json.dumps(tpl.tags),
                    mistake_tags_json=json.dumps(mistakes),
                    confidence=tpl.confidence,
                    thesis=tpl.thesis,
                    planned_exit=tpl.planned_exit,
                    risk_amount=tpl.risk,
                    review_note=(
                        f"Lessons: {', '.join(mistakes)}." if mistakes else None
                    ),
                )
            )

        for t in seeded:
            session.add(t)
        session.commit()
        log.info(
            "seeded %d demo trades (%d open + %d closed) — by-strategy story: condors win, straddles lose",
            len(seeded),
            sum(1 for t in seeded if t.status == "open"),
            sum(1 for t in seeded if t.status == "closed"),
        )
