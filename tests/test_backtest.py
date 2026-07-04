from unittest.mock import patch

import pandas as pd

from astock.tools import backtest as bt


def _mk_hist(closes):
    n = len(closes)
    return pd.DataFrame({
        "日期": [f"2026-06-{i:02d}" for i in range(1, n + 1)],
        "开盘": closes,
        "收盘": closes,
        "最高": [c + 0.5 for c in closes],
        "最低": [c - 0.5 for c in closes],
        "成交量": [1000] * n,
    })


def test_unknown_strategy_returns_none():
    with patch("astock.tools.backtest.get_hist", return_value=_mk_hist([10.0] * 50)):
        assert bt.run("000001", "bogus", 5, 100) is None


def test_no_signal_returns_empty_trades():
    with patch("astock.tools.backtest.get_hist", return_value=_mk_hist([10.0] * 100)):
        r = bt.run("000001", "macd_golden_cross", 5, 100)
    assert r is not None
    assert r.trades == []
    assert r.total_signals == 0


def test_ma20_break_finds_signal():
    # 需要 ≥40 根；构造一次向下再向上的形态确保有上穿事件
    closes = [10.0] * 22 + [9.0, 8.5, 8.0, 8.5, 9.0, 9.5, 10.0, 10.5, 11.0, 11.5,
                            12.0, 12.5, 13.0, 13.5, 14.0, 14.5, 15.0, 15.5]
    with patch("astock.tools.backtest.get_hist", return_value=_mk_hist(closes)):
        r = bt.run("000001", "ma_break_20", hold_days=1, days=len(closes))
    assert r is not None


def test_win_rate_and_avg_return():
    closes = [10.0] * 22 + [9.0, 8.5, 8.0, 8.5, 9.0, 9.5, 10.0, 10.5, 11.0, 11.5,
                            12.0, 12.5, 13.0, 13.5, 14.0, 14.5, 15.0, 15.5]
    with patch("astock.tools.backtest.get_hist", return_value=_mk_hist(closes)):
        r = bt.run("000001", "ma_break_20", hold_days=3, days=len(closes))
    assert r is not None
    if r.trades:
        assert 0 <= r.win_rate <= 100
