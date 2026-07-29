"""GET /api/analytics — cross-trade aggregations for the analytics tab.

Filters at the API boundary: paper/live, strategy, since/until on
exit_date. Computation lives in calculations/journal_analytics.py;
this router is glue + serialization.
"""

from __future__ import annotations

import logging
import math
from datetime import UTC, date, datetime, time
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from calculations.journal_analytics import compose
from calculations.monte_carlo import simulate_terminal_pnl
from database import get_session
from models.combine import Combine
from models.trade import Trade
from models.user import User
from schemas.analytics import (
    AnalyticsFilters,
    AnalyticsResponse,
    DteBucketOut,
    EquityCurveOut,
    EquityPointOut,
    KpiBlockOut,
    MistakeBucketOut,
    RiskBlockOut,
    StrategyBucketOut,
    StreakStatsOut,
    SymbolBucketOut,
    TimeBucketOut,
)
from services.auth import get_current_user

router = APIRouter(prefix="/api/analytics", tags=["analytics"])
log = logging.getLogger(__name__)


@router.get("", response_model=AnalyticsResponse)
def get_analytics(
    paper: bool | None = Query(default=None, description="Filter is_paper"),
    strategy: str | None = Query(default=None),
    since: str | None = Query(default=None, description="ISO date — exit_date >= since"),
    until: str | None = Query(default=None, description="ISO date — exit_date <= until"),
    trail: float | None = Query(
        default=None,
        ge=0,
        description="Active tier's MLL trailing distance — enables the days-near-MLL count.",
    ),
    combine_id: int | None = Query(
        default=None,
        description="Scope to one owned combine (e.g. the dashboard's active one).",
    ),
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
) -> AnalyticsResponse:
    """Aggregate journal metrics for the signed-in user. All filters optional."""
    # Always scoped to the user's own combines; an explicit combine_id
    # narrows to one (ownership-checked → 404 on foreign ids).
    stmt = select(Trade).where(
        Trade.combine_id.in_(select(Combine.id).where(Combine.user_id == user.id))
    )
    if combine_id is not None:
        combine = session.execute(
            select(Combine).where(
                Combine.id == combine_id, Combine.user_id == user.id
            )
        ).scalar_one_or_none()
        if combine is None:
            raise HTTPException(404, f"combine {combine_id} not found")
        stmt = stmt.where(Trade.combine_id == combine_id)
        # Funded-stage scoping. Activation re-bases the account's accounting to
        # the funded epoch (funded_epoch_at) — from that instant the balance /
        # closed-P&L the account header shows count ONLY trades opened at/after
        # the epoch (services.combine_state.realized_sum_for_combine, entry_date
        # based). Scope the analytics the same way so the dashboard's balance
        # curve + performance tracker match the header instead of replaying the
        # eval-stage trades a funded account no longer counts. Pre-activation
        # (funded_epoch_at is None) nothing is filtered, so the eval view is
        # unchanged. (The Journal remains the full trade log, by design.)
        if combine.funded_epoch_at is not None:
            stmt = stmt.where(Trade.entry_date >= combine.funded_epoch_at)
    if paper is not None:
        stmt = stmt.where(Trade.is_paper == paper)
    if strategy:
        stmt = stmt.where(Trade.strategy == strategy.lower())
    if since:
        try:
            d = date.fromisoformat(since)
            stmt = stmt.where(
                Trade.exit_date >= datetime.combine(d, time.min, tzinfo=UTC)
            )
        except ValueError:
            pass
    if until:
        try:
            d = date.fromisoformat(until)
            stmt = stmt.where(
                Trade.exit_date <= datetime.combine(d, time.max, tzinfo=UTC)
            )
        except ValueError:
            pass

    trades = session.execute(stmt).scalars().all()
    result = compose(trades, trail)

    # Pydantic can't serialize math.inf cleanly to JSON — coerce to None.
    def _finite(v: float | None) -> float | None:
        if v is None:
            return None
        if math.isinf(v) or math.isnan(v):
            return None
        return v

    return AnalyticsResponse(
        kpis=KpiBlockOut(
            total_trades=result.kpis.total_trades,
            open_trades=result.kpis.open_trades,
            closed_trades=result.kpis.closed_trades,
            win_rate=result.kpis.win_rate,
            net_pnl=result.kpis.net_pnl,
            profit_factor=_finite(result.kpis.profit_factor),
            avg_winner=result.kpis.avg_winner,
            avg_loser=result.kpis.avg_loser,
            expectancy=result.kpis.expectancy,
            avg_r=result.kpis.avg_r,
            largest_winner=result.kpis.largest_winner,
            largest_loser=result.kpis.largest_loser,
            avg_hold_min=result.kpis.avg_hold_min,
        ),
        by_strategy=[
            StrategyBucketOut(
                strategy=b.strategy,
                trades=b.trades,
                closed=b.closed,
                win_rate=b.win_rate,
                net_pnl=b.net_pnl,
                avg_pnl=b.avg_pnl,
                profit_factor=_finite(b.profit_factor),
                avg_r=b.avg_r,
            )
            for b in result.by_strategy
        ],
        by_symbol=[
            SymbolBucketOut(
                symbol=b.symbol, trades=b.trades, closed=b.closed,
                win_rate=b.win_rate, net_pnl=b.net_pnl, avg_pnl=b.avg_pnl,
            )
            for b in result.by_symbol
        ],
        by_dte=[
            DteBucketOut(
                label=b.label, trades=b.trades, win_rate=b.win_rate,
                avg_pnl=b.avg_pnl, net_pnl=b.net_pnl,
            )
            for b in result.by_dte
        ],
        by_time_of_day=[
            TimeBucketOut(
                label=b.label, trades=b.trades, win_rate=b.win_rate,
                avg_pnl=b.avg_pnl, net_pnl=b.net_pnl,
            )
            for b in result.by_time_of_day
        ],
        by_day_of_week=[
            TimeBucketOut(
                label=b.label, trades=b.trades, win_rate=b.win_rate,
                avg_pnl=b.avg_pnl, net_pnl=b.net_pnl,
            )
            for b in result.by_day_of_week
        ],
        by_hold_duration=[
            TimeBucketOut(
                label=b.label, trades=b.trades, win_rate=b.win_rate,
                avg_pnl=b.avg_pnl, net_pnl=b.net_pnl,
            )
            for b in result.by_hold_duration
        ],
        by_mistake=[
            MistakeBucketOut(
                tag=b.tag, trades=b.trades, net_pnl=b.net_pnl,
                avg_pnl=b.avg_pnl, total_r=b.total_r,
            )
            for b in result.by_mistake
        ],
        streaks=StreakStatsOut(
            best_win=result.streaks.best_win,
            worst_loss=result.streaks.worst_loss,
            current=result.streaks.current,
            avg_hold_win_min=result.streaks.avg_hold_win_min,
            avg_hold_loss_min=result.streaks.avg_hold_loss_min,
        ),
        equity=EquityCurveOut(
            points=[
                EquityPointOut(date=p.date, cumulative_pnl=p.cumulative_pnl)
                for p in result.equity.points
            ],
            max_drawdown=result.equity.max_drawdown,
            peak_pnl=result.equity.peak_pnl,
            final_pnl=result.equity.final_pnl,
            drawdown_peak_date=result.equity.drawdown_peak_date,
            drawdown_trough_date=result.equity.drawdown_trough_date,
        ),
        risk=RiskBlockOut(
            largest_loss=result.risk.largest_loss,
            worst_day_pnl=result.risk.worst_day_pnl,
            worst_day_date=result.risk.worst_day_date,
            avg_loss=result.risk.avg_loss,
            max_drawdown=result.risk.max_drawdown,
            trail=result.risk.trail,
            days_near_mll=result.risk.days_near_mll,
        ),
        filters=AnalyticsFilters(paper=paper, strategy=strategy, since=since, until=until),
    )


# ---------------------------------------------------------------------------
# WS5 — Monte-Carlo scenario / backtest panel
# ---------------------------------------------------------------------------
#
# Surfaces the dormant simulator behind POST /api/analytics/montecarlo.
# Two modes:
#   * trade_id given → simulate the live open position's terminal P&L.
#   * legs given     → simulate a hypothetical structure (the builder preview).
# Self-contained: no chart/feed dependency; spot/sigma/horizon are supplied
# by the caller (the frontend reads them from the chain/position payload).


class MonteCarloLeg(BaseModel):
    side: Literal["call", "put"]
    action: Literal["buy", "sell"]
    strike: float = Field(gt=0)
    contracts: int = Field(gt=0, le=1000, default=1)
    entry_price: float = Field(ge=0)


class MonteCarloRequest(BaseModel):
    """Either reference an owned open trade (`trade_id`) OR pass explicit
    `legs`. `spot`, `sigma`, `horizon_days` describe the environment; `drift`
    is optional (defaults to the risk-free `rate`)."""

    trade_id: int | None = Field(default=None)
    legs: list[MonteCarloLeg] | None = Field(default=None, min_length=1, max_length=8)
    spot: float = Field(gt=0)
    sigma: float = Field(gt=0, le=5.0)
    horizon_days: float = Field(gt=0, le=365.0)
    rate: float = Field(default=0.0, ge=0, le=1.0)
    drift: float | None = Field(default=None, ge=-1.0, le=1.0)
    paths: int = Field(default=10_000, ge=100, le=200_000)
    seed: int | None = Field(default=None)


class MonteCarloOut(BaseModel):
    paths: int
    horizon_days: float
    spot: float
    sigma: float
    drift: float
    cost_basis: float
    prob_profit: float
    expected_pnl: float
    median_pnl: float
    pnl_p05: float
    pnl_p95: float
    max_simulated_loss: float
    max_simulated_profit: float
    var_95: float
    expected_terminal_price: float
    hist_bin_edges: list[float]
    hist_counts: list[int]
    sample_terminal_prices: list[float]


@router.post("/montecarlo", response_model=MonteCarloOut)
def post_montecarlo(
    payload: MonteCarloRequest,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
) -> MonteCarloOut:
    """Run a terminal-value Monte-Carlo for an open position or a hypothetical
    structure. Position is resolved from the user's own combines (404 on a
    foreign/unknown trade_id). At least one of trade_id / legs is required."""
    if payload.trade_id is not None:
        trade = session.execute(
            select(Trade).where(
                Trade.id == payload.trade_id,
                Trade.combine_id.in_(
                    select(Combine.id).where(Combine.user_id == user.id)
                ),
            )
        ).scalar_one_or_none()
        if trade is None:
            raise HTTPException(404, f"trade {payload.trade_id} not found")
        legs = [
            {
                "side": leg["side"],
                "action": leg["action"],
                "strike": float(leg["strike"]),
                "contracts": int(leg.get("contracts", 1)),
                "entry_price": float(leg["entry_price"]),
            }
            for leg in (trade.legs or [])
        ]
        if not legs:
            raise HTTPException(422, f"trade {payload.trade_id} has no legs to simulate")
    elif payload.legs:
        legs = [leg.model_dump() for leg in payload.legs]
    else:
        raise HTTPException(422, "Provide either trade_id or legs.")

    result = simulate_terminal_pnl(
        legs=legs,
        spot=payload.spot,
        sigma=payload.sigma,
        horizon_days=payload.horizon_days,
        rate=payload.rate,
        drift=payload.drift,
        paths=payload.paths,
        seed=payload.seed,
    )
    return MonteCarloOut(**result.__dict__)
