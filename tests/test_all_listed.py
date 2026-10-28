import pandas as pd

from indiabloom.graph import Graph, parse_relations
from indiabloom.sectors import OTHER, load_rules
from indiabloom.stock_list import build_stock_list, group_from_sector
from indiabloom.universe import Constituent, parse_all_listed
from indiabloom.cli import build_parser

SAMPLE = """SYMBOL,NAME OF COMPANY, SERIES, DATE OF LISTING, PAID UP VALUE, MARKET LOT, ISIN NUMBER, FACE VALUE
INFY,Infosys Limited, EQ,1995-01-01, 5,1, INE009A01021, 5
JPL,Jio Platforms Limited, EQ,2026-10-27, 10,1, INEXXX, 10
SGBX,Sovereign Gold Bond, GB,2020-01-01, 1,1, INEYYY, 1
INFY,Infosys duplicate, EQ,1995-01-01, 5,1, INE009A01021, 5
"""


def test_parse_all_listed_keeps_eq_and_dedupes():
    rows = parse_all_listed(SAMPLE)
    assert [r.ticker for r in rows] == ["INFY.NS", "JPL.NS"]
    assert rows[1].company == "Jio Platforms Limited"
    assert rows[0].industry == ""  # the full list has no industry column


def test_group_from_yahoo_sector():
    assert group_from_sector("Technology", "ANY LTD") == "IT"
    assert group_from_sector("Healthcare", "ANY LTD") == "Pharma"
    assert group_from_sector("Financial Services", "HDFC BANK LTD") == "Banks"
    assert group_from_sector("Financial Services", "BAJAJ FINANCE LTD") == "Financials"
    assert group_from_sector("Utilities", "POWER CO") == "Utilities"  # own group, not lumped into Other
    assert group_from_sector(None, "NO DATA LTD") == OTHER


def test_build_stock_list_falls_back_to_yahoo_sector_only_when_nse_has_no_industry():
    rules = load_rules()
    closes = pd.DataFrame({"JPL.NS": [100.0, 102.0], "POW.NS": [50.0, 49.0]})
    constituents = [
        Constituent("JPL", "JPL.NS", "Jio Platforms Limited", ""),
        Constituent("POW", "POW.NS", "POWER CO LTD", ""),
    ]
    graph = Graph(parse_relations([]))
    rows = {r.ticker: r for r in build_stock_list(constituents, closes, graph, rules, {},
                                                  {"JPL.NS": "Communication Services", "POW.NS": "Utilities"})}
    assert rows["JPL.NS"].group == "Communication Services"
    assert rows["POW.NS"].group == "Utilities"


def test_ui_and_data_commands_accept_all():
    parser = build_parser()
    assert parser.parse_args(["ui", "--index", "all"]).index == "all"
    assert parser.parse_args(["fundamentals", "--index", "all"]).index == "all"
