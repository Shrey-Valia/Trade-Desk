"""Typed accessors over the platform_state KV table.

Generic get/set for JSON values (watermarks, small operational flags) plus
the trading-mode helpers behind the operator kill switch. Deliberately
DB-only — no market-data dependency, so the switch works exactly when the
data feed is the thing that broke.
"""

from __future__ import annotations

import json

from sqlalchemy.orm import Session

from models.platform_state import PlatformState

# Operator kill switch states (services consumed by zerodte/_require_tradeable
# and order_monitor entry-fill paths — workstream B5):
#   normal      — no restriction (default)
#   close_only  — opens refused, closes allowed (wind-down mode)
#   halted      — all new executions refused (incident mode)
TRADING_MODES = ("normal", "close_only", "halted")

KEY_TRADING_MODE = "trading_mode"
KEY_BANNED_SYMBOLS = "banned_symbols"


def get_value(db: Session, key: str, default=None):
    row = db.get(PlatformState, key)
    if row is None:
        return default
    try:
        value = json.loads(row.value_json)
    except (ValueError, TypeError):
        return default
    return default if value is None else value


def set_value(db: Session, key: str, value, *, commit: bool = True) -> None:
    """Upsert one key. Commits by default — callers treat platform state as
    its own small transaction (an operator flip must land even if a
    surrounding request later fails). Pass ``commit=False`` when the caller
    needs to bundle the write with other rows (e.g. a kill-switch flip that
    must land atomically with its audit row) and will commit once itself."""
    row = db.get(PlatformState, key)
    if row is None:
        row = PlatformState(key=key)
        db.add(row)
    row.value_json = json.dumps(value)
    if commit:
        db.commit()


def get_trading_mode(db: Session) -> str:
    mode = get_value(db, KEY_TRADING_MODE, "normal")
    return mode if mode in TRADING_MODES else "normal"


def set_trading_mode(db: Session, mode: str, *, commit: bool = True) -> None:
    if mode not in TRADING_MODES:
        raise ValueError(f"unknown trading mode {mode!r}")
    set_value(db, KEY_TRADING_MODE, mode, commit=commit)


def get_banned_symbols(db: Session) -> set[str]:
    raw = get_value(db, KEY_BANNED_SYMBOLS, [])
    if not isinstance(raw, list):
        return set()
    return {str(s).upper() for s in raw}


def set_banned_symbols(
    db: Session, symbols: list[str], *, commit: bool = True
) -> None:
    set_value(
        db, KEY_BANNED_SYMBOLS, sorted({str(s).upper() for s in symbols}), commit=commit
    )


def platform_status(db: Session) -> dict:
    """One-call snapshot of the operator kill switch for the admin console
    (GET /api/admin/platform, workstream C2): the current trading mode plus
    the sorted per-symbol ban list. JSON-ready."""
    return {
        "trading_mode": get_trading_mode(db),
        "banned_symbols": sorted(get_banned_symbols(db)),
    }
