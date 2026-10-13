"""Unit tests for attendance rules (no MongoDB required)."""
from datetime import datetime, timezone

from app.main import (
    attendance_date_for_punch,
    compute_half_day,
    compute_late_minutes,
    compute_overtime_minutes,
    compute_work_hours,
    round_half_up,
    working_days_in_month,
)

IST = timezone.utc  # instants below are UTC equivalents of IST wall times


def ist_to_utc(y, m, d, hh, mm, ss=0):
    # wall clock in IST -> UTC instant (IST = UTC+5:30)
    from datetime import timedelta, timezone as tz

    ist = tz(timedelta(hours=5, minutes=30))
    return datetime(y, m, d, hh, mm, ss, tzinfo=ist).astimezone(timezone.utc)


def test_late_grace_boundary():
    pin = ist_to_utc(2026, 7, 6, 9, 40, 0)
    assert compute_late_minutes(pin, "2026-07-06", "09:30") == 0
    pin2 = ist_to_utc(2026, 7, 6, 9, 40, 1)
    assert compute_late_minutes(pin2, "2026-07-06", "09:30") == 10


def test_work_hours_half_up():
    pin = ist_to_utc(2026, 7, 6, 9, 28, 0)
    pout = ist_to_utc(2026, 7, 6, 18, 35, 0)
    assert compute_work_hours(pin, pout) == 9.12


def test_overtime_minimum():
    pin = ist_to_utc(2026, 7, 6, 9, 0, 0)
    pout = ist_to_utc(2026, 7, 6, 18, 45, 0)  # 15 min after 18:30
    assert compute_overtime_minutes(pout, "2026-07-06", "09:30", "18:30") == 0
    pout2 = ist_to_utc(2026, 7, 6, 19, 10, 0)  # 40 min OT
    assert compute_overtime_minutes(pout2, "2026-07-06", "09:30", "18:30") == 40


def test_half_day_flag():
    assert compute_half_day(3.5) is True
    assert compute_half_day(4.5) is False


def test_overnight_attendance_date():
    pin = ist_to_utc(2026, 7, 7, 5, 30, 0)  # 05:30 IST, before 06:00 shift end
    d = attendance_date_for_punch(pin, "22:00", "06:00")
    assert d == "2026-07-06"


def test_working_days_mid_join():
    assert working_days_in_month("2026-07", "2026-07-13") == 15  # Mon 13 through Fri 31


def test_round_half_up():
    assert round_half_up(2.125, 2) == 2.13
    assert round_half_up(2.124, 2) == 2.12
