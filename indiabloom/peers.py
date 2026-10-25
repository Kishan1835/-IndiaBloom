"""Statistical peers: same-industry stocks that move most closely with each stock.

These are computed from price history, not from business relationships. A
high correlation means the two stocks trade together. It does not mean they
compete. The UI labels them separately from recorded competitors.

Peers are limited to the same NSE industry, so unrelated sectors that happen to
move together (a common market factor) do not show up as peers.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

from indiabloom.analytics import log_returns

PEERS_FILE = Path(__file__).resolve().parent.parent / "data" / "peers.csv"
MIN_OBS = 120  # about six months of shared trading days


@dataclass(frozen=True)
class Peer:
    ticker: str
    peer: str
    corr: float
    industry: str


def statistical_peers(
    closes: pd.DataFrame,
    industries: dict[str, str],
    k: int = 5,
    min_obs: int = MIN_OBS,
) -> list[Peer]:
    """Top-k same-industry peers for every ticker in `industries`.

    Correlation uses daily log returns over dates both stocks traded. Tickers
    with fewer than `min_obs` shared days are not ranked.
    """
    tickers = [t for t in industries if t in closes.columns]
    returns = pd.concat({t: log_returns(closes[t]) for t in tickers}, axis=1)
    corr = returns.corr(min_periods=min_obs)

    by_industry: dict[str, list[str]] = {}
    for t in tickers:
        by_industry.setdefault(industries[t], []).append(t)

    out: list[Peer] = []
    for ticker in tickers:
        candidates = [t for t in by_industry[industries[ticker]] if t != ticker]
        scored = []
        for other in candidates:
            value = corr.at[ticker, other] if ticker in corr.index and other in corr.columns else np.nan
            if pd.notna(value):
                scored.append((float(value), other))
        scored.sort(reverse=True)
        for value, other in scored[:k]:
            out.append(Peer(ticker, other, value, industries[ticker]))
    return out


def save_peers(path: Path, peers: list[Peer]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(["ticker", "peer", "corr", "industry"])
        for p in peers:
            writer.writerow([p.ticker, p.peer, f"{p.corr:.4f}", p.industry])


def load_peers(path: Path = PEERS_FILE) -> dict[str, list[Peer]]:
    """Peers keyed by ticker. Empty dict if the file does not exist yet."""
    if not path.exists():
        return {}
    out: dict[str, list[Peer]] = {}
    with path.open(encoding="utf-8", newline="") as fh:
        for row in csv.DictReader(fh):
            peer = Peer(row["ticker"], row["peer"], float(row["corr"]), row["industry"])
            out.setdefault(peer.ticker, []).append(peer)
    return out
