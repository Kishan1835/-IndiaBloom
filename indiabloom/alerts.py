"""Alerts for watched stocks: price levels, day moves, new bulk/block deals and new headlines.

Rules are stored in data/alerts.json and are personal, so the file is git-ignored.
evaluate() is pure: it takes quotes, deals and headlines and returns the alerts that
fire plus the updated rules. The CLI (`python -m indiabloom alerts ...`) fetches the
data and writes triggered alerts to data/alerts/log.csv.

Firing rules:
  price_above / price_below / move_above / move_below
      fire at most once per day, the first check that finds the condition true.
  deal / news
      fire once per new item. Items present when the rule was created are
      recorded as seen, so you are not alerted on old history.
"""

from __future__ import annotations

import csv
import json
from dataclasses import asdict, dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Any

from indiabloom.deals import Deal

ALERTS_FILE = Path(__file__).resolve().parent.parent / "data" / "alerts.json"
LOG_FILE = Path(__file__).resolve().parent.parent / "data" / "alerts" / "log.csv"
KINDS = ("price_above", "price_below", "move_above", "move_below", "deal", "news")
NEEDS_NUMBER = {"price_above", "price_below", "move_above", "move_below"}
MAX_SEEN = 200


class AlertError(ValueError):
    """Raised for an invalid rule (unknown kind, or a missing threshold)."""


@dataclass
class Rule:
    id: int
    ticker: str
    kind: str
    threshold: float | None = None
    last_fired: str | None = None  # ISO date of the last price/move alert
    seen: list[str] = field(default_factory=list)  # keys of deals or headlines already alerted


@dataclass(frozen=True)
class Alert:
    rule_id: int
    ticker: str
    message: str


def validate(kind: str, threshold: float | None) -> None:
    if kind not in KINDS:
        raise AlertError(f"unknown alert kind '{kind}'; choose one of {', '.join(KINDS)}")
    if kind in NEEDS_NUMBER and threshold is None:
        raise AlertError(f"{kind} needs a number")


def load_rules(path: Path = ALERTS_FILE) -> tuple[list[Rule], int]:
    """Rules and the next free id. A missing file means no rules yet."""
    if not path.exists():
        return [], 1
    data = json.loads(path.read_text(encoding="utf-8"))
    rules = [Rule(**item) for item in data.get("rules", [])]
    return rules, int(data.get("next_id", max((r.id for r in rules), default=0) + 1))


def save_rules(rules: list[Rule], next_id: int, path: Path = ALERTS_FILE) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"next_id": next_id, "rules": [asdict(r) for r in sorted(rules, key=lambda r: r.id)]}
    path.write_text(json.dumps(payload, indent=1), encoding="utf-8")


def deal_key(d: Deal) -> str:
    return f"{d.date}|{d.kind}|{d.side}|{d.client}|{d.quantity}|{d.price}"


def _code(ticker: str) -> str:
    return ticker.removesuffix(".NS").upper()


def evaluate(
    rules: list[Rule],
    quotes: dict[str, tuple[float | None, float | None]],
    deals: list[Deal],
    headlines: dict[str, list[str]],
    today: date,
) -> tuple[list[Alert], list[Rule]]:
    """Alerts that fire now, and the rules with their state updated.

    quotes maps ticker -> (last price, day change %). deals are the whole history.
    headlines maps ticker -> current headline titles. Rules are updated in place
    and returned.
    """
    alerts: list[Alert] = []
    today_s = today.isoformat()
    for rule in rules:
        last, change = quotes.get(rule.ticker, (None, None))
        if rule.kind in NEEDS_NUMBER:
            if rule.last_fired == today_s:
                continue
            message = _price_message(rule, last, change)
            if message:
                alerts.append(Alert(rule.id, rule.ticker, message))
                rule.last_fired = today_s
        elif rule.kind == "deal":
            code = _code(rule.ticker)
            for d in sorted((d for d in deals if d.symbol == code), key=lambda d: d.date):
                key = deal_key(d)
                if key in rule.seen:
                    continue
                rule.seen = (rule.seen + [key])[-MAX_SEEN:]
                alerts.append(Alert(rule.id, rule.ticker,
                                    f"{rule.ticker} deal {d.date}: {d.side} {d.quantity:,} shares "
                                    f"by {d.client} at {d.price:,.2f} ({d.kind})"))
        elif rule.kind == "news":
            for title in headlines.get(rule.ticker, []):
                if title in rule.seen:
                    continue
                rule.seen = (rule.seen + [title])[-MAX_SEEN:]
                alerts.append(Alert(rule.id, rule.ticker, f"{rule.ticker} headline: {title}"))
    return alerts, rules


def _price_message(rule: Rule, last: float | None, change: float | None) -> str | None:
    if rule.kind == "price_above" and last is not None and last >= rule.threshold:
        return f"{rule.ticker} at {last:,.2f}, at or above {rule.threshold:g}"
    if rule.kind == "price_below" and last is not None and last <= rule.threshold:
        return f"{rule.ticker} at {last:,.2f}, at or below {rule.threshold:g}"
    if rule.kind == "move_above" and change is not None and change >= rule.threshold:
        return f"{rule.ticker} up {change:+.2f}% today (alert at +{rule.threshold:g}%)"
    if rule.kind == "move_below" and change is not None and change <= rule.threshold:
        return f"{rule.ticker} down {change:+.2f}% today (alert at {rule.threshold:g}%)"
    return None


def append_log(alerts: list[Alert], when: datetime, path: Path = LOG_FILE) -> None:
    """Append fired alerts to the log CSV, writing the header on first use."""
    if not alerts:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    new_file = not path.exists()
    with path.open("a", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        if new_file:
            writer.writerow(["time", "rule_id", "ticker", "message"])
        for a in alerts:
            writer.writerow([when.isoformat(timespec="seconds"), a.rule_id, a.ticker, a.message])


def describe(rule: Rule) -> str:
    if rule.kind in NEEDS_NUMBER:
        return f"{rule.kind} {rule.threshold:g}"
    return rule.kind


def to_dict(rule: Rule) -> dict[str, Any]:
    return asdict(rule)
