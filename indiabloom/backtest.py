"""Preference screen on price history, with an out-of-sample backtest.

You write rules on price measures (for example "vol_1y<40" and "ret_3m>0"). At
each monthly date in the test period, the rules are applied using only prices
up to that date. The stocks that pass are held for a fixed number of trading
days and compared with the average of all stocks in the universe.

Limits, stated plainly:
- Only price rules are tested. Fundamentals have no history in this project,
  so a P/E or ROE rule cannot be backtested here.
- The universe is today's listed stocks, so delisted and failed companies are
  missing. That flatters every result (survivorship bias).
- Trading costs, taxes and slippage are not modelled.
- A rule that beats the universe in one test period may not do so in the next.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

LOOKBACK = 252  # trading days in a year
FIELDS = {"ret_3m", "ret_1y", "vol_1y", "drawdown_1y"}
_CONDITION = re.compile(r"^\s*([a-z0-9_]+)\s*(<=|>=|<|>)\s*(-?\d+(?:\.\d+)?)\s*$")


class BacktestError(ValueError):
    """Raised for a rule that cannot be read, or data too short to test."""


@dataclass(frozen=True)
class Rule:
    field: str
    op: str
    value: float


def parse_rule(text: str) -> Rule:
    match = _CONDITION.match(text.lower())
    if not match:
        raise BacktestError(f"cannot read rule '{text}'; use e.g. vol_1y<40 or ret_3m>0")
    field_name, op, raw = match.groups()
    if field_name not in FIELDS:
        raise BacktestError(f"unknown measure '{field_name}'; choose from {', '.join(sorted(FIELDS))}")
    return Rule(field_name, op, float(raw))


def measures(closes: pd.DataFrame) -> pd.DataFrame:
    """Price measures for every stock using only the rows in `closes` (no look-ahead)."""
    last = closes.iloc[-1]
    out = pd.DataFrame(index=closes.columns)
    out["ret_3m"] = (last / closes.iloc[-64] - 1) * 100 if len(closes) > 64 else np.nan
    window = closes.iloc[-(LOOKBACK + 1):]
    out["ret_1y"] = (last / window.iloc[0] - 1) * 100 if len(window) > 1 else np.nan
    log_returns = np.log(window / window.shift(1)).iloc[1:]
    out["vol_1y"] = log_returns.std() * math.sqrt(LOOKBACK) * 100
    peak = window.cummax()
    out["drawdown_1y"] = ((window / peak - 1) * 100).min()
    return out


def _passes(values: pd.DataFrame, rules: list[Rule]) -> pd.Series:
    ok = pd.Series(True, index=values.index)
    for rule in rules:
        col = values[rule.field]
        cmp = {"<": col < rule.value, "<=": col <= rule.value,
               ">": col > rule.value, ">=": col >= rule.value}[rule.op]
        ok &= cmp.fillna(False)
    return ok


@dataclass
class BacktestResult:
    periods: int
    avg_selected: float | None
    avg_universe: float | None
    period_wins: int  # periods where the selection's average beat the universe median
    selected_counts: list[int] = field(default_factory=list)

    @property
    def excess(self) -> float | None:
        if self.avg_selected is None or self.avg_universe is None:
            return None
        return self.avg_selected - self.avg_universe

    @property
    def win_rate(self) -> float | None:
        return self.period_wins / self.periods if self.periods else None


def backtest(closes: pd.DataFrame, rules: list[Rule], hold_days: int = 21, step_days: int = 21,
             top_n: int = 20, test_fraction: float = 0.3) -> BacktestResult:
    """Test the rules on the last `test_fraction` of the history.

    Selected stocks (the top_n by 1-year return if more pass) are held for hold_days.
    Returns the average forward return of the selection and of the whole universe.
    """
    closes = closes.sort_index().dropna(axis=1, thresh=LOOKBACK + 2)
    n = len(closes)
    if n < LOOKBACK + hold_days + 2:
        raise BacktestError(f"need at least {LOOKBACK + hold_days + 2} trading days; have {n}")
    start = max(LOOKBACK, int(n * (1 - test_fraction)))
    sel_returns: list[float] = []
    uni_returns: list[float] = []
    wins = 0
    counts: list[int] = []
    for t in range(start, n - hold_days, step_days):
        history = closes.iloc[: t + 1].ffill()
        values = measures(history)
        forward = closes.iloc[t + hold_days] / closes.iloc[t] - 1
        forward = forward.dropna()
        universe = values.index.intersection(forward.index)
        if len(universe) < 10:
            continue
        passing = values.loc[universe][_passes(values.loc[universe], rules)].index
        if len(passing) == 0:
            counts.append(0)
            continue
        if len(passing) > top_n:
            passing = values.loc[passing].sort_values("ret_1y", ascending=False).index[:top_n]
        selected_mean = float(forward.loc[passing].mean())
        universe_mean = float(forward.loc[universe].mean())
        universe_median = float(forward.loc[universe].median())
        sel_returns.append(selected_mean)
        uni_returns.append(universe_mean)
        counts.append(len(passing))
        if selected_mean > universe_median:
            wins += 1
    if not sel_returns:
        return BacktestResult(0, None, None, 0, counts)
    return BacktestResult(
        periods=len(sel_returns),
        avg_selected=float(np.mean(sel_returns)) * 100,
        avg_universe=float(np.mean(uni_returns)) * 100,
        period_wins=wins,
        selected_counts=counts,
    )
