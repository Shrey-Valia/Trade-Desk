"""GET /api/calendar — 7-trading-day strip with mixed event types.

Earnings come from the cached Finnhub 30-day payload (zero new API calls
versus what the watchlist already pulled). FOMC + minutes + Fed speakers
are hardcoded constants. FRED supplies economic releases. OPEX / quad
witching are computed from the third-Friday rule.
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from fastapi import APIRouter

from calculations.calendar_dates import (
    ism_manufacturing_date,
    ism_services_date,
    is_monthly_opex,
    is_quad_witching,
    next_trading_days,
)
from config import settings
from schemas.calendar import CalendarDay, CalendarEvent, CalendarResponse
from services.cache import cache
from services.calendar_constants import (
    FED_SPEAKERS_2026,
    FOMC_MEETINGS_2026,
    FOMC_MINUTES_2026,
    FRED_RELEASE_NAMES,
)
from services.finnhub_client import earnings_calendar
from services.fred_client import releases_dates

router = APIRouter(prefix="/api", tags=["calendar"])
log = logging.getLogger(__name__)

_ET = ZoneInfo("America/New_York")
_DAYS = 7


@router.get("/calendar", response_model=CalendarResponse)
def get_calendar() -> CalendarResponse:
    cache_key = "calendar:v1"
    cached = cache.get(cache_key)
    if cached is not None:
        return cached

    today_et = datetime.now(_ET).date()
    sessions = next_trading_days(today_et, _DAYS)
    if not sessions:
        return CalendarResponse(days=[], notes=_notes())

    window_start, window_end = sessions[0], sessions[-1]

    earnings_events = _earnings_events(window_start, window_end)
    fomc_events = _static_events(FOMC_MEETINGS_2026, "fomc", importance="high")
    minutes_events = _static_events(FOMC_MINUTES_2026, "fomc_minutes", importance="medium")
    speaker_events = _static_events(FED_SPEAKERS_2026, "fed_speak", importance="low")
    economic_events = _fred_events(window_start, window_end)
    ism_events = _ism_events(sessions)

    by_date: dict[date, list[CalendarEvent]] = {}
    for d, evs in [
        *earnings_events.items(),
        *fomc_events.items(),
        *minutes_events.items(),
        *speaker_events.items(),
        *economic_events.items(),
        *ism_events.items(),
    ]:
        by_date.setdefault(d, []).extend(evs)

    # OPEX / quad witching — computed per visible session.
    for d in sessions:
        if is_quad_witching(d):
            by_date.setdefault(d, []).append(
                CalendarEvent(type="quad_witching", title="Quad Witching", importance="high")
            )
        elif is_monthly_opex(d):
            by_date.setdefault(d, []).append(
                CalendarEvent(type="opex", title="Monthly OPEX", importance="medium")
            )

    days = [
        CalendarDay(
            date=d.isoformat(),
            is_today=(d == today_et),
            events=by_date.get(d, []),
        )
        for d in sessions
    ]

    response = CalendarResponse(days=days, notes=_notes())
    cache.set(cache_key, response, ttl_seconds=3600)  # 1h
    return response


def _notes() -> dict[str, str]:
    notes: dict[str, str] = {}
    if not FED_SPEAKERS_2026:
        notes["fed_speakers"] = "Fed speaker data: manual upkeep, currently empty"
    return notes


def _earnings_events(start: date, end: date) -> dict[date, list[CalendarEvent]]:
    out: dict[date, list[CalendarEvent]] = {}
    try:
        rows = earnings_calendar(days_forward=30)
    except Exception:
        log.exception("calendar: earnings_calendar failed")
        return out

    universe = set(settings.watchlist_universe)
    for row in rows:
        if row.symbol not in universe:
            continue
        try:
            d = date.fromisoformat(row.date)
        except ValueError:
            continue
        if not (start <= d <= end):
            continue
        hour = (row.hour or "").lower()
        suffix = {"bmo": " BMO", "amc": " AMC"}.get(hour, "")
        out.setdefault(d, []).append(
            CalendarEvent(
                type="earnings",
                title=f"{row.symbol} ER{suffix}",
                ticker=row.symbol,
                importance="high",
            )
        )
    return out


def _static_events(
    rows: list[tuple[date, str]], event_type: str, *, importance: str
) -> dict[date, list[CalendarEvent]]:
    out: dict[date, list[CalendarEvent]] = {}
    for d, title in rows:
        out.setdefault(d, []).append(
            CalendarEvent(type=event_type, title=title, importance=importance)  # type: ignore[arg-type]
        )
    return out


def _ism_events(sessions: list[date]) -> dict[date, list[CalendarEvent]]:
    """ISM Manufacturing + Services PMI release dates within the visible window.

    Computed (not from FRED) — ISM is a private trade association whose
    release calendar isn't in /fred/releases/dates. Same engineering
    pattern as OPEX: per-month computation, surfaced only on days that
    fall inside the window.
    """
    out: dict[date, list[CalendarEvent]] = {}
    if not sessions:
        return out
    session_set = set(sessions)
    months = {(s.year, s.month) for s in sessions}
    for year, month in months:
        mfg = ism_manufacturing_date(year, month)
        svc = ism_services_date(year, month)
        if mfg is not None and mfg in session_set:
            out.setdefault(mfg, []).append(
                CalendarEvent(type="economic", title="ISM Mfg", importance="high")
            )
        if svc is not None and svc in session_set:
            out.setdefault(svc, []).append(
                CalendarEvent(type="economic", title="ISM Svc", importance="medium")
            )
    return out


def _fred_events(start: date, end: date) -> dict[date, list[CalendarEvent]]:
    out: dict[date, list[CalendarEvent]] = {}
    # FRED's realtime window must include the dates we're interested in.
    # Pad ±1 day for any timezone-edge quirks in their response.
    rows = releases_dates(start - timedelta(days=1), end + timedelta(days=1))
    # Exact match — case + whitespace normalized. Avoids hitting state-level
    # / regional / "Selected ..." variants that share substrings with the
    # canonical national releases. See calendar_constants for the rationale.
    canonical = {name.strip().lower(): (label, importance) for name, label, importance in FRED_RELEASE_NAMES}
    for row in rows:
        if not (start <= row.date <= end):
            continue
        match = canonical.get(row.release_name.strip().lower())
        if match is None:
            continue
        label, importance = match
        out.setdefault(row.date, []).append(
            CalendarEvent(
                type="economic",
                title=label,
                importance=importance,  # type: ignore[arg-type]
            )
        )
    return out
