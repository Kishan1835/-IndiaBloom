"""Screen the Nifty index on fundamentals: filters like "pe_trailing<20" or "roe>15".

Works only on the local fundamentals cache (data/fundamentals/), so it makes no
network calls. Run `python -m indiabloom fundamentals` first to fill the cache.

Conditions use plain numbers in the units people usually quote:
  roe, profit_margin, revenue_growth, insider_pct, institution_pct are percents
  market_cap_cr is in Rs crore
  sector and industry match case-insensitively as a substring (sector=bank)
A stock with no value for a field never matches a condition on that field.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

from indiabloom.fundamentals import effective_roe

OPERATORS = ("<=", ">=", "<", ">", "=")
PERCENT_FIELDS = {"roe", "profit_margin", "revenue_growth", "insider_pct", "institution_pct"}
NUMERIC_FIELDS = {
    "pe_trailing", "pe_forward", "pb", "eps", "price", "dividend_yield_pct", "debt_to_equity",
    "market_cap_cr", "roe", *PERCENT_FIELDS,
}
TEXT_FIELDS = {"sector", "industry"}
_CONDITION = re.compile(r"^\s*([a-z_]+)\s*(<=|>=|<|>|=)\s*(.+?)\s*$")


class ScreenError(ValueError):
    """Raised for a condition that cannot be parsed or names an unknown field."""


@dataclass(frozen=True)
class Condition:
    field: str
    op: str
    value: float | str


def parse_condition(text: str) -> Condition:
    match = _CONDITION.match(text.lower())
    if not match:
        raise ScreenError(f"cannot read condition '{text}'; use e.g. pe_trailing<20 or sector=bank")
    field, op, raw = match.groups()
    if field in TEXT_FIELDS:
        if op != "=":
            raise ScreenError(f"'{field}' only supports '=' (substring match)")
        return Condition(field, op, raw.strip())
    if field not in NUMERIC_FIELDS:
        known = ", ".join(sorted(NUMERIC_FIELDS | TEXT_FIELDS))
        raise ScreenError(f"unknown field '{field}'. Known fields: {known}")
    try:
        value = float(raw)
    except ValueError as exc:
        raise ScreenError(f"'{raw}' is not a number for {field}") from exc
    return Condition(field, op, value)


def metric(snap: dict[str, Any], field: str) -> float | str | None:
    """The value a condition compares against, in the condition's units."""
    if field in TEXT_FIELDS:
        return snap.get(field)
    if field == "market_cap_cr":
        mc = snap.get("market_cap")
        return None if mc is None else mc / 1e7
    if field == "roe":
        value = effective_roe(snap)
    else:
        value = snap.get(field)
    if value is None:
        return None
    return value * 100 if field in PERCENT_FIELDS else value


def _compare(actual: float, op: str, target: float) -> bool:
    return {
        "<": actual < target, "<=": actual <= target,
        ">": actual > target, ">=": actual >= target,
        "=": abs(actual - target) < 1e-9,
    }[op]


def matches(snap: dict[str, Any], conditions: list[Condition]) -> bool:
    for cond in conditions:
        actual = metric(snap, cond.field)
        if actual is None:
            return False
        if cond.field in TEXT_FIELDS:
            if cond.value not in str(actual).lower():
                return False
        elif not _compare(float(actual), cond.op, float(cond.value)):
            return False
    return True


def screen(snapshots: Iterable[dict[str, Any]], conditions: list[Condition],
           sort_by: str = "market_cap_cr", descending: bool = True, top: int | None = None) -> list[dict[str, Any]]:
    """Snapshots that pass every condition, sorted. Stocks without the sort field go last."""
    hits = [s for s in snapshots if matches(s, conditions)]

    def key(snap: dict[str, Any]) -> tuple[int, float]:
        value = metric(snap, sort_by)
        if value is None or isinstance(value, str):
            return (1, 0.0)
        return (0, -value if descending else value)

    hits.sort(key=key)
    return hits[:top] if top else hits
