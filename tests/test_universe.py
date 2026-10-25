from datetime import datetime, timedelta

import numpy as np
import pandas as pd
import pytest

from indiabloom.universe import UniverseError, load_index, parse_constituents
from indiabloom.universe_scan import holdout_hit_rate, scan_universe, t_statistic

CSV = (
    "Company Name,Industry,Symbol,Series,ISIN Code\n"
    "Infosys Ltd.,IT,INFY,EQ,INE009A01021\n"
    "Tata Consultancy Services Ltd.,IT,TCS,EQ,INE467B01029\n"
    "Infosys Ltd.,IT,INFY,EQ,INE009A01021\n"
)


def test_parse_constituents_builds_tickers_and_dedupes():
    cons = parse_constituents(CSV)
    assert [c.ticker for c in cons] == ["INFY.NS", "TCS.NS"]
    assert cons[0].company == "Infosys Ltd."
    assert cons[1].industry == "IT"


def test_parse_constituents_rejects_wrong_header():
    with pytest.raises(UniverseError, match="missing columns"):
        parse_constituents("Name,Sector\nX,Y\n")


def test_parse_constituents_rejects_empty_file():
    with pytest.raises(UniverseError, match="no constituents"):
        parse_constituents("Company Name,Industry,Symbol\n")


def test_load_index_uses_fresh_cache_without_network(tmp_path, monkeypatch):
    (tmp_path / "nifty50.csv").write_text(CSV, encoding="utf-8")
    import indiabloom.universe as universe

    def no_network(*args, **kwargs):
        raise AssertionError("network must not be called for a fresh cache")

    monkeypatch.setattr(universe.urllib.request, "urlopen", no_network)
    cons = load_index("nifty50", cache_dir=tmp_path, now=datetime.now())
    assert len(cons) == 2


def test_load_index_rejects_unknown_name(tmp_path):
    with pytest.raises(UniverseError, match="unknown index"):
        load_index("nifty9000", cache_dir=tmp_path)


def test_t_statistic_matches_formula():
    assert t_statistic(0.0, 100) == 0.0
    assert t_statistic(0.2, 102) == pytest.approx(0.2 * (100 / 0.96) ** 0.5)


def _closes(days=400, seed=9):
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range(end="2026-10-23", periods=days)
    leader = rng.normal(0, 0.012, days)
    data = {"LEAD": 100 * np.exp(np.cumsum(leader))}
    # strong follower reacts to leader's previous session
    lagged = np.concatenate([[0.0], leader[:-1]])
    data["STRONG.NS"] = 500 * np.exp(np.cumsum(0.8 * lagged + rng.normal(0, 0.01, days)))
    # noise follower
    data["NOISE.NS"] = 300 * np.exp(np.cumsum(rng.normal(0, 0.01, days)))
    return pd.DataFrame(data, index=idx), leader


def test_scan_ranks_planted_follower_first_and_skips_leader():
    closes, _ = _closes()
    labels = {"STRONG.NS": ("Strong Co", "Tech")}
    rows = scan_universe("LEAD", closes, labels)
    assert rows[0].ticker == "STRONG.NS"
    assert rows[0].company == "Strong Co"
    assert rows[0].t_stat > 5
    assert all(r.ticker != "LEAD" for r in rows)


def test_scan_skips_series_with_too_little_data():
    closes, _ = _closes(days=400)
    closes["SHORT.NS"] = np.nan
    closes.loc[closes.index[-10:], "SHORT.NS"] = 100.0
    rows = scan_universe("LEAD", closes, {})
    assert "SHORT.NS" not in [r.ticker for r in rows]


def test_scan_raises_for_missing_leader():
    closes, _ = _closes()
    with pytest.raises(KeyError):
        scan_universe("NOPE", closes, {})


def test_holdout_recovers_planted_direction_out_of_sample():
    closes, _ = _closes()
    from indiabloom.analytics import log_returns

    result = holdout_hit_rate(log_returns(closes["LEAD"]), log_returns(closes["STRONG.NS"]))
    assert result.hit_rate is not None and result.hit_rate > 0.7
    assert result.beta_train is not None and result.beta_train > 0


def test_holdout_on_noise_is_near_chance():
    closes, _ = _closes()
    from indiabloom.analytics import log_returns

    result = holdout_hit_rate(log_returns(closes["LEAD"]), log_returns(closes["NOISE.NS"]))
    assert result.hit_rate is not None
    assert 0.35 < result.hit_rate < 0.65


def test_holdout_insufficient_history_returns_none():
    closes, _ = _closes(days=40)
    from indiabloom.analytics import log_returns

    result = holdout_hit_rate(log_returns(closes["LEAD"]), log_returns(closes["STRONG.NS"]))
    assert result.hit_rate is None
