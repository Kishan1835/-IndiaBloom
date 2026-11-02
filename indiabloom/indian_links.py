"""Price-based Indian-to-Indian links.

These are statistical relationships, not claims that one company supplies,
competes with, or causes another company. Curated business links remain in
relations.json and are displayed separately by the Graph views.
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from indiabloom.analytics import MIN_OBSERVATIONS, log_returns


@dataclass(frozen=True)
class IndianLink:
    ticker: str
    other: str
    corr: float
    observations: int
    sector: str
    other_sector: str


def rank_indian_links(ticker: str, closes: pd.DataFrame, sectors: dict[str, str],
                      limit: int = 15, min_observations: int = MIN_OBSERVATIONS) -> list[IndianLink]:
    """Top absolute same-day correlations for one Indian stock.

    Results require shared daily return observations and are sorted by absolute
    correlation. The displayed correlation keeps its sign.
    """
    if ticker not in closes.columns:
        return []
    base = log_returns(closes[ticker]).rename(ticker)
    rows: list[IndianLink] = []
    for other in closes.columns:
        if other == ticker or not other.endswith(".NS"):
            continue
        pair = pd.concat([base, log_returns(closes[other]).rename(other)], axis=1, join="inner").dropna()
        if len(pair) < min_observations:
            continue
        corr = pair[ticker].corr(pair[other])
        if pd.notna(corr):
            rows.append(IndianLink(ticker, other, float(corr), len(pair),
                                   sectors.get(ticker, "-"), sectors.get(other, "-")))
    rows.sort(key=lambda r: (-abs(r.corr), r.other))
    return rows[:limit]
