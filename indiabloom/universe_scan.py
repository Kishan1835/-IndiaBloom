"""Scan an index universe for stocks that react to a leader (e.g. the US index).

Ranking uses the t-statistic of the lead-lag correlation, not the raw
correlation. With hundreds of stocks, some correlations are chance. A t-stat
of about 2 is the usual threshold, and about 3 is stricter when you test many
stocks at once.

`holdout_hit_rate` checks the signal on data the fit never saw: fit the sign
and slope on the first part of the history, then test on the rest.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
import pandas as pd

from indiabloom.analytics import MIN_OBSERVATIONS, lead_aligned, log_returns

MIN_TRAIN = 60
MIN_TEST = 20


@dataclass(frozen=True)
class UniverseRow:
    ticker: str
    company: str
    industry: str
    n_obs: int
    corr: float
    t_stat: float
    beta: float
    last_leader_return_pct: float | None


@dataclass(frozen=True)
class HoldoutResult:
    hit_rate: float | None  # share of out-of-sample days where the predicted direction was right
    n_test: int
    beta_train: float | None


def t_statistic(corr: float, n: int) -> float:
    """t-statistic for a Pearson correlation with n pairs."""
    if n <= 2 or abs(corr) >= 1.0:
        return float("inf") if abs(corr) >= 1.0 else 0.0
    return corr * math.sqrt((n - 2) / (1.0 - corr * corr))


def scan_universe(
    leader: str,
    closes: pd.DataFrame,
    labels: dict[str, tuple[str, str]],
    extra_lag: int = 0,
) -> list[UniverseRow]:
    """Lead-lag statistics for every follower column against `leader`.

    `labels` maps ticker -> (company, industry) for display. Followers with
    too few aligned observations are skipped. Result is sorted by |t|.
    Raises KeyError if the leader is not a column in `closes`.
    """
    leader = leader.strip().upper()
    leader_returns = log_returns(closes[leader])
    last_leader = float(leader_returns.iloc[-1]) * 100 if len(leader_returns) else None

    rows: list[UniverseRow] = []
    for ticker in closes.columns:
        if ticker == leader:
            continue
        frame = lead_aligned(leader_returns, log_returns(closes[ticker]), extra_lag)
        n = len(frame)
        if n < MIN_OBSERVATIONS:
            continue
        corr = float(frame["lead"].corr(frame["follow"]))
        if np.isnan(corr):
            continue
        variance = float(frame["lead"].var())
        beta = float(frame["lead"].cov(frame["follow"]) / variance) if variance else 0.0
        company, industry = labels.get(ticker, ("", ""))
        rows.append(UniverseRow(ticker, company, industry, n, corr,
                                t_statistic(corr, n), beta, last_leader))

    rows.sort(key=lambda r: -abs(r.t_stat))
    return rows


def holdout_hit_rate(
    leader_returns: pd.Series,
    follower_returns: pd.Series,
    split: float = 0.7,
    extra_lag: int = 0,
) -> HoldoutResult:
    """Fit the lead-lag slope on the first `split` of the history, test on the rest.

    A prediction is right when sign(beta * leader) equals the follower's sign.
    Days with a zero return on either side are ignored.
    """
    frame = lead_aligned(leader_returns, follower_returns, extra_lag)
    cut = int(len(frame) * split)
    train, test = frame.iloc[:cut], frame.iloc[cut:]
    if len(train) < MIN_TRAIN or len(test) < MIN_TEST:
        return HoldoutResult(None, len(test), None)

    variance = float(train["lead"].var())
    if not variance:
        return HoldoutResult(None, len(test), None)
    beta = float(train["lead"].cov(train["follow"]) / variance)

    predicted = np.sign(beta) * np.sign(test["lead"].to_numpy())
    actual = np.sign(test["follow"].to_numpy())
    keep = (predicted != 0) & (actual != 0)
    if not keep.any():
        return HoldoutResult(None, len(test), beta)
    hit = float((predicted[keep] == actual[keep]).mean())
    return HoldoutResult(hit, int(keep.sum()), beta)
