"""GET /api/analytics — cross-trade aggregations for the analytics tab.

Filters at the API boundary: paper/live, strategy, since/until on
exit_date. Computation lives in calculations/journal_analytics.py;
this router is glue + serialization.
"""

from __future__ import annotations

import logging
import math
from datetime import date, datetime, time, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from calculations.journal_analytics import compose
from database import get_session
from models.combine import Combine
from models.trade import Trade
from models.user import User
from services.auth import get_current_user
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
        owned = session.execute(
            select(Combine.id).where(
                Combine.id == combine_id, Combine.user_id == user.id
            )
        ).scalar_one_or_none()
        if owned is None:
            raise HTTPException(404, f"combine {combine_id} not found")
        stmt = stmt.where(Trade.combine_id == combine_id)
    if paper is not None:
        stmt = stmt.where(Trade.is_paper == paper)
    if strategy:
        stmt = stmt.where(Trade.strategy == strategy.lower())
    if since:
        try:
            d = date.fromisoformat(since)
            stmt = stmt.where(
                Trade.exit_date >= datetime.combine(d, time.min, tzinfo=timezone.utc)
            )
        except ValueError:
            pass
    if until:
        try:
            d = date.fromisoformat(until)
            stmt = stmt.where(
                Trade.exit_date <= datetime.combine(d, time.max, tzinfo=timezone.utc)
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
