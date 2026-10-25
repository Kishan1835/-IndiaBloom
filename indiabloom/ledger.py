"""Forward signal ledger: log predictions before they happen, then score them.

Each logged signal is one stock's predicted direction for one Indian session,
made from the newest completed leader session (e.g. the S&P 500 close). The
ledger is append-only CSV. A signal is scored only after its target session has
closed, so the record is forward-only. Backfilling old scans would leak the
future into the fit, so `log-signals` always uses data available at log time.

Direction is sign(beta * leader_return). Stocks with a zero beta or zero
return are not predicted.
"""

from __future__ import annotations

import csv
import math
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

from indiabloom.analytics import log_returns

LEDGER_COLUMNS = [
    "logged_on", "leader", "leader_session", "target_session", "ticker", "company",
    "rank", "beta", "t_stat", "leader_return_pct", "predicted", "in_top",
]


@dataclass(frozen=True)
class LedgerEntry:
    logged_on: date
    leader: str
    leader_session: date
    target_session: date
    ticker: str
    company: str
    rank: int
    beta: float
    t_stat: float
    leader_return_pct: float
    predicted: int  # +1 up, -1 down
    in_top: bool


@dataclass(frozen=True)
class ScoredEntry:
    entry: LedgerEntry
    actual_return_pct: float | None  # None while the target session is still pending
    hit: bool | None  # None when pending or the actual move is exactly zero


def build_entries(
    rows: list,  # UniverseRow objects from universe_scan.scan_universe
    leader: str,
    leader_session: date,
    target_session: date,
    leader_return: float,
    logged_on: date,
    top_n: int = 20,
) -> list[LedgerEntry]:
    """One entry per stock with a usable direction, ranked by |t| as in the scan."""
    entries: list[LedgerEntry] = []
    for rank, row in enumerate(rows, start=1):
        direction = float(np.sign(row.beta * leader_return))
        if direction == 0:
            continue
        entries.append(LedgerEntry(
            logged_on=logged_on,
            leader=leader,
            leader_session=leader_session,
            target_session=target_session,
            ticker=row.ticker,
            company=row.company,
            rank=rank,
            beta=row.beta,
            t_stat=row.t_stat,
            leader_return_pct=leader_return * 100.0,
            predicted=int(direction),
            in_top=rank <= top_n,
        ))
    return entries


def _key(leader: str, leader_session: date) -> tuple[str, str]:
    return leader, leader_session.isoformat()


def read_ledger(path: Path) -> list[LedgerEntry]:
    if not path.exists():
        return []
    entries: list[LedgerEntry] = []
    with path.open(encoding="utf-8", newline="") as fh:
        for row in csv.DictReader(fh):
            entries.append(LedgerEntry(
                logged_on=date.fromisoformat(row["logged_on"]),
                leader=row["leader"],
                leader_session=date.fromisoformat(row["leader_session"]),
                target_session=date.fromisoformat(row["target_session"]),
                ticker=row["ticker"],
                company=row["company"],
                rank=int(row["rank"]),
                beta=float(row["beta"]),
                t_stat=float(row["t_stat"]),
                leader_return_pct=float(row["leader_return_pct"]),
                predicted=int(row["predicted"]),
                in_top=row["in_top"] == "True",
            ))
    return entries


def already_logged(path: Path, leader: str, leader_session: date) -> bool:
    """True if this leader session already has entries (no duplicate logging)."""
    return any(_key(e.leader, e.leader_session) == _key(leader, leader_session)
               for e in read_ledger(path))


def append_entries(path: Path, entries: list[LedgerEntry]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    is_new = not path.exists()
    with path.open("a", encoding="utf-8", newline="") as fh:
        writer = csv.writer(fh)
        if is_new:
            writer.writerow(LEDGER_COLUMNS)
        for e in entries:
            writer.writerow([
                e.logged_on.isoformat(), e.leader, e.leader_session.isoformat(),
                e.target_session.isoformat(), e.ticker, e.company, e.rank,
                f"{e.beta:.6f}", f"{e.t_stat:.4f}", f"{e.leader_return_pct:.4f}",
                e.predicted, e.in_top,
            ])


def score_entries(entries: list[LedgerEntry], closes: pd.DataFrame) -> list[ScoredEntry]:
    """Compare each prediction with the stock's actual move on its target session.

    The actual move is the log change from the stock's previous close to its
    close on the target session. Entries whose target session is not in
    `closes` yet stay pending.
    """
    scored: list[ScoredEntry] = []
    for entry in entries:
        actual: float | None = None
        if entry.ticker in closes.columns:
            series = closes[entry.ticker].dropna().sort_index()
            # target_session is the next weekday; the stock's first real session on or
            # after it is the one that actually reacted (Indian holidays shift it).
            target = pd.Timestamp(entry.target_session)
            pos = series.index.searchsorted(target, side="left")
            if 1 <= pos < len(series):
                actual = float(math.log(series.iloc[pos] / series.iloc[pos - 1]) * 100.0)
        hit: bool | None = None
        if actual is not None and actual != 0.0:
            hit = bool(np.sign(actual) == entry.predicted)
        scored.append(ScoredEntry(entry, actual, hit))
    return scored


@dataclass(frozen=True)
class Summary:
    sessions_scored: int
    top_picks: int
    top_hits: int
    universe_predictions: int
    universe_hits: int
    pending: int

    @property
    def top_hit_rate(self) -> float | None:
        return self.top_hits / self.top_picks if self.top_picks else None

    @property
    def universe_hit_rate(self) -> float | None:
        return self.universe_hits / self.universe_predictions if self.universe_predictions else None


def summarize(scored: list[ScoredEntry]) -> Summary:
    resolved = [s for s in scored if s.hit is not None]
    top = [s for s in resolved if s.entry.in_top]
    sessions = {(s.entry.leader, s.entry.leader_session) for s in resolved}
    return Summary(
        sessions_scored=len(sessions),
        top_picks=len(top),
        top_hits=sum(1 for s in top if s.hit),
        universe_predictions=len(resolved),
        universe_hits=sum(1 for s in resolved if s.hit),
        pending=sum(1 for s in scored if s.actual_return_pct is None),
    )


def wilson_interval(hits: int, n: int, z: float = 1.96) -> tuple[float, float] | None:
    """95% Wilson score interval for a hit rate. Honest about small samples."""
    if n == 0:
        return None
    p = hits / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return max(0.0, centre - half), min(1.0, centre + half)
