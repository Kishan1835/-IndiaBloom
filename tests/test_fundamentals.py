from datetime import datetime, timedelta

import numpy as np
import pandas as pd

from indiabloom.fundamentals import (
    build_snapshot,
    fundamentals_rows,
    is_fresh,
    load_snapshot,
    run_fundamentals,
    save_snapshot,
)

NOW = datetime(2026, 10, 25, 12, 0, 0)


def _frame(rows: dict[str, list[float]]) -> pd.DataFrame:
    columns = [pd.Timestamp("2026-03-31"), pd.Timestamp("2025-03-31")]
    return pd.DataFrame.from_dict(rows, orient="index", columns=columns)


def _info(**overrides):
    base = {"shortName": "TEST CO", "sector": "Technology", "industry": "IT Services",
            "marketCap": 4.6e12, "trailingPE": 15.3, "currentPrice": 1150.0}
    base.update(overrides)
    return base


def test_build_snapshot_maps_info_and_statements():
    financials = _frame({"Total Revenue": [1000.0, 900.0], "Net Income": [200.0, np.nan]})
    balance = _frame({"Total Debt": [50.0, 60.0]})
    cashflow = _frame({"Free Cash Flow": [150.0, 140.0]})
    snap = build_snapshot("TEST.NS", _info(), financials, balance, cashflow, fetched_at=NOW)

    assert snap["name"] == "TEST CO"
    assert snap["pe_trailing"] == 15.3
    assert snap["annual"]["revenue"][0] == ["2026-03-31", 1000.0]
    assert snap["annual"]["revenue"][1] == ["2025-03-31", 900.0]
    # NaN in a statement becomes null, not a float NaN in the JSON
    assert snap["annual"]["net_income"][1] == ["2025-03-31", None]
    assert snap["annual"]["total_debt"][0] == ["2026-03-31", 50.0]
    assert snap["annual"]["free_cash_flow"][0] == ["2026-03-31", 150.0]


def test_missing_statement_rows_are_left_out_not_guessed():
    financials = _frame({"Something Else": [1.0, 2.0]})
    snap = build_snapshot("TEST.NS", _info(), financials, None, None, fetched_at=NOW)
    assert snap["annual"] == {}
    assert snap["roe"] is None  # absent info key is None, not 0


def test_nan_and_inf_info_values_become_none():
    snap = build_snapshot("TEST.NS", _info(trailingPE=float("nan"), forwardPE=float("inf")),
                          fetched_at=NOW)
    assert snap["pe_trailing"] is None
    assert snap["pe_forward"] is None


def test_save_load_roundtrip(tmp_path):
    snap = build_snapshot("ABC.NS", _info(), fetched_at=NOW)
    save_snapshot(snap, tmp_path)
    loaded = load_snapshot("ABC.NS", tmp_path)
    assert loaded == snap
    assert load_snapshot("MISSING.NS", tmp_path) is None


def test_freshness_uses_seven_day_window():
    snap = {"fetched_at": NOW.isoformat()}
    assert is_fresh(snap, NOW + timedelta(days=6))
    assert not is_fresh(snap, NOW + timedelta(days=8))
    assert not is_fresh(None, NOW)
    assert not is_fresh({}, NOW)


def test_run_is_resumable_and_skips_fresh_cache(tmp_path):
    calls = []

    def fake_fetch(ticker):
        calls.append(ticker)
        return build_snapshot(ticker, _info(), fetched_at=NOW)

    first = run_fundamentals(["A.NS", "B.NS"], tmp_path, fetch=fake_fetch, sleep_s=0, now=NOW)
    assert first.fetched == 2 and first.skipped_fresh == 0 and first.failed == []

    second = run_fundamentals(["A.NS", "B.NS", "C.NS"], tmp_path, fetch=fake_fetch, sleep_s=0, now=NOW)
    assert second.skipped_fresh == 2
    assert second.fetched == 1
    assert calls == ["A.NS", "B.NS", "C.NS"]


def test_failures_are_reported_not_cached_and_do_not_stop_run(tmp_path):
    def flaky(ticker):
        if ticker == "BAD.NS":
            raise RuntimeError("rate limited")
        return build_snapshot(ticker, _info(), fetched_at=NOW)

    report = run_fundamentals(["BAD.NS", "GOOD.NS"], tmp_path, fetch=flaky, sleep_s=0, now=NOW)
    assert report.fetched == 1
    assert [f.ticker for f in report.failed] == ["BAD.NS"]
    assert "rate limited" in report.failed[0].reason
    assert load_snapshot("BAD.NS", tmp_path) is None  # retried next run


def test_fundamentals_rows_formats_units():
    financials = _frame({"Total Revenue": [2.5e10, 2.0e10]})
    snap = build_snapshot("TEST.NS", _info(returnOnEquity=0.3, marketCap=1e12),
                          financials, fetched_at=NOW)
    rows = dict(fundamentals_rows(snap))
    assert rows["Market cap (Rs cr)"] == "100,000"
    assert rows["ROE"] == "30.0%"
    assert rows["P/E trailing"] == "15.30"
    assert rows["Revenue FY ending 2026-03-31 (Rs cr)"] == "2,500"
def test_fundamentals_rows_computes_roe_when_yfinance_omits_it():
    financials = _frame({"Net Income": [200.0, 180.0]})
    balance = _frame({"Stockholders Equity": [1000.0, 900.0]})
    snap = build_snapshot("TEST.NS", _info(returnOnEquity=None), financials, balance, fetched_at=NOW)
    rows = dict(fundamentals_rows(snap))
    assert rows["ROE (computed: net income / equity)"] == "20.0%"
    assert "ROE" not in rows


def test_usd_reporting_currency_is_labelled_not_converted():
    # Infosys: share price in INR, statements in USD
    financials = _frame({"Total Revenue": [2.0e10, 1.9e10]})
    snap = build_snapshot("INFY.NS", _info(financialCurrency="USD"), financials, fetched_at=NOW)
    rows = dict(fundamentals_rows(snap))
    assert rows["Revenue FY ending 2026-03-31 (USD mn)"] == "20,000 USD mn"
    assert "Revenue FY ending 2026-03-31 (Rs cr)" not in rows
    assert rows["Market cap (Rs cr)"] == "460,000"  # market cap stays INR
