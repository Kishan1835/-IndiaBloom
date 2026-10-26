from datetime import datetime

import pandas as pd

from indiabloom.signals_cli import IST, drop_open_session


def _closes():
    idx = pd.to_datetime(["2026-10-23", "2026-10-26"])
    return pd.DataFrame({"INFY.NS": [1500.0, 1510.0]}, index=idx)


def test_today_bar_dropped_during_session():
    now = datetime(2026, 10, 26, 12, 48, tzinfo=IST)
    kept = drop_open_session(_closes(), now)
    assert [d.date().isoformat() for d in kept.index] == ["2026-10-23"]


def test_today_bar_kept_after_close():
    now = datetime(2026, 10, 26, 16, 30, tzinfo=IST)
    assert len(drop_open_session(_closes(), now)) == 2


def test_session_guard_uses_the_last_full_day_before_today():
    now = datetime(2026, 10, 26, 9, 0, tzinfo=IST)  # before the open: today is incomplete
    assert len(drop_open_session(_closes(), now)) == 1
