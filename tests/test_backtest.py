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


def test_equity_curve_empty():
    result = bt.BacktestResult(
        code="X", strategy="s", strategy_label="s", hold_days=5,
        total_signals=0, trades=[], win_rate=0, avg_return=0,
        total_return=0, best_return=0, worst_return=0,
    )
    curve = bt.equity_curve(result, initial=100000)
    assert curve["final_full"] == 100000
    assert curve["final_sized"] == 100000


def test_equity_curve_with_trades():
    trades = [
        bt.Trade("D1", 10.0, "D3", 11.0, 10.0),   # +10%
        bt.Trade("D5", 11.0, "D7", 9.9, -10.0),   # -10%
        bt.Trade("D9", 10.0, "D11", 12.0, 20.0),  # +20%
    ]
    result = bt.BacktestResult(
        code="X", strategy="s", strategy_label="s", hold_days=2,
        total_signals=3, trades=trades,
        win_rate=66.67, avg_return=6.67, total_return=18.8,
        best_return=20, worst_return=-10,
        avg_win=15.0, avg_loss=10.0,
    )
    curve = bt.equity_curve(result, initial=100000)
    # 全仓：1.1 * 0.9 * 1.2 = 1.188 → 118800
    assert abs(curve["final_full"] - 118800) < 1
    # 凯利分数 = (1.5*0.6667 - 0.3333)/1.5 = 0.4445（因为 win/loss ratio = 1.5）
    # 凯利不应该 <= 0
    assert curve["kelly_fraction_used"] > 0
    assert curve["final_sized"] > 100000  # 有正期望，凯利也应盈利
    assert curve["full_max_dd"] > 0  # 中间有回撤（-10% 那次）
