import numpy as np
import pandas as pd

from indiabloom.indian_links import rank_indian_links


def test_rank_indian_links_sorts_by_absolute_correlation_and_keeps_sign():
    index = pd.bdate_range("2024-01-01", periods=80)
    base = np.linspace(100, 140, 80)
    frame = pd.DataFrame({
        "A.NS": base,
        "B.NS": base * 2 + 3,
        "C.NS": 20000 / base,
        "US": base,
    }, index=index)
    links = rank_indian_links("A.NS", frame, {"A.NS": "IT", "B.NS": "IT", "C.NS": "Auto"}, limit=5)
    assert [l.other for l in links] == ["C.NS", "B.NS"]
    assert links[0].corr < -0.99 and links[1].corr > 0.99
    assert all(l.observations == 79 for l in links)
    assert links[0].sector == "IT" and links[0].other_sector == "Auto"
    assert links[1].other_sector == "IT"


def test_indian_links_require_shared_observations_and_ignore_us():
    index = pd.bdate_range("2024-01-01", periods=20)
    frame = pd.DataFrame({"A.NS": range(20), "B.NS": range(20), "US": range(20)}, index=index)
    assert rank_indian_links("A.NS", frame, {}, min_observations=30) == []
    assert all(l.other.endswith(".NS") for l in rank_indian_links("A.NS", frame, {}, min_observations=10))


def test_missing_ticker_has_no_links():
    frame = pd.DataFrame({"A.NS": [1.0, 2.0]})
    assert rank_indian_links("MISSING.NS", frame, {}) == []
