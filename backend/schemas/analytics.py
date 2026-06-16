"""API schemas for the journal analytics route — mirrors the dataclasses
in calculations/journal_analytics.py."""

from __future__ import annotations

from pydantic import BaseModel, Field


class KpiBlockOut(BaseModel):
    total_trades: int
    open_trades: int
    closed_trades: int
    win_rate: float | None
    net_pnl: float
    profit_factor: float | None       # may be inf when no losers; serialized as null
    avg_winner: float | None
    avg_loser: float | None
    expectancy: float | None
    avg_r: float | None
    largest_winner: float | None
    largest_loser: float | None
    avg_hold_min: float | None


class StrategyBucketOut(BaseModel):
    strategy: str
    trades: int
    closed: int
    win_rate: float | None
    net_pnl: float
    avg_pnl: float | None
    profit_factor: float | None
    avg_r: float | None


class SymbolBucketOut(BaseModel):
    symbol: str
    trades: int
    closed: int
    win_rate: float | None
    net_pnl: float
    avg_pnl: float | None


class TimeBucketOut(BaseModel):
    label: str
    trades: int
    win_rate: float | None
    avg_pnl: float | None
    net_pnl: float


class StreakStatsOut(BaseModel):
    best_win: int
    worst_loss: int
    current: int
    avg_hold_win_min: float | None
    avg_hold_loss_min: float | None


class RiskBlockOut(BaseModel):
    largest_loss: float | None
    worst_day_pnl: float
    worst_day_date: str | None
    avg_loss: float | None
    max_drawdown: float
    trail: float | None
    days_near_mll: int | None


class DteBucketOut(BaseModel):
    label: str
    trades: int
    win_rate: float | None
    avg_pnl: float | None
    net_pnl: float


class MistakeBucketOut(BaseModel):
    tag: str
    trades: int
    net_pnl: float
    avg_pnl: float | None
    total_r: float | None


class EquityPointOut(BaseModel):
    date: str
    cumulative_pnl: float


class EquityCurveOut(BaseModel):
    points: list[EquityPointOut] = Field(default_factory=list)
    max_drawdown: float
    peak_pnl: float
    final_pnl: float
    drawdown_peak_date: str | None = None
    drawdown_trough_date: str | None = None


class AnalyticsResponse(BaseModel):
    kpis: KpiBlockOut
    by_strategy: list[StrategyBucketOut] = Field(default_factory=list)
    by_symbol: list[SymbolBucketOut] = Field(default_factory=list)
    by_dte: list[DteBucketOut] = Field(default_factory=list)
    by_time_of_day: list[TimeBucketOut] = Field(default_factory=list)
    by_day_of_week: list[TimeBucketOut] = Field(default_factory=list)
    by_hold_duration: list[TimeBucketOut] = Field(default_factory=list)
    by_mistake: list[MistakeBucketOut] = Field(default_factory=list)
    streaks: StreakStatsOut
    equity: EquityCurveOut
    risk: RiskBlockOut
    # Pass-through of the filters used so the UI can verify what was
    # computed (and re-issue queries deterministically).
    filters: "AnalyticsFilters"


class AnalyticsFilters(BaseModel):
    paper: bool | None = None
    strategy: str | None = None
    since: str | None = None         # ISO date — exit_date >= since
    until: str | None = None         # ISO date — exit_date <= until


AnalyticsResponse.model_rebuild()
