"""简易信号回测：在历史上找信号触发日，模拟买入并 N 天后卖出."""
from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from astock.data.provider import get_hist
from astock.screen.indicators import (
    calc_cci,
    calc_dmi,
    calc_kdj,
    calc_ma,
    calc_macd,
    calc_rsi,
    calc_sar,
)

STRATEGIES = {
    "macd_golden_cross": "MACD 金叉",
    "rsi_oversold": "RSI 超卖反弹（<30 → ≥30）",
    "ma_break_20": "上穿 MA20",
    "ma_break_60": "上穿 MA60",
    "kdj_golden_cross": "KDJ 金叉（低位）",
    "cci_oversold": "CCI 超卖反弹（<-100 → ≥-100）",
    "dmi_golden_cross": "DMI 金叉（+DI 上穿 -DI）",
    "sar_bullish_flip": "SAR 翻多",
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
    name: str = ""       # 显示名，可空
    avg_win: float = 0.0  # 平均盈利单笔 % （凯利用）
    avg_loss: float = 0.0  # 平均亏损单笔 %（绝对值，凯利用）


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
    elif strategy == "cci_oversold":
        if n < 20:
            return idxs
        cci = calc_cci(highs, lows, closes)
        for i in range(1, n):
            if pd.isna(cci.iloc[i - 1]) or pd.isna(cci.iloc[i]):
                continue
            if cci.iloc[i - 1] < -100 and cci.iloc[i] >= -100:
                idxs.append(i)
    elif strategy == "dmi_golden_cross":
        if n < 40:
            return idxs
        plus, minus, adx = calc_dmi(highs, lows, closes)
        for i in range(1, n):
            if pd.isna(plus.iloc[i - 1]) or pd.isna(minus.iloc[i - 1]) or pd.isna(adx.iloc[i]):
                continue
            if plus.iloc[i - 1] < minus.iloc[i - 1] and plus.iloc[i] >= minus.iloc[i] and adx.iloc[i] >= 20:
                idxs.append(i)
    elif strategy == "sar_bullish_flip":
        if n < 5:
            return idxs
        _, trend = calc_sar(highs, lows)
        for i in range(1, n):
            if trend.iloc[i - 1] == -1 and trend.iloc[i] == 1:
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

    wins_list = [t.return_pct for t in trades if t.return_pct > 0]
    losses_list = [-t.return_pct for t in trades if t.return_pct < 0]  # 取正
    wins = len(wins_list)
    avg = sum(t.return_pct for t in trades) / len(trades)
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
        avg_win=round(sum(wins_list) / len(wins_list), 2) if wins_list else 0.0,
        avg_loss=round(sum(losses_list) / len(losses_list), 2) if losses_list else 0.0,
    )


def run_batch(codes: list[str], strategy: str, hold_days: int = 5,
              days: int = 250) -> list[BacktestResult]:
    """并发跑多个 code。返回按 code 顺序的结果列表（跳过没结果的）."""
    from concurrent.futures import ThreadPoolExecutor
    results: list[BacktestResult] = []
    with ThreadPoolExecutor(max_workers=6) as ex:
        futures = {ex.submit(run, c, strategy, hold_days, days): c for c in codes}
        for c, fut in zip(codes, [None] * len(codes)):
            pass  # placeholder
        # 按 code 原顺序回收
        rmap: dict[str, BacktestResult] = {}
        for fut, code in futures.items():
            try:
                r = fut.result()
            except Exception:
                r = None
            if r is not None:
                rmap[code] = r
    for c in codes:
        if c in rmap:
            results.append(rmap[c])
    return results


def equity_curve(result: BacktestResult, initial: float = 100000.0,
                 kelly_fraction_val: float = 0.0) -> dict:
    """给一次回测结果，返回资金曲线。
    kelly_fraction_val 是采用的分数凯利比例（0 = 全仓），其余留现金。
    返回：
      { "trades_idx": [0,1,...], "full": [...], "sized": [...],
        "full_max_dd": %, "sized_max_dd": %, "final_full": ..., "final_sized": ... }
    """
    if not result.trades:
        return {"trades_idx": [], "full": [initial], "sized": [initial],
                "full_max_dd": 0, "sized_max_dd": 0,
                "final_full": initial, "final_sized": initial}

    # 计算凯利分数（如果给了）
    f = kelly_fraction_val
    if f <= 0 and result.avg_win > 0 and result.avg_loss > 0:
        # 自动用 result 的胜率/盈亏比算标准凯利
        from astock.tools.sizing import kelly_fraction
        f = max(0.0, kelly_fraction(result.win_rate, result.avg_win, result.avg_loss))
    f = min(f, 1.0)

    full = [initial]
    sized = [initial]
    cur_full, cur_sized = initial, initial
    for t in result.trades:
        r = t.return_pct / 100
        cur_full = cur_full * (1 + r)
        cur_sized = cur_sized * (1 + r * f) if f > 0 else cur_sized
        full.append(cur_full)
        sized.append(cur_sized)

    def _max_dd(series: list[float]) -> float:
        peak = series[0]
        max_dd = 0.0
        for v in series:
            if v > peak:
                peak = v
            dd = (peak - v) / peak * 100 if peak else 0
            if dd > max_dd:
                max_dd = dd
        return max_dd

    return {
        "trades_idx": list(range(len(full))),
        "full": [round(v, 2) for v in full],
        "sized": [round(v, 2) for v in sized],
        "full_max_dd": round(_max_dd(full), 2),
        "sized_max_dd": round(_max_dd(sized), 2),
        "final_full": round(full[-1], 2),
        "final_sized": round(sized[-1], 2),
        "kelly_fraction_used": round(f, 4),
    }


STRATEGY_FAMILIES = {
    "ma_break": "均线突破",
    "rsi": "RSI 超卖反弹",
    "macd": "MACD 金叉",
    "kdj": "KDJ 金叉（低位）",
}


def _signals_with_params(closes, highs, lows, family: str, params: dict) -> list[int]:
    from astock.screen.indicators import (
        calc_kdj, calc_ma, calc_macd, calc_rsi,
    )
    n = len(closes)
    idxs: list[int] = []
    if family == "ma_break":
        period = params["period"]
        if n < period + 1:
            return idxs
        ma = calc_ma(closes, period)
        for i in range(1, n):
            if pd.isna(ma.iloc[i - 1]) or pd.isna(ma.iloc[i]):
                continue
            if closes.iloc[i - 1] < ma.iloc[i - 1] and closes.iloc[i] >= ma.iloc[i]:
                idxs.append(i)
    elif family == "rsi":
        period = params["period"]
        if n < period + 2:
            return idxs
        rsi = calc_rsi(closes, period)
        for i in range(1, n):
            if pd.isna(rsi.iloc[i - 1]) or pd.isna(rsi.iloc[i]):
                continue
            if rsi.iloc[i - 1] < 30 and rsi.iloc[i] >= 30:
                idxs.append(i)
    elif family == "macd":
        fast = params.get("fast", 12)
        slow = params.get("slow", 26)
        sig = params.get("signal", 9)
        if n < slow + sig:
            return idxs
        dif, dea, _ = calc_macd(closes, fast=fast, slow=slow, signal=sig)
        for i in range(1, n):
            if pd.isna(dif.iloc[i - 1]) or pd.isna(dea.iloc[i - 1]):
                continue
            if dif.iloc[i - 1] < dea.iloc[i - 1] and dif.iloc[i] >= dea.iloc[i]:
                idxs.append(i)
    elif family == "kdj":
        if n < 12:
            return idxs
        k, d, _ = calc_kdj(highs, lows, closes,
                            n=params.get("n", 9),
                            m1=params.get("m1", 3),
                            m2=params.get("m2", 3))
        threshold = params.get("threshold", 50)
        for i in range(1, n):
            if pd.isna(k.iloc[i - 1]) or pd.isna(d.iloc[i - 1]):
                continue
            if k.iloc[i - 1] < d.iloc[i - 1] and k.iloc[i] >= d.iloc[i] and k.iloc[i] < threshold:
                idxs.append(i)
    return idxs


def _grid_for(family: str) -> list[dict]:
    if family == "ma_break":
        return [{"period": p, "hold": h}
                for p in [5, 10, 15, 20, 30, 40, 60]
                for h in [3, 5, 10, 20]]
    if family == "rsi":
        return [{"period": p, "hold": h}
                for p in [7, 9, 14, 21, 28]
                for h in [3, 5, 10, 20]]
    if family == "macd":
        return [{"fast": f, "slow": s, "signal": sig, "hold": h}
                for f in [8, 12, 16]
                for s in [22, 26, 30]
                for sig in [7, 9, 11]
                for h in [3, 5, 10, 20]]
    if family == "kdj":
        return [{"n": n, "m1": m1, "m2": m2, "threshold": th, "hold": h}
                for n in [7, 9, 14]
                for m1 in [3]
                for m2 in [3]
                for th in [30, 50, 70]
                for h in [3, 5, 10, 20]]
    return []


def grid_search(code: str, family: str, days: int = 500) -> list[dict]:
    """跑一个策略族的参数网格。返回按 kelly 降序的 top 10."""
    if family not in STRATEGY_FAMILIES:
        return []
    df = get_hist(code, days)
    if df.empty or len(df) < 60:
        return []
    closes = df["收盘"].astype(float)
    highs = df["最高"].astype(float)
    lows = df["最低"].astype(float)

    from astock.tools.sizing import kelly_fraction

    combos = _grid_for(family)
    results = []
    for c in combos:
        hold = c["hold"]
        params = {k: v for k, v in c.items() if k != "hold"}
        idxs = _signals_with_params(closes, highs, lows, family, params)
        rets = []
        for idx in idxs:
            if idx + hold >= len(closes):
                continue
            ep = float(closes.iloc[idx])
            xp = float(closes.iloc[idx + hold])
            rets.append((xp - ep) / ep * 100)
        if len(rets) < 3:
            continue
        wins = [r for r in rets if r > 0]
        losses = [-r for r in rets if r < 0]
        win_rate = len(wins) / len(rets) * 100
        avg_w = (sum(wins) / len(wins)) if wins else 0
        avg_l = (sum(losses) / len(losses)) if losses else 0
        avg = sum(rets) / len(rets)
        k = kelly_fraction(win_rate, avg_w, avg_l) if (avg_w and avg_l) else 0
        results.append({
            "params": c,
            "count": len(rets),
            "win_rate": round(win_rate, 2),
            "avg_return": round(avg, 2),
            "avg_win": round(avg_w, 2),
            "avg_loss": round(avg_l, 2),
            "kelly": round(k, 4),
        })
    # 按凯利 + 样本量综合排序
    results.sort(
        key=lambda x: (x["kelly"] * min(x["count"] / 5, 2), x["avg_return"]),
        reverse=True,
    )
    return results[:10]


def aggregate(results: list[BacktestResult]) -> dict:
    """跨股票聚合：平均胜率、平均单笔收益、总样本、样本加权收益."""
    if not results:
        return {"count": 0, "total_trades": 0, "avg_win_rate": 0,
                "sample_weighted_avg_return": 0, "codes_positive": 0}
    total_trades = sum(len(r.trades) for r in results)
    win_rates = [r.win_rate for r in results if r.trades]
    avg_win_rate = sum(win_rates) / len(win_rates) if win_rates else 0
    weighted = sum(r.avg_return * len(r.trades) for r in results if r.trades)
    weighted_avg = weighted / total_trades if total_trades else 0
    codes_positive = sum(1 for r in results if r.avg_return > 0)
    return {
        "count": len(results),
        "total_trades": total_trades,
        "avg_win_rate": round(avg_win_rate, 2),
        "sample_weighted_avg_return": round(weighted_avg, 2),
        "codes_positive": codes_positive,
    }
