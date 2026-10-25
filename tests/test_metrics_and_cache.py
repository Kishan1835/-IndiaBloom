from datetime import datetime, timedelta

import pandas as pd
import pytest

import indiabloom.market as market
from indiabloom.demo import synthetic_closes
from indiabloom.scanner import pair_metrics


def test_us_indian_pair_uses_next_session_with_us_leader():
    closes = synthetic_closes("MU", {"FOLLOW.NS": 0.9}, days=300, seed=2)
    m = pair_metrics("FOLLOW.NS", "MU", closes)
    assert m.method == "next-session"
    assert m.leader == "MU"
    assert m.corr is not None and m.corr > 0.5


def test_same_market_pair_uses_same_day_and_no_beta():
    closes = synthetic_closes("MU", {"FOLLOW.NS": 0.9}, days=300, seed=2)
    closes["OTHER.NS"] = closes["FOLLOW.NS"] * 1.01  # perfectly tracks FOLLOW
    m = pair_metrics("FOLLOW.NS", "OTHER.NS", closes)
    assert m.method == "same-day"
    assert m.leader == ""
    assert m.corr == pytest.approx(1.0, abs=1e-9)
    assert m.beta is None


def test_missing_ticker_raises_key_error():
    closes = synthetic_closes("MU", {}, days=60)
    with pytest.raises(KeyError):
        pair_metrics("MU", "NOPE.NS", closes)


def _fake_download(calls):
    def download(ticker, period):
        calls.append(ticker)
        index = pd.bdate_range(end="2026-10-23", periods=40)
        return pd.Series(range(100, 140), index=index, dtype=float)
    return download


def test_fetch_closes_uses_fresh_cache_without_downloading(tmp_path, monkeypatch):
    calls: list[str] = []
    monkeypatch.setattr(market, "_download", _fake_download(calls))
    now = datetime(2026, 10, 25, 9, 0)
    market.fetch_closes(["INFY.NS"], "1y", cache_dir=tmp_path, now=now)
    assert calls == ["INFY.NS"]

    # second call within the age limit must read the cache
    market.fetch_closes(["INFY.NS"], "1y", cache_dir=tmp_path, now=now + timedelta(hours=1))
    assert calls == ["INFY.NS"]


def test_fetch_closes_refreshes_stale_cache(tmp_path, monkeypatch):
    calls: list[str] = []
    monkeypatch.setattr(market, "_download", _fake_download(calls))
    now = datetime(2026, 10, 25, 9, 0)
    market.fetch_closes(["INFY.NS"], "1y", cache_dir=tmp_path, now=now)
    market.fetch_closes(["INFY.NS"], "1y", cache_dir=tmp_path, now=now + timedelta(days=2))
    assert calls == ["INFY.NS", "INFY.NS"]


def test_fetch_closes_raises_when_nothing_returned(tmp_path, monkeypatch):
    monkeypatch.setattr(market, "_download", lambda t, p: None)
    with pytest.raises(market.MarketDataError):
        market.fetch_closes(["NOPE.NS"], "1y", cache_dir=tmp_path)
