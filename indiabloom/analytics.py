"""Return and correlation analytics. Pure functions: no I/O, no network.

Time-zone alignment
-------------------
The US session for calendar date d closes before the Indian session on d+1
opens. So for an Indian date t, the newest US session that is already known is
the latest US session dated on or before t-1 calendar day. Holidays and
weekends are handled by using the real US session dates, not the row position.

`extra_lag` counts additional US sessions further back. extra_lag=0 means
"newest completed US session" (the primary signal, SPEC section 6.3).
"""

from __future__ import annotations

import numpy as np
import pandas as pd

MIN_OBSERVATIONS = 30
MAX_STALENESS_DAYS = 4  # longest acceptable gap (long weekends) before a US value is stale


def log_returns(prices: pd.Series) -> pd.Series:
    """Daily log returns on the series' own trading dates, dropping NaNs."""
    clean = prices.astype(float).dropna().sort_index()
    return np.log(clean).diff().dropna()


def lead_aligned(
    leader_returns: pd.Series, follower_returns: pd.Series, extra_lag: int = 0
) -> pd.DataFrame:
    """Pair each follower return with the leader return it can react to.

    Returns a DataFrame with columns `lead` (leader return) and `follow`
    (follower return), indexed by follower date. Rows without a fresh leader
    value are dropped.
    """
    if extra_lag < 0:
        raise ValueError("extra_lag must be >= 0")
    leader = leader_returns.dropna().sort_index()
    if extra_lag:
        leader = leader.shift(extra_lag).dropna()
    follower = follower_returns.dropna().sort_index()
    if leader.empty or follower.empty:
        return pd.DataFrame(columns=["lead", "follow"], dtype=float)

    cutoff = follower.index - pd.Timedelta(days=1)
    pos = leader.index.searchsorted(cutoff, side="right") - 1
    usable = pos >= 0
    lead_dates = pd.DatetimeIndex(leader.index[np.where(usable, pos, 0)])
    gap_days = (cutoff - lead_dates).days
    fresh = usable & (gap_days <= MAX_STALENESS_DAYS)

    values = leader.to_numpy()[np.where(fresh, pos, 0)]
    frame = pd.DataFrame(
        {"lead": values, "follow": follower.to_numpy()}, index=follower.index
    )
    return frame[fresh].dropna()


def same_day_correlation(leader_returns: pd.Series, follower_returns: pd.Series) -> float | None:
    """Pearson correlation on identical dates. Shown for reference only:
    it ignores the time-zone offset and is misleading for cross-market pairs."""
    frame = pd.concat(
        [leader_returns.rename("lead"), follower_returns.rename("follow")], axis=1, join="inner"
    ).dropna()
    if len(frame) < MIN_OBSERVATIONS:
        return None
    return float(frame["lead"].corr(frame["follow"]))


def lagged_correlation(
    leader_returns: pd.Series, follower_returns: pd.Series, extra_lag: int = 0
) -> float | None:
    """Correlation between the leader's newest completed session and the follower's return."""
    frame = lead_aligned(leader_returns, follower_returns, extra_lag)
    if len(frame) < MIN_OBSERVATIONS:
        return None
    return float(frame["lead"].corr(frame["follow"]))


def lagged_beta(
    leader_returns: pd.Series, follower_returns: pd.Series, extra_lag: int = 0
) -> float | None:
    """Expected follower move per unit of leader move (OLS slope through the pairs)."""
    frame = lead_aligned(leader_returns, follower_returns, extra_lag)
    if len(frame) < MIN_OBSERVATIONS:
        return None
    variance = float(frame["lead"].var())
    if variance == 0.0 or np.isnan(variance):
        return None
    return float(frame["lead"].cov(frame["follow"]) / variance)
