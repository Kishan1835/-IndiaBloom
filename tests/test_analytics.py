import numpy as np
import pandas as pd
import pytest

from indiabloom.analytics import (
    MIN_OBSERVATIONS,
    lagged_beta,
    lagged_correlation,
    lead_aligned,
    log_returns,
    same_day_correlation,
)


def _series(values, start="2024-01-01"):
    idx = pd.bdate_range(start=start, periods=len(values))
    return pd.Series(values, index=idx)


def test_log_returns_drops_first_nan_and_matches_formula():
    rets = log_returns(_series([100.0, 110.0, 99.0]))
    assert len(rets) == 2
    assert rets.iloc[0] == pytest.approx(np.log(1.1))


def test_same_day_correlation_of_identical_series_is_one():
    rng = np.random.default_rng(1)
    r = _series(rng.normal(size=60))
    assert same_day_correlation(r, r) == pytest.approx(1.0)


def test_returns_none_below_minimum_sample():
    r = _series(np.arange(10, dtype=float))
    assert same_day_correlation(r, r) is None


def test_planted_one_day_lead_is_recovered():
    rng = np.random.default_rng(42)
    n = 400
    leader = rng.normal(size=n)
    # follower on business day t reacts to the leader on business day t-1
    follower = np.concatenate([[0.0], leader[:-1]]) + rng.normal(scale=0.05, size=n)
    lead, fol = _series(leader), _series(follower)

    assert lagged_correlation(lead, fol, extra_lag=0) == pytest.approx(0.99, abs=0.05)
    assert abs(lagged_correlation(lead, fol, extra_lag=1)) < 0.2


def test_planted_sensitivity_recovered_by_beta():
    rng = np.random.default_rng(3)
    n = 500
    leader = rng.normal(size=n)
    follower = 0.6 * np.concatenate([[0.0], leader[:-1]]) + rng.normal(scale=0.01, size=n)
    assert lagged_beta(_series(leader), _series(follower)) == pytest.approx(0.6, abs=0.05)


def test_monday_follower_pairs_with_friday_leader():
    # Business-day index: Mon..Fri. Monday's India session follows Friday's US session.
    leader = pd.Series([1.0, 2.0, 3.0, 4.0, 5.0],
                       index=pd.to_datetime(["2024-06-03", "2024-06-04", "2024-06-05",
                                             "2024-06-06", "2024-06-07"]))
    follower = pd.Series([9.0], index=pd.to_datetime(["2024-06-10"]))  # a Monday
    frame = lead_aligned(leader, follower)
    assert frame["lead"].iloc[0] == 5.0  # Friday 2024-06-07


def test_us_holiday_uses_previous_real_session():
    # Wednesday 2024-06-05 is a US holiday: no leader row for it.
    leader = pd.Series([1.0, 2.0, 4.0],
                       index=pd.to_datetime(["2024-06-03", "2024-06-04", "2024-06-06"]))
    follower = pd.Series([7.0], index=pd.to_datetime(["2024-06-06"]))  # Thursday
    frame = lead_aligned(leader, follower)
    # Cutoff is Wednesday; newest US session on or before it is Tuesday 2024-06-04.
    assert frame["lead"].iloc[0] == 2.0


def test_stale_leader_value_is_dropped():
    leader = pd.Series([1.0], index=pd.to_datetime(["2024-06-01"]))
    follower = pd.Series([2.0], index=pd.to_datetime(["2024-06-20"]))
    assert lead_aligned(leader, follower).empty


def test_negative_extra_lag_rejected():
    r = _series(np.arange(50, dtype=float))
    with pytest.raises(ValueError):
        lagged_correlation(r, r, extra_lag=-1)


def test_minimum_observations_constant_unchanged():
    assert MIN_OBSERVATIONS == 30
