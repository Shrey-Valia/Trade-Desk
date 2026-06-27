"""Money handling — exact 2-decimal storage without float drift.

THE P0: money columns were `FLOAT`, so summing many small slice-outs / payouts
accumulated binary-floating-point error (e.g. 0.1 + 0.2 ≠ 0.3). Storing dollars
as `NUMERIC(12, 2)` makes the on-disk value EXACT to the cent.

THE BOUNDARY DECISION (read this before touching any money path):

  We keep the Python compute layer in `float` exactly as it was, and quantize to
  a 2-decimal `Decimal` ONLY at the storage boundary. Concretely the money
  columns use the `Money` TypeDecorator below, which:

    * on WRITE  — quantizes the bound value to 2dp (ROUND_HALF_UP) and stores it
      as an exact `Decimal` in a `NUMERIC(12, 2)` column, and
    * on READ   — converts the `Decimal` the DB returns BACK to `float`.

  So every existing read path (`float(r[0] or 0.0)`, `t.realized_pnl + …`,
  every `round(x, 2)`) is byte-for-byte unchanged — the type hands Python a
  `float`, never a `Decimal`, so float math can't accidentally mix with Decimal
  and blow up with a TypeError. The ONLY behavioural change is that the value
  that round-trips through the DB is now exact to the cent instead of the
  nearest float, which is the whole point.

  Why not thread `Decimal` end-to-end? It would touch ~45 arithmetic sites
  across routers/services/jobs and every one is a place a stray `float` (a live
  Alpaca mark, a commission rate, a slippage term) could mix with a `Decimal`
  and raise at runtime. Quantizing at the boundary gets the exact-storage
  guarantee with a near-zero blast radius on the compute layer. The cost is that
  intermediate Python arithmetic is still float — acceptable because every
  storage write already calls `round(x, 2)`, so the only values that persist are
  already cent-quantized; `Money` just makes the persistence itself exact and
  re-quantizes defensively in case a caller forgot the round().

`create_all` on a fresh DB (incl. the Postgres CI leg) picks up `NUMERIC(12,2)`
directly from the column type; an idempotent ALTER in database.py widens the
type on an existing Postgres DB. SQLite is typeless (its NUMERIC affinity stores
the bound value as-is), so the ALTER is a guarded no-op there.
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

from sqlalchemy import Numeric
from sqlalchemy.types import TypeDecorator

# All dollar amounts quantize to this. Two decimal places = cents.
_CENT = Decimal("0.01")

# Width chosen to comfortably hold the largest amount the app can produce: a
# 150K combine's HWM/balance plus headroom. 12 digits total, 2 after the point
# → up to 9,999,999,999.99, far above any realistic account value.
MONEY_PRECISION = 12
MONEY_SCALE = 2


def quantize_money(value: float | int | Decimal | str | None) -> Decimal | None:
    """Round `value` to an exact 2dp Decimal (ROUND_HALF_UP, the everyday
    "round half up" most people expect for money). None passes through (NULL
    money columns — e.g. an open trade's realized_pnl — stay NULL).

    Floats are routed through `str()` first so we quantize the DECIMAL the user
    sees (0.1) rather than its binary-float shadow (0.1000000000000000055…),
    which keeps half-way cases rounding the intuitive direction."""
    if value is None:
        return None
    if isinstance(value, Decimal):
        dec = value
    elif isinstance(value, float):
        dec = Decimal(str(value))
    else:
        # int / str
        try:
            dec = Decimal(value)
        except (InvalidOperation, TypeError, ValueError) as exc:  # pragma: no cover
            raise ValueError(f"not a money value: {value!r}") from exc
    return dec.quantize(_CENT, rounding=ROUND_HALF_UP)


def to_float(value: float | int | Decimal | None) -> float | None:
    """Coerce a money value (Decimal from a NUMERIC read, or a float) to float.
    None passes through. Used where a serializer or further float math wants a
    plain float regardless of which backend produced the value."""
    if value is None:
        return None
    return float(value)


class Money(TypeDecorator):
    """A dollar column: stored EXACT as ``NUMERIC(12, 2)``, handed to Python as
    ``float``.

    - WRITE: ``process_bind_param`` quantizes to 2dp so the persisted value is
      exact to the cent (and re-quantizes defensively even if the caller already
      ``round()``-ed).
    - READ: ``process_result_value`` converts the ``Decimal`` the DBAPI returns
      back to ``float`` so every existing compute path sees the same type it
      always did — no float/Decimal mixing anywhere downstream.

    ``cache_ok`` is safe: the type carries no per-instance state.
    """

    impl = Numeric(MONEY_PRECISION, MONEY_SCALE)
    cache_ok = True

    def process_bind_param(self, value, dialect):
        return quantize_money(value)

    def process_result_value(self, value, dialect):
        return to_float(value)
