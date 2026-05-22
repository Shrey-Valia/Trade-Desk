"""Put/call volume ratio."""

from __future__ import annotations


def pc_ratio(call_volume: int, put_volume: int) -> float | None:
    """Today's put / call volume. Returns None when call_volume is 0."""
    if call_volume <= 0:
        return None
    return put_volume / call_volume
