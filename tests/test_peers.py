import numpy as np
import pandas as pd

from indiabloom.peers import MIN_OBS, Peer, load_peers, save_peers, statistical_peers


def _closes(days=300, seed=21):
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range(end="2026-10-23", periods=days)
    market = rng.normal(0, 0.01, days)
    # A and B share a strong common factor; C is in a different industry but
    # moves exactly with A, to show that cross-industry pairs are excluded.
    a = 100 * np.exp(np.cumsum(market + rng.normal(0, 0.002, days)))
    b = 100 * np.exp(np.cumsum(market + rng.normal(0, 0.002, days)))
    c = 100 * np.exp(np.cumsum(market + rng.normal(0, 0.002, days)))
    d = 100 * np.exp(np.cumsum(rng.normal(0, 0.01, days)))  # unrelated, same industry as A
    e = 100 * np.exp(np.cumsum(rng.normal(0, 0.01, days)))  # unrelated, other industry
    return pd.DataFrame({"A.NS": a, "B.NS": b, "C.NS": c, "D.NS": d, "E.NS": e}, index=idx)


INDUSTRIES = {"A.NS": "IT", "B.NS": "IT", "C.NS": "Banks", "D.NS": "IT", "E.NS": "Banks"}


def test_peers_stay_within_industry():
    peers = statistical_peers(_closes(), INDUSTRIES, k=5)
    for p in peers:
        assert p.industry == INDUSTRIES[p.ticker]
        assert INDUSTRIES[p.peer] == INDUSTRIES[p.ticker]


def test_most_correlated_same_industry_peer_ranks_first():
    peers = [p for p in statistical_peers(_closes(), INDUSTRIES, k=5) if p.ticker == "A.NS"]
    assert peers[0].peer == "B.NS"
    assert peers[0].corr > peers[-1].corr
    assert "C.NS" not in [p.peer for p in peers]  # different industry is excluded


def test_k_limits_number_of_peers():
    peers = [p for p in statistical_peers(_closes(), INDUSTRIES, k=1) if p.ticker == "A.NS"]
    assert len(peers) == 1


def test_too_little_shared_history_gives_no_peers():
    closes = _closes(days=MIN_OBS - 50)
    assert statistical_peers(closes, INDUSTRIES) == []


def test_save_and_load_round_trip(tmp_path):
    path = tmp_path / "peers.csv"
    save_peers(path, [Peer("A.NS", "B.NS", 0.8123, "IT")])
    loaded = load_peers(path)
    assert loaded["A.NS"][0].peer == "B.NS"
    assert abs(loaded["A.NS"][0].corr - 0.8123) < 1e-4


def test_load_missing_file_returns_empty(tmp_path):
    assert load_peers(tmp_path / "none.csv") == {}
