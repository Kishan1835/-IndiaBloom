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


RULE_WORDS = {"above": "price_above", "below": "price_below", "move_up": "move_above",
              "move_down": "move_below", "deals": "deal", "news": "news"}


@dataclass(frozen=True)
class ParsedRule:
    ticker: str
    kind: str
    threshold: float | None


def parse_rule_text(text: str) -> ParsedRule:
    """'INFY.NS above 1700', 'MU move_down -3', 'INFY.NS deals' or 'TCS.NS news'."""
    parts = text.split()
    usage = "use TICKER above|below|move_up|move_down NUMBER, or TICKER deals|news"
    if len(parts) < 2:
        raise AlertError(usage)
    ticker = parts[0].upper()
    word = parts[1].lower()
    if word not in RULE_WORDS:
        raise AlertError(f"unknown rule '{word}'; {usage}")
    kind = RULE_WORDS[word]
    if kind in NEEDS_NUMBER:
        if len(parts) != 3:
            raise AlertError(f"{word} needs a number, e.g. {ticker} {word} 1700")
        try:
            threshold = float(parts[2])
        except ValueError as exc:
            raise AlertError(f"'{parts[2]}' is not a number") from exc
    else:
        if len(parts) != 2:
            raise AlertError(f"{word} takes no number")
        threshold = None
    validate(kind, threshold)
    return ParsedRule(ticker, kind, threshold)


def parse_remove(text: str) -> int | None:
    """The rule id in 'remove 3' (or 'rm 3'), or None when the text is not a removal."""
    parts = text.split()
    if len(parts) == 2 and parts[0].lower() in ("remove", "rm"):
        try:
            return int(parts[1])
        except ValueError as exc:
            raise AlertError("remove needs a rule id number, e.g. remove 3") from exc
    return None


def news_query(ticker: str) -> str:
    from indiabloom.companies import DEFAULT_COMPANIES, load_companies

    names = load_companies(DEFAULT_COMPANIES)
    code = ticker.removesuffix(".NS")
    return f"{names[ticker][0] if ticker in names else code} stock"


def initial_seen(ticker: str, kind: str) -> list[str]:
    """Items that already exist when a rule is created, so only later ones alert."""
    if kind == "deal":
        from indiabloom.deals import load_history

        code = ticker.removesuffix(".NS")
        return [deal_key(d) for d in load_history() if d.symbol == code][-MAX_SEEN:]
    if kind == "news":
        from indiabloom.news import NewsError, fetch_news

        try:
            return [item.title for item in fetch_news(news_query(ticker))][:MAX_SEEN]
        except NewsError as exc:
            raise AlertError(f"could not read current headlines ({exc}); try again later") from exc
    return []


def apply_alert_text(text: str, path: Path = ALERTS_FILE) -> str:
    """Add a rule or remove one, from the text typed in the TUI. Returns a status message."""
    removal = parse_remove(text)
    rules, next_id = load_rules(path)
    if removal is not None:
        remaining = [r for r in rules if r.id != removal]
        if len(remaining) == len(rules):
            raise AlertError(f"no rule with id {removal}")
        save_rules(remaining, next_id, path)
        return f"removed rule {removal}"
    parsed = parse_rule_text(text)
    rule = Rule(id=next_id, ticker=parsed.ticker, kind=parsed.kind, threshold=parsed.threshold,
                seen=initial_seen(parsed.ticker, parsed.kind))
    save_rules([*rules, rule], next_id + 1, path)
    return f"added rule {rule.id}: {rule.ticker} {describe(rule)}"


def load_log(path: Path = LOG_FILE, limit: int = 30) -> list[dict[str, str]]:
    """The most recent fired alerts, newest first."""
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    return rows[-limit:][::-1]
