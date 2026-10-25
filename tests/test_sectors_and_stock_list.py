from datetime import date

import pandas as pd
import pytest

from indiabloom.graph import Graph, parse_relations
from indiabloom.sectors import OTHER, classify, load_rules
from indiabloom.stock_list import build_stock_list, filter_group, price_change
from indiabloom.universe import Constituent

RULES = load_rules()


@pytest.mark.parametrize("company,industry,expected", [
    ("Infosys Ltd.", "Information Technology", "IT"),
    ("HDFC Bank Ltd.", "Financial Services", "Banks"),
    ("Bajaj Finance Ltd.", "Financial Services", OTHER),   # non-bank lender, not a bank
    ("Sun Pharmaceutical Industries Ltd.", "Healthcare", "Pharma"),
    ("Larsen & Toubro Ltd.", "Capital Goods", "Manufacturing"),
    ("Hindalco Industries Ltd.", "Metals & Mining", "Manufacturing"),
    ("Some Power Co Ltd.", "Power", OTHER),
])
def test_classify_sector_groups(company, industry, expected):
    assert classify(company, industry, RULES) == expected


def test_price_change_uses_last_two_closes():
    idx = pd.to_datetime(["2026-10-22", "2026-10-23"])
    closes = pd.DataFrame({"A.NS": [100.0, 110.0], "B.NS": [float("nan"), 5.0]}, index=idx)
    last, change = price_change(closes, "A.NS")
    assert last == 110.0 and change == pytest.approx(10.0)
    assert price_change(closes, "MISSING.NS") == (None, None)


def test_build_stock_list_combines_index_and_graph_stocks():
    idx = pd.to_datetime(["2026-10-22", "2026-10-23"])
    closes = pd.DataFrame({"INFY.NS": [1000.0, 1010.0], "MU": [100.0, 95.0]}, index=idx)
    graph = Graph(parse_relations([{
        "source": "MU", "target": "KAYNES.NS", "relation": "thematic",
        "confidence": "low", "rationale": "theme", "sources": []}]))
    cons = [Constituent("INFY", "INFY.NS", "Infosys Ltd.", "Information Technology")]
    rows = {r.ticker: r for r in build_stock_list(cons, closes, graph, RULES, {"INFY.NS": -2.5})}

    assert rows["INFY.NS"].group == "IT"
    assert rows["INFY.NS"].us_t == -2.5
    assert rows["MU"].group == "US"
    assert rows["KAYNES.NS"].group == OTHER  # no prices, still listed
    assert rows["KAYNES.NS"].last is None
    assert [r.ticker for r in filter_group(list(rows.values()), "US")] == ["MU"]
    assert len(filter_group(list(rows.values()), None)) == 3


def test_rules_file_covers_expected_groups():
    groups = {r.group for r in RULES}
    assert {"IT", "Banks", "Manufacturing", "Pharma"} <= groups
