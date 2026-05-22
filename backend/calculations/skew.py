"""25-delta skew: how much more puts cost than calls at equivalent moneyness."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import date

from calculations.types import ContractRow


def skew_25d(chain: Iterable[ContractRow], expiry: date) -> float | None:
    """OTM-put IV minus OTM-call IV at ~25Δ. Positive = put skew (downside fear).

    Per README §10: take puts with delta ∈ [-0.30, -0.20] and calls with
    delta ∈ [0.20, 0.30], average IVs on each side, return the difference.
    Returns None when either side has no qualifying contracts with IV.
    """
    same_expiry = [c for c in chain if c.expiry == expiry]
    if not same_expiry:
        return None

    put_ivs = [
        c.iv
        for c in same_expiry
        if c.type == "put"
        and c.delta is not None
        and -0.30 <= c.delta <= -0.20
        and c.iv is not None
    ]
    call_ivs = [
        c.iv
        for c in same_expiry
        if c.type == "call"
        and c.delta is not None
        and 0.20 <= c.delta <= 0.30
        and c.iv is not None
    ]
    if not put_ivs or not call_ivs:
        return None

    return sum(put_ivs) / len(put_ivs) - sum(call_ivs) / len(call_ivs)
