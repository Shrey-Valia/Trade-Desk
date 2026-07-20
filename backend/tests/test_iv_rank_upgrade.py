"""Self-upgrading IV metric — percentile proxy until 252d, then TRUE rank.

The audit flagged a 60-day percentile silently labeled "IVR" as dishonest
decision support: the status string now names the basis until the real
range-position rank has a full year of history behind it.
"""

from __future__ import annotations

import pytest

from routers.ticker import _IV_HISTORY_WINDOW, _IV_RANK_WINDOW, _iv_rank_with_status


def _pin_history(monkeypatch, values):
    monkeypatch.setattr("routers.ticker._historical_iv30", lambda sym: values)


def test_no_iv_short_circuits(monkeypatch):
    _pin_history(monkeypatch, [0.2] * 300)
    assert _iv_rank_with_status("SPY", None) == (None, "no IV available")


def test_under_60_days_still_collecting(monkeypatch):
    _pin_history(monkeypatch, [0.2] * 30)
    value, status = _iv_rank_with_status("SPY", 0.25)
    assert value is None
    assert status == f"30/{_IV_HISTORY_WINDOW} days collected"


def test_between_60_and_252_serves_percentile_and_says_so(monkeypatch):
    history = [0.10 + i * 0.001 for i in range(100)]  # 0.10 … 0.199
    _pin_history(monkeypatch, history)
    value, status = _iv_rank_with_status("SPY", 0.15)
    # Percentile: 50 of 100 readings sit strictly below 0.15.
    assert value == pytest.approx(50.0)
    assert status == f"percentile · 100/{_IV_RANK_WINDOW}d to rank"


def test_at_252_days_serves_true_rank_with_no_caveat(monkeypatch):
    # Range 0.10–0.30 over the last 252 readings → 0.20 ranks at 50.
    history = [0.5] * 40 + [0.10 + (i % 253) * (0.20 / 252) for i in range(252)]
    _pin_history(monkeypatch, history)
    value, status = _iv_rank_with_status("SPY", 0.20)
    assert status is None
    # True RANK is range position — only the LAST 252 readings count (the
    # 0.5 outliers before the window must not stretch the range).
    assert value == pytest.approx(50.0, abs=1.0)
