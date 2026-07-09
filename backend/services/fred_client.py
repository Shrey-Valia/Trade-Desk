"""Thin FRED client — only the releases-dates endpoint we need today.

We use httpx directly instead of the unmaintained `fredapi` package; only
one endpoint matters for the calendar so the surface area is tiny.

Cached 24h: release schedules don't change intraday.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date

import httpx

from config import settings
from services.cache import cache

log = logging.getLogger(__name__)

_FRED_BASE = "https://api.stlouisfed.org/fred"

# Used by Phase 5 BS pricing. Only kicks in when FRED is unreachable / key
# missing — see latest_dgs3mo_rate(). Hardcoded rates drift silently, so
# this is a fallback, not a default.
DEFAULT_RATE_FALLBACK = 0.045


@dataclass
class FredReleaseDate:
    release_id: int
    release_name: str
    date: date


def releases_dates(start: date, end: date) -> list[FredReleaseDate]:
    """All FRED release dates in [start, end]. Caller filters by name pattern."""
    if not settings.fred_api_key:
        log.warning("FRED_API_KEY not set; returning empty release calendar")
        return []

    cache_key = f"fred:releases_dates:{start.isoformat()}:{end.isoformat()}"
    cached = cache.get(cache_key)
    if cached is not None:
        return cached

    params = {
        "api_key": settings.fred_api_key,
        "file_type": "json",
        "realtime_start": start.isoformat(),
        "realtime_end": end.isoformat(),
        "include_release_dates_with_no_data": "true",
        "limit": 1000,
        "sort_order": "asc",
    }
    try:
        with httpx.Client(timeout=10.0) as client:
            r = client.get(f"{_FRED_BASE}/releases/dates", params=params)
            r.raise_for_status()
            payload = r.json()
    except Exception as exc:  # noqa: BLE001
        log.warning("FRED releases/dates fetch failed: %s", exc)
        cache.set(cache_key, [], ttl_seconds=300)
        return []

    rows = payload.get("release_dates", [])
    out: list[FredReleaseDate] = []
    for row in rows:
        try:
            out.append(
                FredReleaseDate(
                    release_id=int(row["release_id"]),
                    release_name=str(row["release_name"]),
                    date=date.fromisoformat(row["date"]),
                )
            )
        except (KeyError, ValueError, TypeError):
            continue

    cache.set(cache_key, out, ttl_seconds=86400)
    return out


def vix_history(start: date, end: date) -> dict[date, float]:
    """VIX daily closes via FRED VIXCLS series. 24h cache.

    Returns {date: close}. Empty dict on any failure — caller treats
    missing VIX as "drop the VIX features and proceed with 5".
    Verified working on FRED 2026-05-15; Alpaca free tier rejects ^VIX/VIX.
    """
    cache_key = f"fred:vixcls:{start.isoformat()}:{end.isoformat()}"
    cached = cache.get(cache_key)
    if cached is not None:
        return cached

    if not settings.fred_api_key:
        log.warning("FRED_API_KEY not set; VIX history unavailable")
        return {}

    params = {
        "api_key": settings.fred_api_key,
        "file_type": "json",
        "series_id": "VIXCLS",
        "observation_start": start.isoformat(),
        "observation_end": end.isoformat(),
        "limit": 100000,
    }
    try:
        with httpx.Client(timeout=30.0) as client:
            r = client.get(f"{_FRED_BASE}/series/observations", params=params)
            r.raise_for_status()
            payload = r.json()
    except Exception as exc:  # noqa: BLE001
        log.warning("FRED VIXCLS fetch failed: %s", exc)
        return {}

    out: dict[date, float] = {}
    for o in payload.get("observations", []):
        raw = o.get("value")
        if not raw or raw == ".":
            continue
        try:
            out[date.fromisoformat(o["date"])] = float(raw)
        except (KeyError, ValueError):
            continue
    cache.set(cache_key, out, ttl_seconds=86400)
    return out


def latest_dgs3mo_rate() -> float:
    """Latest 3-month Treasury constant maturity rate as a decimal (e.g. 0.045).

    Used as the risk-free rate in Black-Scholes pricing. 24h cache. Falls
    back to DEFAULT_RATE_FALLBACK with a logged warning when FRED is
    unreachable or the API key is missing.
    """
    cache_key = "fred:dgs3mo"
    cached = cache.get(cache_key)
    if cached is not None:
        return cached

    if not settings.fred_api_key:
        log.warning("FRED_API_KEY not set; using fallback rate %s", DEFAULT_RATE_FALLBACK)
        return DEFAULT_RATE_FALLBACK

    params = {
        "api_key": settings.fred_api_key,
        "file_type": "json",
        "series_id": "DGS3MO",
        "limit": 10,
        "sort_order": "desc",
    }
    try:
        with httpx.Client(timeout=10.0) as client:
            r = client.get(f"{_FRED_BASE}/series/observations", params=params)
            r.raise_for_status()
            payload = r.json()
    except Exception as exc:  # noqa: BLE001
        log.warning("FRED DGS3MO fetch failed: %s; using fallback %s", exc, DEFAULT_RATE_FALLBACK)
        # NEGATIVE-CACHE the fallback for a short window. latest_dgs3mo_rate is
        # called per-trade per-tick by the order monitor; without this, a FRED
        # outage means every tick makes a fresh 10s httpx call on the scheduler
        # thread, stretching a sweep toward minutes and delaying every bracket /
        # liquidation check. 5 min balances "don't hammer a down dependency"
        # against "recover reasonably quickly once FRED is back".
        cache.set(cache_key, DEFAULT_RATE_FALLBACK, ttl_seconds=300)
        return DEFAULT_RATE_FALLBACK

    # FRED uses "." for missing observations on holidays; walk newest-first
    # until we find a usable value.
    for o in payload.get("observations", []):
        raw = o.get("value")
        if not raw or raw == ".":
            continue
        try:
            rate = float(raw) / 100.0
        except ValueError:
            continue
        cache.set(cache_key, rate, ttl_seconds=86400)
        return rate

    log.warning("FRED DGS3MO returned no usable observations; using fallback")
    return DEFAULT_RATE_FALLBACK
