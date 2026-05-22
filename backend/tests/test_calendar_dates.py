"""Calendar date-helper correctness."""

from datetime import date

from calculations.calendar_dates import (
    ism_manufacturing_date,
    ism_services_date,
    is_monthly_opex,
    is_quad_witching,
    next_trading_days,
    nth_trading_day_of_month,
    third_friday,
)


def test_third_friday_known_dates():
    assert third_friday(2026, 1) == date(2026, 1, 16)
    assert third_friday(2026, 3) == date(2026, 3, 20)
    assert third_friday(2026, 5) == date(2026, 5, 15)
    assert third_friday(2026, 12) == date(2026, 12, 18)


def test_third_friday_when_first_is_friday():
    # May 2026: 1st is a Friday → third Friday is the 15th.
    assert third_friday(2026, 5) == date(2026, 5, 15)


def test_is_monthly_opex_true_on_third_friday():
    assert is_monthly_opex(date(2026, 5, 15)) is True
    assert is_monthly_opex(date(2026, 5, 22)) is False  # 4th Friday
    assert is_monthly_opex(date(2026, 5, 8)) is False   # 2nd Friday


def test_is_quad_witching_only_on_quarter_end_third_fridays():
    assert is_quad_witching(date(2026, 3, 20)) is True   # March
    assert is_quad_witching(date(2026, 6, 19)) is True   # June
    assert is_quad_witching(date(2026, 9, 18)) is True   # September
    assert is_quad_witching(date(2026, 12, 18)) is True  # December
    # Non-quarter months that are still monthly OPEX
    assert is_quad_witching(date(2026, 5, 15)) is False
    assert is_quad_witching(date(2026, 7, 17)) is False


def test_quad_witching_implies_monthly_opex():
    # If quad witching is true, monthly OPEX must also be true — check
    # callers that label opex have to test quad first.
    for m in (3, 6, 9, 12):
        d = third_friday(2026, m)
        assert is_quad_witching(d)
        assert is_monthly_opex(d)


def test_next_trading_days_skips_weekend():
    # Saturday 2026-05-16 → first trading day in result should be Mon 2026-05-18.
    sessions = next_trading_days(date(2026, 5, 16), 3)
    assert sessions[0] == date(2026, 5, 18)
    # Sequential, no Sat/Sun.
    for d in sessions:
        assert d.weekday() < 5


def test_next_trading_days_includes_today_if_weekday():
    # Friday 2026-05-15 is a regular session.
    sessions = next_trading_days(date(2026, 5, 15), 5)
    assert sessions[0] == date(2026, 5, 15)
    assert len(sessions) == 5


def test_next_trading_days_skips_independence_day_weekend():
    # July 4, 2026 is a Saturday → market is closed on Friday July 3 (observed).
    # Starting from Wed July 1, the next 3 sessions should be 7/1, 7/2, 7/6.
    sessions = next_trading_days(date(2026, 7, 1), 3)
    assert sessions == [date(2026, 7, 1), date(2026, 7, 2), date(2026, 7, 6)]


# ---------- ISM dates ----------


def test_ism_normal_month_may_2026():
    # May 1 2026 is a Friday (regular session) → Mfg = 5/1, Svc = 5/5 (Tue).
    assert ism_manufacturing_date(2026, 5) == date(2026, 5, 1)
    assert ism_services_date(2026, 5) == date(2026, 5, 5)


def test_ism_month_starting_on_weekend_aug_2026():
    # Aug 1 2026 is a Saturday → Mfg shifts to Mon 8/3, Svc to Wed 8/5.
    assert ism_manufacturing_date(2026, 8) == date(2026, 8, 3)
    assert ism_services_date(2026, 8) == date(2026, 8, 5)


def test_ism_month_starting_on_holiday_jan_2027():
    # Jan 1 2027 is a Friday but NYSE is closed for New Year's →
    # 1st trading day is Mon Jan 4. Svc = 3rd trading day = Wed Jan 6.
    assert ism_manufacturing_date(2027, 1) == date(2027, 1, 4)
    assert ism_services_date(2027, 1) == date(2027, 1, 6)


def test_nth_trading_day_returns_none_when_n_too_large():
    # No month has 50 trading days.
    assert nth_trading_day_of_month(2026, 5, 50) is None
