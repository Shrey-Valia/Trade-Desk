"""API schema for the journal P&L calendar — mirrors the dataclasses
in calculations/journal_calendar.py."""

from __future__ import annotations

from pydantic import BaseModel, Field


class CalendarDayOut(BaseModel):
    date: str
    in_month: bool
    realized_pnl: float
    trade_count: int
    trade_ids: list[int] = Field(default_factory=list)
    is_today: bool = False


class CalendarWeekOut(BaseModel):
    week_of_month: int
    days: list[CalendarDayOut]
    realized_pnl: float
    trade_count: int


class CalendarMonthOut(BaseModel):
    month: str
    label: str
    weeks: list[CalendarWeekOut]
    realized_pnl: float
    trade_count: int
