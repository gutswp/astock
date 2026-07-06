"""做T信号回测：拉过去 N 天分时 → 每天跑 detect_signals → 汇总指标.

数据源：tencent gtimg `kline/mkline` 1min k线（含 OHLC + volume），锚点向前翻。
- vwap 由 close × volume 累积估算
- 覆盖约 20 交易日历史

指标：
- day_low_gap: buy 距日内最低 pct
- day_high_gap: sell 距日内最高 pct
- profit: sell.price - buy.price (每对)
- 负 profit 对数（应 = 0 才对）
- 覆盖率：抓到的最优对 profit / 理论最优(day_high - day_low)

跑法：python -m scripts.backtest_signals
"""
from __future__ import annotations

import json
import statistics
from collections import defaultdict
from datetime import datetime
from pathlib import Path

from astock.data.http import curl_get
from astock.screen.t_signals import detect_signals
from astock.screen.t_trading import score_opening

BACKTEST_CACHE = Path(__file__).resolve().parent.parent / "data" / "backtest_cache"
BACKTEST_CACHE.mkdir(parents=True, exist_ok=True)


def _exchange(code: str) -> str:
    return "sh" if code.startswith(("6", "5", "9")) else "sz"


def _fetch_batch(code: str, anchor: str) -> list[list]:
    ex = _exchange(code)
    url = (
        f"https://ifzq.gtimg.cn/appstock/app/kline/mkline?"
        f"param={ex}{code},m1,{anchor},500"
    )
    raw = curl_get(url, timeout=10)
    d = json.loads(raw)
    return d["data"][f"{ex}{code}"].get("m1", []) or []


def fetch_history(code: str, days_back: int = 30) -> dict[str, list[dict]]:
    """按 anchor 递归拉取，返回 {date_yyyymmdd: [bar dict]}."""
    cache_f = BACKTEST_CACHE / f"{code}_hist.json"
    if cache_f.exists():
        try:
            cached = json.loads(cache_f.read_text())
            # 已缓存的话直接用
            print(f"[{code}] 用缓存 {len(cached)} 天")
            return cached
        except Exception:
            pass

    collected: dict[str, dict] = {}  # ts -> raw bar
    # 从今天倒退，每 3 天一个 anchor
    anchors = []
    today = datetime.now()
    for k in range(0, days_back, 3):
        d = (today.timestamp() - k * 86400)
        dt = datetime.fromtimestamp(d)
        anchors.append(dt.strftime("%Y%m%d150000"))

    for a in anchors:
        try:
            bars = _fetch_batch(code, a)
        except Exception as e:
            print(f"[{code}] anchor={a} 抓取失败：{e}")
            continue
        for b in bars:
            if b and len(b) >= 6:
                collected[b[0]] = b

    # 按日期分组，转成 astock bar dict
    by_date: dict[str, list[dict]] = defaultdict(list)
    for ts, raw in collected.items():
        date = ts[:8]
        # raw: [time, open, close, high, low, volume, {}, extra]
        try:
            open_ = float(raw[1])
            close_ = float(raw[2])
            high_ = float(raw[3])
            low_ = float(raw[4])
            vol = int(float(raw[5]))
        except (ValueError, TypeError):
            continue

        # 转成 astock 里的时间格式 "YYYY-MM-DD HH:MM"
        yyyy_mm_dd = f"{ts[:4]}-{ts[4:6]}-{ts[6:8]}"
        hh_mm = f"{ts[8:10]}:{ts[10:12]}"
        by_date[date].append({
            "time": f"{yyyy_mm_dd} {hh_mm}",
            "open": open_,
            "close": close_,
            "high": high_,
            "low": low_,
            "volume": vol,
            "amount": close_ * vol * 100,  # 手 → 股 * 元
            # vwap 稍后按日累积算
        })

    # 每天内按时间排序 + 补 vwap
    result: dict[str, list[dict]] = {}
    for date, bars in by_date.items():
        if len(bars) < 100:  # 不足半天，跳过
            continue
        bars.sort(key=lambda b: b["time"])
        cum_amt = 0.0
        cum_vol = 0
        for b in bars:
            cum_amt += b["amount"]
            cum_vol += b["volume"] * 100
            b["vwap"] = cum_amt / cum_vol if cum_vol > 0 else b["close"]
        result[date] = bars

    # 缓存
    cache_f.write_text(json.dumps(result, ensure_ascii=False))
    print(f"[{code}] 抓到 {len(result)} 完整交易日")
    return result


def analyze_day(code: str, date: str, bars: list[dict], preclose: float) -> dict:
    """跑 detect_signals，计算指标."""
    scored = score_opening(bars, preclose)
    label = scored["label"]
    sigs = detect_signals(bars, preclose, label, code=code)

    day_low = min(b["low"] for b in bars)
    day_high = max(b["high"] for b in bars)
    day_range = day_high - day_low

    total_profit = 0.0
    n_pairs = 0
    n_losing = 0
    best_buy_gap = None  # 最靠近 day_low 的买点距离
    best_sell_gap = None  # 最靠近 day_high 的卖点距离

    for s in sigs:
        if s["type"] == "buy" and s.get("partner_price"):
            profit = s["partner_price"] - s["price"]
            total_profit += profit
            n_pairs += 1
            if profit < 0:
                n_losing += 1
            gap = (s["price"] - day_low) / day_low * 100 if day_low else 0
            if best_buy_gap is None or gap < best_buy_gap:
                best_buy_gap = gap
        if s["type"] == "sell" and s.get("partner_price"):
            gap = (day_high - s["price"]) / day_high * 100 if day_high else 0
            if best_sell_gap is None or gap < best_sell_gap:
                best_sell_gap = gap

    coverage = (total_profit / day_range * 100) if day_range > 0 else 0

    return {
        "date": date,
        "code": code,
        "label": label,
        "score": scored["score"],
        "preclose": preclose,
        "day_low": day_low,
        "day_high": day_high,
        "day_range": day_range,
        "n_pairs": n_pairs,
        "n_losing": n_losing,
        "total_profit": total_profit,
        "best_buy_gap_pct": best_buy_gap,
        "best_sell_gap_pct": best_sell_gap,
        "coverage_pct": coverage,
        "n_bars": len(bars),
    }


def main():
    codes = ["000063", "002230", "600645", "600011", "601138", "002298", "002266"]

    all_results: list[dict] = []
    for code in codes:
        hist = fetch_history(code)
        # 按日期顺序，用前一天 close 作 preclose
        dates = sorted(hist.keys())
        for i, date in enumerate(dates):
            bars = hist[date]
            preclose = hist[dates[i-1]][-1]["close"] if i > 0 else bars[0]["open"]
            if preclose <= 0:
                continue
            r = analyze_day(code, date, bars, preclose)
            all_results.append(r)

    # 按 code 分组打印
    print()
    print("=" * 120)
    print(f"{'code':<8} {'date':<10} {'label':<6} {'S':>3} {'范围':>10} {'对数':>5} {'亏':>3} {'总盈利':>8} {'覆盖%':>7} {'买离底%':>8} {'卖离顶%':>8}")
    print("=" * 120)
    for r in all_results:
        rng = f"{r['day_low']:.2f}→{r['day_high']:.2f}"
        buy_gap = f"{r['best_buy_gap_pct']:.2f}" if r['best_buy_gap_pct'] is not None else "  —"
        sell_gap = f"{r['best_sell_gap_pct']:.2f}" if r['best_sell_gap_pct'] is not None else "  —"
        print(f"{r['code']:<8} {r['date']:<10} {r['label']:<6} {r['score']:>+3} {rng:>10} {r['n_pairs']:>5} {r['n_losing']:>3} {r['total_profit']:>+8.2f} {r['coverage_pct']:>7.1f} {buy_gap:>8} {sell_gap:>8}")

    # 汇总
    print()
    print("=" * 120)
    print("汇总")
    print("=" * 120)
    total_days = len(all_results)
    total_pairs = sum(r["n_pairs"] for r in all_results)
    total_losing = sum(r["n_losing"] for r in all_results)
    days_with_signals = sum(1 for r in all_results if r["n_pairs"] > 0)
    days_no_signals = total_days - days_with_signals
    total_profit = sum(r["total_profit"] for r in all_results)
    avg_coverage = statistics.mean(r["coverage_pct"] for r in all_results if r["day_range"] > 0)
    buy_gaps = [r["best_buy_gap_pct"] for r in all_results if r["best_buy_gap_pct"] is not None]
    sell_gaps = [r["best_sell_gap_pct"] for r in all_results if r["best_sell_gap_pct"] is not None]

    print(f"总测试日数: {total_days}, 出信号日数: {days_with_signals}, 无信号: {days_no_signals}")
    print(f"总对数: {total_pairs}, 亏损对: {total_losing} ({total_losing/max(total_pairs,1)*100:.1f}%)")
    print(f"总盈利: {total_profit:+.2f} 元/股")
    print(f"平均覆盖率（总盈利 / 日振幅）: {avg_coverage:.1f}%")
    print(f"买点离日内最低 avg={statistics.mean(buy_gaps):.2f}% median={statistics.median(buy_gaps):.2f}%") if buy_gaps else print("无买点数据")
    print(f"卖点离日内最高 avg={statistics.mean(sell_gaps):.2f}% median={statistics.median(sell_gaps):.2f}%") if sell_gaps else print("无卖点数据")


if __name__ == "__main__":
    main()
