"""Scheduled order monitor.

Thin scheduler entry point — all logic (and its injectable seams) live in
services/order_monitor.run_order_monitor. Runs every ~20s during market
hours to fill working limit/stop orders and auto-close SL/TP brackets. The
underlying universe is tiny (SPY/QQQ/IWM) and quotes are cached 5s + guarded
by the resilience circuit breaker, so the cadence is cheap.
"""

from __future__ import annotations

import logging

log = logging.getLogger(__name__)


def monitor_orders(session_factory=None) -> dict:
    from services.order_monitor import run_order_monitor

    return run_order_monitor(session_factory=session_factory)
