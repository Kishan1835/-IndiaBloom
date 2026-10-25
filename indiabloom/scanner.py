"""Combine the graph, prices, and analytics into ranked rows for one global stock."""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from indiabloom.analytics import (
    MIN_OBSERVATIONS,
    lagged_beta,
    lagged_correlation,
    lead_aligned,
    log_returns,
    same_day_correlation,
)
from indiabloom.graph import Graph
from indiabloom.models import Relation, is_indian


@dataclass(frozen=True)
class ScanRow:
    global_ticker: str
    indian_ticker: str
    relation: str
    confidence: str
    n_obs: int
    same_day_corr: float | None
    next_session_corr: float | None
    beta: float | None
    implied_move_pct: float | None
    score: float | None
    note: str


def _implied_move(beta: float | None, latest_global_return: float | None) -> float | None:
    if beta is None or latest_global_return is None:
        return None
    return beta * latest_global_return * 100.0


def scan(
    global_ticker: str,
    graph: Graph,
    closes: pd.DataFrame,
    extra_lag: int = 0,
) -> list[ScanRow]:
    """Score every listed Indian counterpart of `global_ticker`.

    `closes` holds one column per ticker with daily closing prices. Rows are
    sorted by score (descending); rows without a score come last.
    """
    key = global_ticker.strip().upper()
    if key not in closes.columns:
        return []
    global_returns = log_returns(closes[key])
    latest_global = float(global_returns.iloc[-1]) if len(global_returns) else None

    rows: list[ScanRow] = []
    for rel in graph.indian_counterparts(key):
        indian = rel.other(key)
        assert indian is not None and is_indian(indian)  # guaranteed by indian_counterparts

        if indian not in closes.columns:
            rows.append(_row(key, indian, rel, 0, None, None, None, None, None, "no price data"))
            continue

        indian_returns = log_returns(closes[indian])
        n_obs = len(
            pd.concat([global_returns.rename("a"), indian_returns.rename("b")],
                      axis=1, join="inner").dropna()
        )
        same_day = same_day_correlation(global_returns, indian_returns)
        next_corr = lagged_correlation(global_returns, indian_returns, extra_lag)
        beta = lagged_beta(global_returns, indian_returns, extra_lag)

        if next_corr is None or n_obs < MIN_OBSERVATIONS:
            rows.append(_row(key, indian, rel, n_obs, same_day, None, beta, None, None,
                             "insufficient data"))
            continue

        rows.append(_row(
            key, indian, rel, n_obs, same_day, next_corr, beta,
            _implied_move(beta, latest_global),
            abs(next_corr) * rel.weight, "",
        ))

    rows.sort(key=lambda r: (r.score is None, -(r.score or 0.0)))
    return rows


def _row(
    global_key: str,
    indian: str,
    rel: Relation,
    n_obs: int,
    same_day: float | None,
    next_corr: float | None,
    beta: float | None,
    implied: float | None,
    score: float | None,
    note: str,
) -> ScanRow:
    return ScanRow(global_key, indian, rel.relation, rel.confidence, n_obs,
                   same_day, next_corr, beta, implied, score, note)


@dataclass(frozen=True)
class PairMetrics:
    a: str
    b: str
    method: str  # "next-session" (US leads India) or "same-day" (same market)
    leader: str  # ticker whose move arrives first; "" for same-day pairs
    n_obs: int
    corr: float | None
    beta: float | None


def pair_metrics(a: str, b: str, closes: pd.DataFrame) -> PairMetrics:
    """Relationship statistics for any two tickers.

    A US stock and an Indian stock are measured with the next-session lead
    (the US move reaches India one session later). Two stocks in the same
    market trade on the same clock, so only same-day correlation is meaningful.
    Raises KeyError if either ticker is missing from `closes`.
    """
    a, b = a.strip().upper(), b.strip().upper()
    ra = log_returns(closes[a])
    rb = log_returns(closes[b])

    if is_indian(a) == is_indian(b):
        frame = pd.concat([ra.rename("a"), rb.rename("b")], axis=1, join="inner").dropna()
        corr = same_day_correlation(ra, rb)
        return PairMetrics(a, b, "same-day", "", len(frame), corr, None)

    leader, follower = (a, b) if not is_indian(a) else (b, a)
    lead_r = ra if leader == a else rb
    follow_r = rb if leader == a else ra
    n_obs = len(lead_aligned(lead_r, follow_r))
    return PairMetrics(
        a, b, "next-session", leader, n_obs,
        lagged_correlation(lead_r, follow_r, 0),
        lagged_beta(lead_r, follow_r, 0),
    )
