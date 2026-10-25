from indiabloom.deals import (
    DealsError,
    deals_for,
    load_history,
    merge_history,
    parse_deals,
    save_history,
)

BULK = """Date,Symbol,Security Name,Client Name,Buy/Sell,Quantity Traded,Trade Price / Wght. Avg. Price,Remarks
23-OCT-2026,BONFIG,Bonfiglioli,CATAMARAN   VENTURES LLP,BUY,1045000,581.35,-
23-OCT-2026,BONFIG,Bonfiglioli,SOME SELLER,SELL,500000,580.00,-
23-OCT-2026,COMSYN,Commercial,ARIHANT CAPITAL,BUY,210629,217.21,-
23-OCT-2026,BROKEN,Broken,BAD ROW,BUY,notanumber,10,-
"""


def test_parse_bulk_rows_normalises_fields():
    deals = parse_deals(BULK, "bulk")
    assert len(deals) == 3  # malformed row skipped, not fatal
    first = deals[0]
    assert first.date == "2026-10-23"
    assert first.symbol == "BONFIG"
    assert first.client == "CATAMARAN VENTURES LLP"  # double spaces collapsed
    assert first.side == "BUY"
    assert first.quantity == 1045000
    assert abs(first.value_cr - 1045000 * 581.35 / 1e7) < 1e-9


def test_no_records_file_gives_no_deals():
    assert parse_deals("NO RECORDS,,,,,,\n", "block") == []


def test_missing_columns_is_an_error():
    try:
        parse_deals("Date,Symbol\n23-OCT-2026,X\n", "bulk")
    except DealsError as exc:
        assert "missing columns" in str(exc)
    else:
        raise AssertionError("expected DealsError")


def test_merge_dedupes_and_counts_new_rows():
    existing = parse_deals(BULK, "bulk")
    merged, added = merge_history(existing, parse_deals(BULK, "bulk"))
    assert added == 0
    assert len(merged) == len(existing)

    newer = parse_deals(BULK.replace("23-OCT-2026", "26-OCT-2026"), "bulk")
    merged, added = merge_history(existing, newer)
    assert added == len(newer)


def test_history_roundtrip_and_lookup(tmp_path):
    path = tmp_path / "deals.csv"
    deals = parse_deals(BULK, "bulk")
    save_history(deals, path)
    loaded = load_history(path)
    assert sorted(d.key() for d in loaded) == sorted(d.key() for d in deals)

    mine = deals_for("BONFIG.NS", loaded)
    assert {d.symbol for d in mine} == {"BONFIG"}
    assert len(mine) == 2
    assert mine[0].value_cr >= mine[1].value_cr  # largest first within a day


def test_missing_history_file_is_empty(tmp_path):
    assert load_history(tmp_path / "none.csv") == []
