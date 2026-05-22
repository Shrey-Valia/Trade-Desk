"""Shared dataclasses for the calculations layer.

Calcs accept these primitive shapes — never Alpaca SDK objects directly —
so they're trivially testable and decoupled from data-source quirks.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date


@dataclass
class ContractRow:
    """One option contract's fields needed across the calc layer.

    Any of `iv`, `delta`, `gamma`, `volume`, `open_interest` may be None
    when the data feed doesn't provide them — calcs filter as needed.
    """

    strike: float
    expiry: date
    type: str  # "call" or "put"
    iv: float | None = None
    delta: float | None = None
    gamma: float | None = None
    volume: int | None = None
    open_interest: int | None = None
    bid: float | None = None
    ask: float | None = None
    last: float | None = None
