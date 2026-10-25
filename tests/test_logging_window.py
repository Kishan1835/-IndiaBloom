from datetime import date, datetime

from indiabloom.signals_cli import IST, logging_window_open


def _ist(y, mo, d, h, mi):
    return datetime(y, mo, d, h, mi, tzinfo=IST)


def test_logging_allowed_before_indian_open_on_target_day():
    assert logging_window_open(date(2026, 10, 26), _ist(2026, 10, 26, 8, 0))


def test_logging_refused_after_indian_open_on_target_day():
    assert not logging_window_open(date(2026, 10, 26), _ist(2026, 10, 26, 10, 30))


def test_logging_allowed_on_weekend_for_monday_target():
    assert logging_window_open(date(2026, 10, 26), _ist(2026, 10, 24, 21, 0))


def test_logging_refused_after_target_day():
    assert not logging_window_open(date(2026, 10, 26), _ist(2026, 10, 27, 7, 0))


def test_utc_clock_is_converted_to_ist():
    from datetime import timezone

    # 2026-10-26 03:30 UTC is 09:00 IST: still before the 09:15 open.
    utc_time = datetime(2026, 10, 26, 3, 30, tzinfo=timezone.utc)
    assert logging_window_open(date(2026, 10, 26), utc_time)
    # 03:50 UTC is 09:20 IST: after the open.
    assert not logging_window_open(date(2026, 10, 26),
                                   datetime(2026, 10, 26, 3, 50, tzinfo=timezone.utc))
