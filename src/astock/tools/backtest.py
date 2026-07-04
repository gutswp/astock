"""简易信号回测：在历史上找信号触发日，模拟买入并 N 天后卖出."""
from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from astock.data.provider import get_hist
from astock.screen.indicators import (
    calc_kdj,
    calc_ma,
    calc_macd,
    calc_rsi,
)

STRATEGIES = {
    "macd_golden_cross": "MACD 金叉",
    "rsi_oversold": "RSI 超卖反弹（<30 → ≥30）",
    "ma_break_20": "上穿 MA20",
    "ma_break_60": "上穿 MA60",
    "kdj_golden_cross": "KDJ 金叉（低位）",
}


@dataclass
class Trade:
    entry_date: str
    entry_price: float
    exit_date: str
    exit_price: float
    return_pct: float


@dataclass
class BacktestResult:
    code: str
    strategy: str
    strategy_label: str
    hold_days: int
    total_signals: int
    trades: list[Trade]
    win_rate: float
    avg_return: float
    total_return: float
    best_return: float
    worst_return: float


def _signal_indices(closes: pd.Series, highs: pd.Series, lows: pd.Series,
                    strategy: str) -> list[int]:
    """返回策略触发的 bar index 列表."""
    n = len(closes)
    idxs: list[int] = []

    if strategy == "macd_golden_cross":
        if n < 35:
            return idxs
        dif, dea, _ = calc_macd(closes)
        for i in range(1, n):
            if pd.isna(dif.iloc[i - 1]) or pd.isna(dea.iloc[i - 1]):
                continue
            if dif.iloc[i - 1] < dea.iloc[i - 1] and dif.iloc[i] >= dea.iloc[i]:
                idxs.append(i)
    elif strategy == "rsi_oversold":
        if n < 16:
            return idxs
        rsi = calc_rsi(closes)
        for i in range(1, n):
            if pd.isna(rsi.iloc[i - 1]) or pd.isna(rsi.iloc[i]):
                continue
            if rsi.iloc[i - 1] < 30 and rsi.iloc[i] >= 30:
                idxs.append(i)
    elif strategy in ("ma_break_20", "ma_break_60"):
        period = 20 if strategy == "ma_break_20" else 60
        if n < period + 1:
            return idxs
        ma = calc_ma(closes, period)
        for i in range(1, n):
            if pd.isna(ma.iloc[i - 1]) or pd.isna(ma.iloc[i]):
                continue
            if closes.iloc[i - 1] < ma.iloc[i - 1] and closes.iloc[i] >= ma.iloc[i]:
                idxs.append(i)
    elif strategy == "kdj_golden_cross":
        if n < 12:
            return idxs
        k, d, _ = calc_kdj(highs, lows, closes)
        for i in range(1, n):
            if pd.isna(k.iloc[i - 1]) or pd.isna(d.iloc[i - 1]):
                continue
            if k.iloc[i - 1] < d.iloc[i - 1] and k.iloc[i] >= d.iloc[i] and k.iloc[i] < 50:
                idxs.append(i)

    return idxs


def run(code: str, strategy: str, hold_days: int = 5, days: int = 250) -> BacktestResult | None:
    """跑一次回测。days 指定历史 K 线长度，hold_days 是持有天数."""
    if strategy not in STRATEGIES:
        return None
    df = get_hist(code, days)
    if df.empty or len(df) < 40:
        return None

    dates = df["日期"].astype(str).tolist()
    closes = df["收盘"].astype(float)
    highs = df["最高"].astype(float)
    lows = df["最低"].astype(float)

    signals = _signal_indices(closes, highs, lows, strategy)
    trades: list[Trade] = []
    for idx in signals:
        exit_idx = idx + hold_days
        if exit_idx >= len(closes):
            continue  # 未到期，忽略
        entry_p = float(closes.iloc[idx])
        exit_p = float(closes.iloc[exit_idx])
        ret = (exit_p - entry_p) / entry_p * 100
        trades.append(Trade(
            entry_date=dates[idx],
            entry_price=round(entry_p, 3),
            exit_date=dates[exit_idx],
            exit_price=round(exit_p, 3),
            return_pct=round(ret, 2),
        ))

    if not trades:
        return BacktestResult(
            code=code, strategy=strategy, strategy_label=STRATEGIES[strategy],
            hold_days=hold_days, total_signals=len(signals), trades=[],
            win_rate=0, avg_return=0, total_return=0,
            best_return=0, worst_return=0,
        )

    wins = sum(1 for t in trades if t.return_pct > 0)
    avg = sum(t.return_pct for t in trades) / len(trades)
    # 假设每次全仓（可比性用）
    total = 1.0
    for t in trades:
        total *= (1 + t.return_pct / 100)
    total_return = (total - 1) * 100
    best = max(t.return_pct for t in trades)
    worst = min(t.return_pct for t in trades)

    return BacktestResult(
        code=code, strategy=strategy, strategy_label=STRATEGIES[strategy],
        hold_days=hold_days, total_signals=len(signals), trades=trades,
        win_rate=round(wins / len(trades) * 100, 2),
        avg_return=round(avg, 2),
        total_return=round(total_return, 2),
        best_return=round(best, 2),
        worst_return=round(worst, 2),
    )
