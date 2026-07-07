"""做T信号回测：拉过去 N 天分时 → 每天跑 detect_signals → 汇总指标.

数据源：tencent gtimg `kline/mkline` 1min k线（含 OHLC + volume），锚点向前翻。
- 覆盖约最近 20 交易日的 1 分钟历史（与实盘 trends2 同粒度）
- vwap 由 amount(≈close×vol) 累积估算，逼近 eastmoney 均价线

核心指标（回答"是否抓到最佳买卖点 + 配对是否合理"）：
- best_buy_gap:  最优买点距日内最低 pct（越小越好，0=买在最低）
- best_sell_gap: 最优卖点距日内最高 pct（越小越好，0=卖在最高）
- n_losing:      亏损对数（买价≥卖价，应为 0）
- coverage:      总盈利 / 日振幅（抓住了多少肉）
- orphans:       未配对信号数（应为 0）

跑法：PYTHONPATH=src python -m scripts.backtest_signals
"""
from __future__ import annotations

import json
import statistics
import subprocess
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path

from astock.screen.t_signals import detect_signals
from astock.screen.t_trading import score_opening

BACKTEST_CACHE = Path(__file__).resolve().parent.parent / "data" / "backtest_cache"
BACKTEST_CACHE.mkdir(parents=True, exist_ok=True)

START_DATE = "20260601"  # 回测起始（腾讯 1min 实际最早约 6/8）

HOLDINGS = [
    "002230", "002298", "002153", "512660", "600011",
    "000063", "002266", "515230", "601138", "159869",
    "603236", "002312", "600111", "002902", "002085",
    "600645", "601888", "000505", "002241", "600410",
]


def _exchange(code: str) -> str:
    return "sh" if code.startswith(("6", "5", "9")) else "sz"


def _fetch_batch(code: str, anchor: str, retries: int = 5) -> list[list]:
    ex = _exchange(code)
    url = (
        f"https://ifzq.gtimg.cn/appstock/app/kline/mkline?"
        f"param={ex}{code},m1,{anchor},500"
    )
    for _ in range(retries):
        r = subprocess.run(["curl", "-s", "--max-time", "20", url], capture_output=True)
        out = r.stdout.decode("utf-8", "replace")
        if out.strip():
            try:
                d = json.loads(out)
                return d["data"][f"{ex}{code}"].get("m1", []) or []
            except Exception:
                pass
    return []


def fetch_history(code: str, days_back: int = 40) -> dict[str, list[dict]]:
    """按 anchor 递归拉取，返回 {date_yyyymmdd: [bar dict]}."""
    cache_f = BACKTEST_CACHE / f"{code}_hist.json"
    if cache_f.exists():
        try:
            cached = json.loads(cache_f.read_text())
            print(f"[{code}] 用缓存 {len(cached)} 天")
            return cached
        except Exception:
            pass

    collected: dict[str, list] = {}
    today = datetime.now()
    for k in range(0, days_back, 2):
        a = (today - timedelta(days=k)).strftime("%Y%m%d150000")
        for b in _fetch_batch(code, a):
            if b and len(b) >= 6:
                collected[b[0]] = b

    by_date: dict[str, list[dict]] = defaultdict(list)
    for ts, raw in collected.items():
        date = ts[:8]
        try:
            open_, close_, high_, low_ = (float(raw[1]), float(raw[2]), float(raw[3]), float(raw[4]))
            vol = int(float(raw[5]))
        except (ValueError, TypeError):
            continue
        yyyy_mm_dd = f"{ts[:4]}-{ts[4:6]}-{ts[6:8]}"
        hh_mm = f"{ts[8:10]}:{ts[10:12]}"
        by_date[date].append({
            "time": f"{yyyy_mm_dd} {hh_mm}",
            "open": open_, "close": close_, "high": high_, "low": low_,
            "volume": vol, "amount": close_ * vol * 100,
        })

    result: dict[str, list[dict]] = {}
    for date, bars in by_date.items():
        if len(bars) < 100:
            continue
        bars.sort(key=lambda b: b["time"])
        cum_amt = cum_vol = 0.0
        for b in bars:
            cum_amt += b["amount"]
            cum_vol += b["volume"] * 100
            b["vwap"] = cum_amt / cum_vol if cum_vol > 0 else b["close"]
        result[date] = bars

    cache_f.write_text(json.dumps(result, ensure_ascii=False))
    print(f"[{code}] 抓到 {len(result)} 完整交易日")
    return result


def analyze_day(code: str, date: str, bars: list[dict], preclose: float) -> dict:
    scored = score_opening(bars, preclose)
    label = scored["label"]
    sigs = detect_signals(bars, preclose, label, code=code)

    day_low = min(b["low"] for b in bars)
    day_high = max(b["high"] for b in bars)
    day_range = day_high - day_low

    buys = [s for s in sigs if s["type"] == "buy"]
    sells = [s for s in sigs if s["type"] == "sell"]
    orphans = sum(1 for s in sigs if not s.get("partner"))

    # 配对盈亏：遍历 pair_id
    pairs: dict = defaultdict(dict)
    for s in sigs:
        pid = s.get("pair_id")
        if pid is not None:
            pairs[pid][s["type"]] = s
    total_profit = 0.0
    n_pairs = n_losing = 0
    for pid, pr in pairs.items():
        if "buy" in pr and "sell" in pr:
            profit = pr["sell"]["price"] - pr["buy"]["price"]
            total_profit += profit
            n_pairs += 1
            if profit <= 0:
                n_losing += 1

    best_buy_gap = min(((s["price"] - day_low) / day_low * 100 for s in buys), default=None)
    best_sell_gap = min(((day_high - s["price"]) / day_high * 100 for s in sells), default=None)
    coverage = (total_profit / day_range * 100) if day_range > 0 else 0

    return {
        "date": date, "code": code, "label": label, "score": scored["score"],
        "preclose": preclose, "day_low": day_low, "day_high": day_high,
        "day_range": day_range, "day_range_pct": day_range / preclose * 100 if preclose else 0,
        "n_buys": len(buys), "n_sells": len(sells), "n_pairs": n_pairs,
        "n_losing": n_losing, "orphans": orphans, "total_profit": total_profit,
        "best_buy_gap_pct": best_buy_gap, "best_sell_gap_pct": best_sell_gap,
        "coverage_pct": coverage, "n_bars": len(bars),
    }


def main():
    all_results: list[dict] = []
    for code in HOLDINGS:
        try:
            hist = fetch_history(code)
        except Exception as e:
            print(f"[{code}] 抓取异常：{e}")
            continue
        dates = sorted(d for d in hist.keys() if d >= START_DATE)
        all_dates = sorted(hist.keys())
        for date in dates:
            bars = hist[date]
            idx = all_dates.index(date)
            preclose = hist[all_dates[idx - 1]][-1]["close"] if idx > 0 else bars[0]["open"]
            if preclose <= 0:
                continue
            all_results.append(analyze_day(code, date, bars, preclose))

    all_results.sort(key=lambda r: (r["code"], r["date"]))

    print()
    print("=" * 128)
    print(f"{'code':<8}{'date':<10}{'label':<6}{'S':>3}{'范围':>13}{'振幅%':>7}"
          f"{'买':>3}{'卖':>3}{'对':>3}{'亏':>3}{'孤':>3}{'总盈利':>8}{'覆盖%':>7}{'买离底%':>8}{'卖离顶%':>8}")
    print("=" * 128)
    for r in all_results:
        rng = f"{r['day_low']:.2f}→{r['day_high']:.2f}"
        bg = f"{r['best_buy_gap_pct']:.2f}" if r["best_buy_gap_pct"] is not None else "—"
        sg = f"{r['best_sell_gap_pct']:.2f}" if r["best_sell_gap_pct"] is not None else "—"
        print(f"{r['code']:<8}{r['date']:<10}{r['label']:<6}{r['score']:>+3}{rng:>13}{r['day_range_pct']:>7.2f}"
              f"{r['n_buys']:>3}{r['n_sells']:>3}{r['n_pairs']:>3}{r['n_losing']:>3}{r['orphans']:>3}"
              f"{r['total_profit']:>+8.2f}{r['coverage_pct']:>7.1f}{bg:>8}{sg:>8}")

    print()
    print("=" * 128)
    print("汇总")
    print("=" * 128)
    n = len(all_results)
    if n == 0:
        print("无结果")
        return
    with_sig = sum(1 for r in all_results if r["n_pairs"] > 0)
    total_pairs = sum(r["n_pairs"] for r in all_results)
    total_losing = sum(r["n_losing"] for r in all_results)
    total_orphans = sum(r["orphans"] for r in all_results)
    buy_gaps = [r["best_buy_gap_pct"] for r in all_results if r["best_buy_gap_pct"] is not None]
    sell_gaps = [r["best_sell_gap_pct"] for r in all_results if r["best_sell_gap_pct"] is not None]
    covs = [r["coverage_pct"] for r in all_results if r["day_range"] > 0]

    print(f"测试样本(股×日): {n}  |  出信号日: {with_sig} ({with_sig/n*100:.0f}%)  |  无信号日: {n-with_sig}")
    print(f"总配对: {total_pairs}  |  亏损对(买≥卖): {total_losing} ({total_losing/max(total_pairs,1)*100:.1f}%)  |  孤儿信号: {total_orphans}")
    print(f"覆盖率(盈利/日振幅) 均值: {statistics.mean(covs):.1f}%  中位: {statistics.median(covs):.1f}%")
    if buy_gaps:
        print(f"买点离日内最低  均值: {statistics.mean(buy_gaps):.2f}%  中位: {statistics.median(buy_gaps):.2f}%  最差: {max(buy_gaps):.2f}%")
    if sell_gaps:
        print(f"卖点离日内最高  均值: {statistics.mean(sell_gaps):.2f}%  中位: {statistics.median(sell_gaps):.2f}%  最差: {max(sell_gaps):.2f}%")

    out = BACKTEST_CACHE / "_last_run.json"
    out.write_text(json.dumps(all_results, ensure_ascii=False, indent=2))
    print(f"\n结果已存 {out}")


if __name__ == "__main__":
    main()
