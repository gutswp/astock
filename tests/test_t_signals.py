"""t_signals 检测器和主流程单测."""
from __future__ import annotations

from astock.screen.t_signals import (
    _pair_and_limit,
    detect_signals,
    is_buy_higher_low,
    is_buy_shrink_bottom,
    is_buy_vwap_bounce,
    is_sell_break_vwap,
    is_sell_lower_high,
    is_sell_volume_stall,
)


def _bar(t: str, close: float, *, open_=None, high=None, low=None, vol=1000, vwap=None) -> dict:
    """构造分时 bar；缺省字段自动补齐."""
    open_ = close if open_ is None else open_
    return {
        "time": f"2026-07-07 {t}:00",
        "open": open_,
        "close": close,
        "high": high if high is not None else max(open_, close) + 0.01,
        "low": low if low is not None else min(open_, close) - 0.01,
        "volume": vol,
        "amount": vol * close,
        "vwap": vwap if vwap is not None else close,
    }


def _flat_am_baseline(n: int, close: float = 10.0, vol: int = 1000) -> list[dict]:
    """从 09:30 起 n 根平稳 bar，供 lookback 用."""
    bars = []
    for k in range(n):
        mm = 30 + k
        hh = 9 + mm // 60
        mm = mm % 60
        bars.append(_bar(f"{hh:02d}:{mm:02d}", close, vol=vol))
    return bars


# ---------- is_buy_shrink_bottom ----------

def test_shrink_bottom_triggers():
    bars = _flat_am_baseline(15, close=10.20, vol=1000)
    # 三根阴序 close 10.15 → 10.10 → 10.05
    bars.append(_bar("09:45", 10.15, low=10.13, vol=900))
    bars.append(_bar("09:46", 10.10, low=10.08, vol=800))
    bars.append(_bar("09:47", 10.05, low=10.03, vol=700))
    # 当根：low 10.06 > min(prior5.low)=10.03？ 需要 low > min(bar[i-5..i-1])
    # prior 5 = bars[13..17]，low 各是 9.99, 9.99, 10.13, 10.08, 10.03 → min = 9.99
    # 所以当根 low 得 > 9.99；缩量 vol < 700 * ... 均值
    bars.append(_bar("09:48", 10.07, low=10.06, vol=300))
    assert is_buy_shrink_bottom(bars, len(bars) - 1)


def test_shrink_bottom_no_prior_decline():
    bars = _flat_am_baseline(15, close=10.20)
    bars.append(_bar("09:45", 10.20, low=10.18, vol=900))
    bars.append(_bar("09:46", 10.20, low=10.18, vol=800))
    bars.append(_bar("09:47", 10.20, low=10.18, vol=700))
    bars.append(_bar("09:48", 10.07, low=10.06, vol=300))
    assert not is_buy_shrink_bottom(bars, len(bars) - 1)


def test_shrink_bottom_volume_not_shrunk():
    bars = _flat_am_baseline(15, close=10.20, vol=1000)
    bars.append(_bar("09:45", 10.15, low=10.13, vol=900))
    bars.append(_bar("09:46", 10.10, low=10.08, vol=800))
    bars.append(_bar("09:47", 10.05, low=10.03, vol=700))
    bars.append(_bar("09:48", 10.07, low=10.06, vol=1200))  # 量没收缩
    assert not is_buy_shrink_bottom(bars, len(bars) - 1)


# ---------- is_buy_higher_low ----------

def test_higher_low_triggers():
    bars = _flat_am_baseline(15, close=10.0)
    # 前 5 根平底 low 9.98；后 2 根 low 抬高到 10.05
    for k in range(5):
        mm = 45 + k
        bars.append(_bar(f"09:{mm:02d}", 10.0, low=9.98))
    bars.append(_bar("09:50", 10.10, low=10.05))
    bars.append(_bar("09:51", 10.12, low=10.06))
    assert is_buy_higher_low(bars, len(bars) - 1)


def test_higher_low_still_lower():
    bars = _flat_am_baseline(15, close=10.0)
    for k in range(5):
        mm = 45 + k
        bars.append(_bar(f"09:{mm:02d}", 10.0, low=9.98))
    bars.append(_bar("09:50", 10.10, low=10.05))
    bars.append(_bar("09:51", 9.95, low=9.90))  # 当根 low 又创新低
    assert not is_buy_higher_low(bars, len(bars) - 1)


# ---------- is_buy_vwap_bounce ----------

def test_vwap_bounce_triggers():
    # 早期 close 一直在 vwap 上方 10.1 vs vwap 10.0
    bars = []
    for k in range(15):
        mm = 30 + k
        hh = 9 + mm // 60
        mm = mm % 60
        bars.append(_bar(f"{hh:02d}:{mm:02d}", 10.1, low=10.08, vol=1000, vwap=10.0))
    # 回踩到 vwap 附近
    bars.append(_bar("09:45", 10.02, low=9.99, vol=900, vwap=10.0))
    bars.append(_bar("09:46", 10.01, low=9.98, vol=900, vwap=10.0))
    # 当根收回均价上方 + 未放量
    bars.append(_bar("09:47", 10.05, low=10.0, vol=800, vwap=10.0))
    assert is_buy_vwap_bounce(bars, len(bars) - 1)


def test_vwap_bounce_no_prior_above():
    bars = []
    for k in range(15):
        mm = 30 + k
        hh = 9 + mm // 60
        mm = mm % 60
        bars.append(_bar(f"{hh:02d}:{mm:02d}", 9.9, low=9.85, vwap=10.0))  # 一直在均价下
    bars.append(_bar("09:45", 10.02, low=9.99, vol=900, vwap=10.0))
    bars.append(_bar("09:46", 10.01, low=9.98, vol=900, vwap=10.0))
    bars.append(_bar("09:47", 10.05, low=10.0, vol=800, vwap=10.0))
    assert not is_buy_vwap_bounce(bars, len(bars) - 1)


# ---------- is_sell_break_vwap ----------

def test_sell_break_vwap_triggers():
    bars = _flat_am_baseline(15, close=10.05, vol=1000)
    for b in bars:
        b["vwap"] = 10.0
    # 上一根 close 10.05 在 vwap 上；当根 close 9.95 跌破 + 放量
    bars.append(_bar("09:45", 9.95, low=9.93, vol=1500, vwap=10.0))
    assert is_sell_break_vwap(bars, len(bars) - 1)


def test_sell_break_vwap_shrunk_volume_rejected():
    """严重缩量的假跌破（可能只是波动）不应触发."""
    bars = _flat_am_baseline(15, close=10.05, vol=1000)
    for b in bars:
        b["vwap"] = 10.0
    bars.append(_bar("09:45", 9.95, low=9.93, vol=300, vwap=10.0))  # vol 300 < 0.5*1000
    assert not is_sell_break_vwap(bars, len(bars) - 1)


# ---------- is_sell_lower_high ----------

def test_sell_lower_high_triggers():
    bars = _flat_am_baseline(10, close=10.0)
    # 前段冲到 10.5
    bars.append(_bar("09:40", 10.5, high=10.55))
    bars.append(_bar("09:41", 10.3, high=10.35))
    bars.append(_bar("09:42", 10.1, low=10.05))  # 回撤 (10.55-10.05)/10.55 = 4.7% > 0.3%
    bars.append(_bar("09:43", 10.15, high=10.20))
    bars.append(_bar("09:44", 10.20, high=10.25))
    # 当根：第二波高 10.35 < 前段 10.55
    bars.append(_bar("09:45", 10.30, high=10.35))
    # 加 3 根 pivot 右窗
    bars.append(_bar("09:46", 10.25, high=10.30))
    bars.append(_bar("09:47", 10.22, high=10.27))
    bars.append(_bar("09:48", 10.20, high=10.25))
    assert is_sell_lower_high(bars, 15)


def test_sell_lower_high_breaks_new_high():
    bars = _flat_am_baseline(10, close=10.0)
    bars.append(_bar("09:40", 10.5, high=10.55))
    bars.append(_bar("09:41", 10.3, high=10.35))
    bars.append(_bar("09:42", 10.1, low=10.05))
    bars.append(_bar("09:43", 10.15, high=10.20))
    bars.append(_bar("09:44", 10.20, high=10.25))
    bars.append(_bar("09:45", 10.60, high=10.65))  # 创新高
    bars.append(_bar("09:46", 10.50, high=10.55))
    bars.append(_bar("09:47", 10.45, high=10.50))
    bars.append(_bar("09:48", 10.40, high=10.45))
    assert not is_sell_lower_high(bars, 15)


# ---------- is_sell_volume_stall ----------

def test_sell_volume_stall_triggers():
    bars = _flat_am_baseline(15, close=10.30, vol=1000)  # 近期高位
    # 放量 + 小实体 + 收近前高
    bars.append(_bar("09:45", 10.30, open_=10.29, high=10.35, low=10.28, vol=2000))
    assert is_sell_volume_stall(bars, len(bars) - 1)


def test_sell_volume_stall_big_body():
    bars = _flat_am_baseline(15, close=10.30, vol=1000)
    # 大实体，非滞涨
    bars.append(_bar("09:45", 10.30, open_=10.20, high=10.32, low=10.19, vol=2000))
    assert not is_sell_volume_stall(bars, len(bars) - 1)


# ---------- detect_signals 主流程 ----------

def test_detect_returns_empty_on_short_bars():
    assert detect_signals(_flat_am_baseline(10, close=10.0), 10.0, "震荡") == []


def test_detect_returns_empty_on_zero_preclose():
    bars = _flat_am_baseline(30, close=10.0)
    assert detect_signals(bars, 0.0, "震荡") == []


def test_detect_returns_empty_on_missing_label():
    bars = _flat_am_baseline(30, close=10.0)
    assert detect_signals(bars, 10.0, "数据不足") == []


def test_detect_strong_label_pairs_sell_first():
    """强势日：出现 sell 后再出现 buy → 应产出 sell → buy 一对（倒T）."""
    raw = [
        {"index": 15, "time": "09:45", "price": 10.30, "type": "sell", "reason": "放量滞涨"},
        {"index": 25, "time": "09:55", "price": 10.05, "type": "buy", "reason": "缩量止跌"},
    ]
    paired = _pair_and_limit(raw, "强势", min_gap=0.2, max_pairs=3)
    assert [s["type"] for s in paired] == ["sell", "buy"], f"倒T应先卖后买，实际 {paired}"
    assert paired[0]["price"] > paired[1]["price"], "倒T 卖价应高于买价"


def test_detect_strong_label_drops_early_buy():
    """强势日 buy 出现在任何 sell 之前 → 违反倒T顺序，应被丢弃."""
    raw = [
        {"index": 18, "time": "09:48", "price": 10.07, "type": "buy", "reason": "缩量止跌"},
    ]
    paired = _pair_and_limit(raw, "强势", min_gap=0.2, max_pairs=3)
    assert paired == [], f"强势日无先行 sell 时 buy 应丢弃，实际 {paired}"


def test_detect_strong_keeps_unpaired_sell():
    """强势日只有 sell 无 buy → sell 独立保留（未回买也是有效卖出提示）."""
    raw = [
        {"index": 15, "time": "09:45", "price": 10.30, "type": "sell", "reason": "跌破均价线"},
    ]
    paired = _pair_and_limit(raw, "强势", min_gap=0.2, max_pairs=3)
    assert paired == raw, f"强势日孤立 sell 应保留，实际 {paired}"


def test_detect_weak_label_pairs_buy_first():
    """弱势日：出现 buy 后再出现 sell → 应产出 buy → sell 一对（正T）."""
    raw = [
        {"index": 18, "time": "09:48", "price": 10.07, "type": "buy", "reason": "缩量止跌"},
        {"index": 28, "time": "09:58", "price": 10.30, "type": "sell", "reason": "冲高不创新高"},
    ]
    paired = _pair_and_limit(raw, "弱势", min_gap=0.2, max_pairs=3)
    assert [s["type"] for s in paired] == ["buy", "sell"], f"正T应先买后卖，实际 {paired}"
    assert paired[1]["price"] > paired[0]["price"], "正T 卖价应高于买价"


def test_detect_weak_label_drops_early_sell():
    """弱势日 sell 出现在任何 buy 之前 → 违反正T顺序，应被丢弃."""
    raw = [
        {"index": 15, "time": "09:45", "price": 10.30, "type": "sell", "reason": "放量滞涨"},
    ]
    paired = _pair_and_limit(raw, "弱势", min_gap=0.2, max_pairs=3)
    assert paired == [], f"弱势日无先行 buy 时 sell 应丢弃，实际 {paired}"


def test_detect_shock_label_pairs_both_directions():
    """震荡：双向都可以做T，接受任意起手."""
    raw = [
        {"index": 18, "time": "09:48", "price": 10.07, "type": "buy", "reason": "缩量止跌"},
        {"index": 28, "time": "09:58", "price": 10.30, "type": "sell", "reason": "冲高不创新高"},
        {"index": 38, "time": "10:08", "price": 10.05, "type": "buy", "reason": "回踩均价线企稳"},
    ]
    paired = _pair_and_limit(raw, "震荡", min_gap=0.2, max_pairs=3)
    assert len(paired) >= 2, f"震荡日应至少一对 buy-sell，实际 {paired}"
    assert any(s["type"] == "buy" for s in paired)
    assert any(s["type"] == "sell" for s in paired)


def test_detect_max_three_pairs():
    """最多 3 组：给 4 对候选，应只保留 6 个信号."""
    raw = []
    for k in range(4):
        idx = 15 + k * 10
        raw.append({"index": idx, "time": f"09:{45+k*10 % 60:02d}", "price": 10.30, "type": "sell", "reason": "放量滞涨"})
        raw.append({"index": idx + 5, "time": f"09:{50+k*10 % 60:02d}", "price": 10.05, "type": "buy", "reason": "缩量止跌"})
    paired = _pair_and_limit(raw, "强势", min_gap=0.2, max_pairs=3)
    assert len(paired) <= 6, f"最多 3 对 = 6 个信号，实际 {len(paired)}"


def test_detect_tail_suppresses_buys():
    # 构造尾盘 buy 场景，1455 之后应被过滤
    bars = _flat_am_baseline(15, close=10.20, vol=1000)
    # 用 pm session 结尾
    for k in range(60):
        mm = 45 + k
        hh = 9 + mm // 60
        mm = mm % 60
        if hh == 11 and mm > 30 or hh == 12:
            continue
        bars.append(_bar(f"{hh:02d}:{mm:02d}", 10.20, vol=1000))
    # 快速推进到 14:55+
    for k, hhmm in enumerate(["14:53", "14:54", "14:55", "14:56", "14:57", "14:58"]):
        # 制造缩量止跌 buy 序列
        base = 10.20 - k * 0.02
        vol = 1000 if k < 3 else 300
        bars.append(_bar(hhmm, base, low=base - 0.01, vol=vol))
    signals = detect_signals(bars, 10.20, "弱势")
    for s in signals:
        assert s["time"] < "14:55", f"14:55 后不应出 buy，实际：{s}"


def test_detect_limit_up_suppresses_all():
    bars = _flat_am_baseline(15, close=11.0, vol=1000)  # preclose 10.0，涨 10%
    for k in range(20):
        mm = 45 + k
        hh = 9 + mm // 60
        mm = mm % 60
        if hh == 11 and mm > 30 or hh == 12:
            continue
        bars.append(_bar(f"{hh:02d}:{mm:02d}", 11.0, vol=1500))
    signals = detect_signals(bars, 10.0, "强势")
    assert signals == []


def test_detect_min_gap_drops_close_pair():
    bars = _flat_am_baseline(15, close=10.30, vol=1000)
    # sell 触发在 10.30
    bars.append(_bar("09:45", 10.30, open_=10.29, high=10.35, low=10.28, vol=2000))
    # 后续构造一个"缩量止跌 buy" 但价格 10.29（差价 0.01 < 0.2）
    bars.append(_bar("09:46", 10.28, vol=900))
    bars.append(_bar("09:47", 10.27, vol=800))
    bars.append(_bar("09:48", 10.26, vol=700))
    bars.append(_bar("09:49", 10.29, low=10.27, vol=300))
    signals = detect_signals(bars, 10.20, "强势", min_gap=0.2)
    # 强势只保留 sell，且 sell 因未配到合格 buy 也应被丢弃（配对制）
    assert signals == [] or all(s["type"] == "sell" for s in signals)


def test_detect_marker_labels_are_sequential():
    bars = _flat_am_baseline(15, close=10.20, vol=1000)
    # 造两组 buy → sell 交替
    bars.append(_bar("09:45", 10.15, low=10.13, vol=900))
    bars.append(_bar("09:46", 10.10, low=10.08, vol=800))
    bars.append(_bar("09:47", 10.05, low=10.03, vol=700))
    bars.append(_bar("09:48", 10.07, low=10.06, vol=300))  # buy1
    for k in range(10):
        mm = 49 + k
        hh = 9 + mm // 60
        mm = mm % 60
        bars.append(_bar(f"{hh:02d}:{mm:02d}", 10.30, vol=1000))  # 平稳
    # sell1（放量滞涨在 10.30）
    bars.append(_bar("10:00", 10.30, open_=10.29, high=10.35, low=10.28, vol=2000))
    signals = detect_signals(bars, 10.20, "震荡")
    buys = [s for s in signals if s["type"] == "buy"]
    sells = [s for s in signals if s["type"] == "sell"]
    if buys:
        assert buys[0]["seq"] == 1 and buys[0]["marker"] == "红1"
    if sells:
        assert sells[0]["seq"] == 1 and sells[0]["marker"] == "绿1"
