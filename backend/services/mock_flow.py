"""Mock options-sweep flow.

Stand-in for a real unusual-flow provider (Unusual Whales, Cheddar Flow,
etc.). Generates deterministic-but-varied sweep records keyed on
(symbol, ET date) so the demo is stable within a session but moves
across tickers. Every record carries `is_mock=True` so the UI can be
honest about it — see schemas/signal.py and MockFlowBanner.tsx.

When real flow data is purchased, this module gets swapped for a real
client implementing the same `get_mock_sweeps(symbol) -> list[Sweep]`
signature. The signal composer will not need to change.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Literal
from zoneinfo import ZoneInfo

from sqlalchemy import select

from database import SessionLocal
from models.watchlist_item import WatchlistItem

_ET = ZoneInfo("America/New_York")

# Names appearing in the live "unusual_options" category get a larger
# expected sweep count — that's the bias real flow data would have if
# it agreed with our heuristic. Ratio bands tune the per-ticker count.
_UNUSUAL_SWEEP_RANGE = (2, 3)   # inclusive
_DEFAULT_SWEEP_RANGE = (0, 1)


Side = Literal["call", "put"]
Aggressor = Literal["bid", "ask"]


@dataclass
class Sweep:
    """One option-sweep print. Mirrors the real-flow record shape so the
    interface doesn't change when we swap in a real provider."""

    strike: float
    expiry: str             # ISO date
    side: Side
    premium: float          # total $ premium across the sweep
    contracts: int
    aggressor: Aggressor
    timestamp: str          # ISO timestamp, ET
    is_mock: bool = True


def get_mock_sweeps(
    symbol: str,
    *,
    today: date | None = None,
    spot: float | None = None,
) -> list[Sweep]:
    """Deterministic sweep list for `symbol` on `today`.

    Re-running on the same day for the same ticker returns the same list.
    `spot` lets the caller anchor strikes near the real price; without
    it strikes round to a placeholder ladder so the data is still
    structurally usable.
    """
    today = today or datetime.now(_ET).date()
    seed = _seed(symbol, today)
    rng = _DeterministicRandom(seed)

    is_unusual = _symbol_is_unusual(symbol)
    lo, hi = _UNUSUAL_SWEEP_RANGE if is_unusual else _DEFAULT_SWEEP_RANGE
    n_sweeps = rng.randint(lo, hi)
    if n_sweeps == 0:
        return []

    # Pin expiry to the next monthly-ish Friday (today + 7-35 days).
    expiry = _pick_expiry(today, rng)
    anchor = spot if spot is not None else 100.0

    sweeps: list[Sweep] = []
    for _ in range(n_sweeps):
        side: Side = "call" if rng.random() > 0.45 else "put"
        # Strike: ATM ± a small ladder. Calls tend to OTM, puts tend ITM-ish
        # — matches the bullish-skew flow pattern real sweep feeds show.
        offset_pct = rng.uniform(-0.05, 0.10) if side == "call" else rng.uniform(-0.10, 0.05)
        strike = round(anchor * (1 + offset_pct), 2)
        contracts = rng.randint(250, 5000)
        # Premium per contract: rough $ amount that scales with how OTM.
        unit_premium = max(0.10, anchor * (0.01 + 0.02 * (1 - abs(offset_pct))))
        premium = round(unit_premium * contracts * 100, 0)  # ×100 multiplier
        aggressor: Aggressor = "ask" if rng.random() > 0.35 else "bid"
        ts_offset_minutes = rng.randint(0, 390)  # within the trading day
        ts = datetime.combine(today, datetime.min.time(), tzinfo=_ET) + timedelta(
            hours=9, minutes=30 + ts_offset_minutes
        )
        sweeps.append(
            Sweep(
                strike=strike,
                expiry=expiry.isoformat(),
                side=side,
                premium=premium,
                contracts=contracts,
                aggressor=aggressor,
                timestamp=ts.isoformat(),
            )
        )

    # Sort newest first — matches how real flow feeds present.
    sweeps.sort(key=lambda s: s.timestamp, reverse=True)
    return sweeps


def directional_bias(sweeps: list[Sweep]) -> tuple[str, float] | None:
    """Aggregate a sweep list into a single (direction, strength) reading.

    Returns:
        ("bullish", 0..1) when call premium dominates and was lifted at ask.
        ("bearish", 0..1) when put premium dominates.
        None when sweeps are empty or balanced (no edge to surface).
    """
    if not sweeps:
        return None

    bull_score = 0.0
    bear_score = 0.0
    for s in sweeps:
        # Aggressor at ask = directional conviction; at bid = the opposite.
        weight = s.premium * (1.0 if s.aggressor == "ask" else 0.4)
        if s.side == "call":
            bull_score += weight
        else:
            bear_score += weight

    total = bull_score + bear_score
    if total <= 0:
        return None
    bull_pct = bull_score / total
    if 0.45 <= bull_pct <= 0.55:
        return None  # too balanced to call

    direction = "bullish" if bull_pct > 0.55 else "bearish"
    strength = round(abs(bull_pct - 0.5) * 2, 2)  # 0 at 50/50 → 1 at 100/0
    return direction, strength


# -- internals --------------------------------------------------------------


def _symbol_is_unusual(symbol: str) -> bool:
    """True when `symbol` currently sits in the watchlist's unusual_options
    bucket. Falls back to False on any error — we never want a DB hiccup
    to invent fake "unusual" flow."""
    try:
        with SessionLocal() as session:
            row = session.execute(
                select(WatchlistItem.symbol)
                .where(WatchlistItem.category == "unusual_options")
                .where(WatchlistItem.symbol == symbol.upper())
                .limit(1)
            ).first()
            return row is not None
    except Exception:  # noqa: BLE001
        return False


def _seed(symbol: str, today: date) -> int:
    """Stable per (symbol, day) — same inputs give the same int every call."""
    raw = f"{symbol.upper()}|{today.isoformat()}".encode()
    digest = hashlib.sha256(raw).digest()
    return int.from_bytes(digest[:8], "big", signed=False)


def _pick_expiry(today: date, rng: "_DeterministicRandom") -> date:
    """Next Friday at least 7 days out, capped at ~35 days."""
    target = today + timedelta(days=rng.randint(7, 35))
    # Roll to the next Friday so it looks like a real options expiry.
    while target.weekday() != 4:
        target += timedelta(days=1)
    return target


class _DeterministicRandom:
    """Tiny LCG seeded from sha256 — we don't pull stdlib `random` so the
    sequence stays stable even if Python's PRNG changes across versions."""

    __slots__ = ("_state",)

    def __init__(self, seed: int) -> None:
        # 64-bit LCG (Knuth's constants). Adequate for stable mock data.
        self._state = seed & ((1 << 64) - 1)

    def _next(self) -> int:
        self._state = (self._state * 6364136223846793005 + 1442695040888963407) & ((1 << 64) - 1)
        return self._state

    def random(self) -> float:
        return (self._next() >> 11) / float(1 << 53)

    def randint(self, lo: int, hi: int) -> int:
        if hi < lo:
            return lo
        span = hi - lo + 1
        return lo + int(self.random() * span) % span

    def uniform(self, lo: float, hi: float) -> float:
        return lo + (hi - lo) * self.random()


__all__ = ["Sweep", "get_mock_sweeps", "directional_bias"]
# Ensure `datetime`/`timezone` imports aren't trimmed in case a downstream
# module needs them through us (e.g. tests). No runtime effect.
_ = (datetime, timezone)
