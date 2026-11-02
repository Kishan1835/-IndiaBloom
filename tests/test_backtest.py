import numpy as np
import pandas as pd
import pytest

from indiabloom.backtest import BacktestError, backtest, measures, parse_rule


def _closes(days=420, up=20, down=20, seed=3):
    rng = np.random.default_rng(seed)
    index = pd.bdate_range("2024-01-01", periods=days)
    data = {}
    for i in range(up):
        data[f"UP{i}.NS"] = 100 * np.exp(np.cumsum(0.002 + rng.normal(0, 0.01, days)))
    for i in range(down):
        data[f"DN{i}.NS"] = 100 * np.exp(np.cumsum(-0.002 + rng.normal(0, 0.01, days)))
    return pd.DataFrame(data, index=index)


def test_parse_rule_accepts_price_measures_only():
    rule = parse_rule("vol_1y<40")
    assert (rule.field, rule.op, rule.value) == ("vol_1y", "<", 40.0)
    with pytest.raises(BacktestError):
        parse_rule("pe_trailing<20")  # fundamentals have no history, so they are not allowed here
    with pytest.raises(BacktestError):
        parse_rule("ret_1y")


def test_measures_use_only_the_rows_given():
    index = pd.bdate_range("2024-01-01", periods=300)
    prices = np.linspace(100, 200, 300)
    closes = pd.DataFrame({"A.NS": prices}, index=index)
    m = measures(closes)
    expected = (prices[-1] / prices[-253] - 1) * 100  # 252 trading-day lookback
    assert m.loc["A.NS", "ret_1y"] == pytest.approx(expected)


def test_momentum_rule_beats_universe_on_trending_data():
    result = backtest(_closes(), [parse_rule("ret_1y>0")], hold_days=21, top_n=10)
    assert result.periods >= 4
    assert result.excess is not None and result.excess > 0
    assert result.win_rate is not None and result.win_rate > 0.5


def test_rule_that_selects_nothing_is_reported():
    result = backtest(_closes(), [parse_rule("ret_1y>1000")], hold_days=21)
    assert result.periods == 0 and result.avg_selected is None


def test_too_short_history_is_rejected():
    short = _closes(days=100)
    with pytest.raises(BacktestError):
        backtest(short, [parse_rule("ret_1y>0")], hold_days=21)
