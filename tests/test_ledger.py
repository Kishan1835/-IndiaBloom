from datetime import date
import math

import pandas as pd
import pytest

from indiabloom.ledger import (
    append_entries,
    already_logged,
    build_entries,
    read_ledger,
    score_entries,
    summarize,
    wilson_interval,
)
from indiabloom.universe_scan import UniverseRow


def _row(ticker, beta, t=3.0):
    return UniverseRow(ticker, ticker, "x", 300, 0.2, t, beta, 1.0)


def test_direction_follows_beta_times_leader_return():
    rows = [_row("UP.NS", 0.8), _row("DOWN.NS", -0.5), _row("FLAT.NS", 0.0)]
    entries = build_entries(rows, "^GSPC", date(2026, 10, 23), date(2026, 10, 26),
                            leader_return=-0.01, logged_on=date(2026, 10, 25), top_n=1)
    by_ticker = {e.ticker: e for e in entries}
    assert "FLAT.NS" not in by_ticker  # zero beta gives no prediction
    assert by_ticker["UP.NS"].predicted == -1  # positive beta, negative leader move
    assert by_ticker["DOWN.NS"].predicted == +1
    assert by_ticker["UP.NS"].in_top and not by_ticker["DOWN.NS"].in_top


def test_ledger_round_trip_and_duplicate_detection(tmp_path):
    path = tmp_path / "signals.csv"
    entries = build_entries([_row("A.NS", 0.5)], "^GSPC", date(2026, 10, 23),
                            date(2026, 10, 26), 0.01, date(2026, 10, 25))
    append_entries(path, entries)
    append_entries(path, entries)  # second write must not repeat the header
    assert path.read_text(encoding="utf-8").count("logged_on") == 1
    loaded = read_ledger(path)
    assert len(loaded) == 2
    assert loaded[0].target_session == date(2026, 10, 26)
    assert already_logged(path, "^GSPC", date(2026, 10, 23))
    assert not already_logged(path, "^GSPC", date(2026, 10, 26))


def _entry(ticker, predicted, target=date(2026, 10, 26), in_top=True):
    return build_entries([_row(ticker, 0.5 * predicted)], "^GSPC", date(2026, 10, 23),
                         target, 0.01, date(2026, 10, 25), top_n=1 if in_top else 0)[0]


def _closes():
    idx = pd.to_datetime(["2026-10-22", "2026-10-23", "2026-10-26", "2026-10-27"])
    return pd.DataFrame({
        "GOOD.NS": [100.0, 100.0, 103.0, 104.0],   # up on target 10-26, predicted up
        "BAD.NS": [100.0, 100.0, 97.0, 96.0],      # down on target, predicted up
    }, index=idx)


def test_scoring_marks_hits_and_misses():
    scored = score_entries([_entry("GOOD.NS", +1), _entry("BAD.NS", +1)], _closes())
    by = {s.entry.ticker: s for s in scored}
    assert by["GOOD.NS"].hit is True
    assert by["BAD.NS"].hit is False
    assert by["GOOD.NS"].actual_return_pct == pytest.approx(math.log(1.03) * 100, abs=1e-9)


def test_holiday_moves_target_to_next_real_session():
    # Target Monday 10-26 is missing for this stock (Indian holiday); Tuesday is the real session.
    idx = pd.to_datetime(["2026-10-23", "2026-10-27"])
    closes = pd.DataFrame({"HOL.NS": [100.0, 105.0]}, index=idx)
    scored = score_entries([_entry("HOL.NS", +1)], closes)
    assert scored[0].hit is True


def test_pending_when_target_has_not_traded():
    scored = score_entries([_entry("GOOD.NS", +1, target=date(2026, 11, 2))], _closes())
    assert scored[0].actual_return_pct is None
    assert scored[0].hit is None
    assert summarize(scored).pending == 1


def test_summary_separates_top_picks_from_universe():
    scored = score_entries([
        _entry("GOOD.NS", +1, in_top=True),
        _entry("BAD.NS", +1, in_top=False),
        _entry("BAD.NS", -1, in_top=False),
    ], _closes())
    s = summarize(scored)
    assert s.top_picks == 1 and s.top_hits == 1
    assert s.universe_predictions == 3 and s.universe_hits == 2
    assert s.sessions_scored == 1


def test_wilson_interval_behaviour():
    assert wilson_interval(0, 0) is None
    low, high = wilson_interval(8, 10)
    assert low < 0.8 < high
    low_small, high_small = wilson_interval(3, 3)
    assert high_small == pytest.approx(1.0)
    assert low_small < 0.6  # three hits is not strong evidence
