import pytest

from indiabloom.fundamentals import build_snapshot
from indiabloom.screener import ScreenError, matches, parse_condition, screen


def _snap(ticker, **info):
    base = {"shortName": ticker, "sector": "Financial Services", "industry": "Banks - Regional",
            "marketCap": 1e12, "trailingPE": 12.0, "priceToBook": 2.0, "returnOnEquity": 0.18}
    base.update(info)
    return build_snapshot(ticker, base)


def test_parse_numeric_and_text_conditions():
    c = parse_condition("pe_trailing<20")
    assert (c.field, c.op, c.value) == ("pe_trailing", "<", 20.0)
    assert parse_condition("sector=bank").value == "bank"


@pytest.mark.parametrize("text", ["pe_trailing", "unknown_field>1", "pe_trailing<abc", "sector>bank"])
def test_bad_conditions_are_rejected(text):
    with pytest.raises(ScreenError):
        parse_condition(text)


def test_percent_fields_compare_in_percent_units():
    snap = _snap("A.NS", returnOnEquity=0.18)
    assert matches(snap, [parse_condition("roe>=15")])
    assert not matches(snap, [parse_condition("roe>20")])


def test_market_cap_in_crore():
    snap = _snap("A.NS", marketCap=1e12)  # 1 trillion rupees = 100,000 crore
    assert matches(snap, [parse_condition("market_cap_cr>=50000")])
    assert not matches(snap, [parse_condition("market_cap_cr>200000")])


def test_text_match_is_case_insensitive_substring():
    snap = _snap("A.NS")
    assert matches(snap, [parse_condition("sector=FINANCIAL")])
    assert matches(snap, [parse_condition("industry=banks")])
    assert not matches(snap, [parse_condition("sector=technology")])


def test_missing_value_never_matches():
    snap = _snap("A.NS", trailingPE=None)
    assert not matches(snap, [parse_condition("pe_trailing<100")])


def test_roe_falls_back_to_computed_value():
    snap = build_snapshot("A.NS", {"shortName": "A"}, fetched_at=None)
    snap["annual"] = {"net_income": [["2026-03-31", 200.0]], "equity": [["2026-03-31", 1000.0]]}
    assert matches(snap, [parse_condition("roe=20")])


def test_screen_sorts_and_limits():
    snaps = [
        _snap("LOW.NS", marketCap=1e11, trailingPE=10.0),
        _snap("HIGH.NS", marketCap=5e12, trailingPE=15.0),
        _snap("MID.NS", marketCap=2e12, trailingPE=50.0),
        _snap("NOPE.NS", marketCap=9e12, trailingPE=None),
    ]
    conds = [parse_condition("pe_trailing<=20")]
    result = screen(snaps, conds)
    assert [s["ticker"] for s in result] == ["HIGH.NS", "LOW.NS"]  # by market cap desc, NOPE excluded
    assert [s["ticker"] for s in screen(snaps, conds, top=1)] == ["HIGH.NS"]
    asc = screen(snaps, [], sort_by="pe_trailing", descending=False)
    assert asc[0]["ticker"] == "LOW.NS"
    assert asc[-1]["ticker"] == "NOPE.NS"  # no P/E sorts last
