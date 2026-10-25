"""Synthetic price generator for offline demos and tests.

Builds a US leader series and Indian follower series where the follower
reacts to the leader's previous-day return. This makes the one-day lead
visible without any network access.
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def synthetic_closes(
    leader: str,
    followers: dict[str, float],
    days: int = 252,
    seed: int = 7,
) -> pd.DataFrame:
    """followers maps ticker -> sensitivity to the leader's previous-day return."""
    rng = np.random.default_rng(seed)
    index = pd.bdate_range(end=pd.Timestamp.today().normalize(), periods=days)
    leader_ret = rng.normal(0.0, 0.015, days)
    data: dict[str, np.ndarray] = {leader: 100.0 * np.exp(np.cumsum(leader_ret))}

    for ticker, sensitivity in followers.items():
        noise = rng.normal(0.0, 0.01, days)
        lagged = np.concatenate([[0.0], leader_ret[:-1]])
        follower_ret = sensitivity * lagged + noise
        data[ticker] = 500.0 * np.exp(np.cumsum(follower_ret))

    return pd.DataFrame(data, index=index)
