import csv
from datetime import date, datetime

import pytest

from indiabloom.alerts import (
    AlertError,
    Rule,
    append_log,
    deal_key,
    evaluate,
    load_rules,
    save_rules,
    validate,
)
from indiabloom.deals import Deal

TODAY = date(2026, 10, 26)


def _deal(date_s="2026-10-23", client="BIG BUYER LLP", side="BUY", qty=1000, price=1500.0, symbol="INFY"):
    return Deal(date_s, symbol, "bulk", client, side, qty, price, qty * price / 1e7)


def test_price_above_fires_once_per_day():
    rules = [Rule(1, "INFY.NS", "price_above", 1700.0)]
    quotes = {"INFY.NS": (1750.0, 1.0)}
    alerts, rules = evaluate(rules, quotes, [], {}, TODAY)
    assert len(alerts) == 1 and "at or above 1700" in alerts[0].message
    again, rules = evaluate(rules, quotes, [], {}, TODAY)
    assert again == []  # same day: no repeat
    tomorrow, _ = evaluate(rules, quotes, [], {}, date(2026, 10, 27))
    assert len(tomorrow) == 1


def test_price_below_and_missing_quote():
    rules = [Rule(1, "INFY.NS", "price_below", 1200.0), Rule(2, "TCS.NS", "price_below", 3000.0)]
    quotes = {"INFY.NS": (1150.0, -2.0)}  # TCS has no quote at all
    alerts, _ = evaluate(rules, quotes, [], {}, TODAY)
    assert [a.rule_id for a in alerts] == [1]


def test_move_alerts_use_day_change():
    rules = [Rule(1, "MU", "move_below", -3.0), Rule(2, "MU", "move_above", 3.0)]
    alerts, _ = evaluate(rules, {"MU": (100.0, -4.2)}, [], {}, TODAY)
    assert [a.rule_id for a in alerts] == [1]
    assert "down -4.20% today" in alerts[0].message


def test_deal_rule_alerts_only_on_new_deals():
    old = _deal("2026-10-01", client="OLD SELLER")
    rules = [Rule(1, "INFY.NS", "deal", seen=[deal_key(old)])]
    deals = [old, _deal("2026-10-23")]
    alerts, rules = evaluate(rules, {}, deals, {}, TODAY)
    assert len(alerts) == 1 and "BIG BUYER LLP" in alerts[0].message
    again, _ = evaluate(rules, {}, deals, {}, TODAY)
    assert again == []  # already seen


def test_deal_rule_ignores_other_stocks():
    rules = [Rule(1, "TCS.NS", "deal")]
    alerts, _ = evaluate(rules, {}, [_deal(symbol="INFY")], {}, TODAY)
    assert alerts == []


def test_news_rule_alerts_once_per_headline():
    rules = [Rule(1, "MU", "news", seen=["old headline"])]
    headlines = {"MU": ["old headline", "Micron wins contract"]}
    alerts, rules = evaluate(rules, {}, [], headlines, TODAY)
    assert [a.message for a in alerts] == ["MU headline: Micron wins contract"]
    again, _ = evaluate(rules, {}, [], headlines, TODAY)
    assert again == []


def test_validate_rejects_bad_rules():
    with pytest.raises(AlertError):
        validate("price_sideways", 10.0)
    with pytest.raises(AlertError):
        validate("price_above", None)
    validate("deal", None)  # no number needed


def test_rules_roundtrip_and_next_id(tmp_path):
    path = tmp_path / "alerts.json"
    save_rules([Rule(3, "INFY.NS", "price_above", 1700.0, last_fired="2026-10-25", seen=["x"])], 4, path)
    rules, next_id = load_rules(path)
    assert next_id == 4
    assert rules == [Rule(3, "INFY.NS", "price_above", 1700.0, last_fired="2026-10-25", seen=["x"])]
    assert load_rules(tmp_path / "missing.json") == ([], 1)


def test_append_log_writes_header_once(tmp_path):
    from indiabloom.alerts import Alert
    path = tmp_path / "log.csv"
    when = datetime(2026, 10, 26, 9, 0, 0)
    append_log([Alert(1, "INFY.NS", "first")], when, path)
    append_log([Alert(1, "INFY.NS", "second")], when, path)
    with path.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.reader(handle))
    assert rows[0] == ["time", "rule_id", "ticker", "message"]
    assert [r[3] for r in rows[1:]] == ["first", "second"]
