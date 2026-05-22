"""Hardcoded calendar event sources that don't have a clean free API.

REVIEW THIS FILE PERIODICALLY — these dates are static and will go stale.
- FOMC: Fed publishes the next year's schedule each summer; refresh annually.
- FOMC minutes: only include dates verified directly from federalreserve.gov;
  half-correct dates would be misleading.
- Fed speakers: announced piecemeal — currently empty by design.
"""

from __future__ import annotations

from datetime import date

# ---------------------------------------------------------------------------
# 2026 FOMC schedule
# Source: https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm
# Verified: 2026-05-15
#
# Each meeting is two days. SEP (Summary of Economic Projections) lands on
# the day-2 of the Mar/Jun/Sep/Dec meetings — labeled explicitly because
# traders position differently for those.
# ---------------------------------------------------------------------------

FOMC_MEETINGS_2026: list[tuple[date, str]] = [
    (date(2026, 1, 27), "FOMC Day 1"),
    (date(2026, 1, 28), "FOMC + Powell"),
    (date(2026, 3, 17), "FOMC Day 1"),
    (date(2026, 3, 18), "FOMC + SEP + Powell"),
    (date(2026, 4, 28), "FOMC Day 1"),
    (date(2026, 4, 29), "FOMC + Powell"),
    (date(2026, 6, 16), "FOMC Day 1"),
    (date(2026, 6, 17), "FOMC + SEP + Powell"),
    (date(2026, 7, 28), "FOMC Day 1"),
    (date(2026, 7, 29), "FOMC + Powell"),
    (date(2026, 9, 15), "FOMC Day 1"),
    (date(2026, 9, 16), "FOMC + SEP + Powell"),
    (date(2026, 10, 27), "FOMC Day 1"),
    (date(2026, 10, 28), "FOMC + Powell"),
    (date(2026, 12, 8), "FOMC Day 1"),
    (date(2026, 12, 9), "FOMC + SEP + Powell"),
]

# Only dates verified directly from federalreserve.gov. Do not extrapolate
# heuristically — half-correct minutes dates would be misleading. Add new
# rows as the Fed publishes them.
FOMC_MINUTES_2026: list[tuple[date, str]] = [
    (date(2026, 2, 18), "Jan FOMC minutes"),
    (date(2026, 4, 8), "Mar FOMC minutes"),
]

# Manual best-effort — REVIEW MONTHLY. Empty by design until we have a
# canonical source we trust; ship missing-but-honest over partial-and-suspect.
FED_SPEAKERS_2026: list[tuple[date, str]] = []

# ---------------------------------------------------------------------------
# FRED release name → pill metadata. EXACT-MATCH (case-insensitive after
# whitespace normalization) on `release_name` to avoid the loose-substring
# problem where e.g. "State Unemployment Insurance Weekly Claims Report"
# (id=469, releases Fridays) pollutes the national Initial Claims series
# (id=180, "Unemployment Insurance Weekly Claims Report", releases Thursdays).
# Names verified against /fred/releases/dates 2026-05-15.
#
# NOTE: ISM Manufacturing PMI ("Manufacturing ISM Report On Business") is
# NOT in FRED's release calendar — ISM is a private trade association;
# FRED hosts the data series but doesn't track its release schedule.
# To surface ISM events, we'd need to compute them ourselves (1st business
# day of each month, 10:00 ET) — deferred polish, not in this filter.
# ---------------------------------------------------------------------------

FRED_RELEASE_NAMES: list[tuple[str, str, str]] = [
    # (canonical release_name, label shown on pill, importance)
    ("Consumer Price Index", "CPI", "high"),
    ("Producer Price Index", "PPI", "medium"),
    ("Employment Situation", "NFP", "high"),
    ("Gross Domestic Product", "GDP", "high"),
    ("Advance Monthly Sales for Retail and Food Services", "Retail Sales", "medium"),
    ("Unemployment Insurance Weekly Claims Report", "Jobless Claims", "low"),
]
