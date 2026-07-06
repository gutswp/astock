"""做T买卖点信号引擎。

按《中兴通讯做T交易规则手册V1.0》检测分时买卖点：
- 5 个原子检测器（3 类买点 + 3 类卖点，冲高不创新高与第二波冲高失败合并为 pivot 检测）
- 屏蔽区间：尾盘 buy / 涨跌停 / 数据不足
- 按当日 label 过滤（强势只倒T、弱势只正T、震荡双向）
- 配对纪律：≤3 组、每对差价 ≥ 0.2 元
- 输出编号 seq，前端渲染成红/绿 markPoint（红N=买，绿N=卖）
"""
from __future__ import annotations

from statistics import mean

_MIN_INDEX = 15  # 9:45 后才知道当日 label，之前不出信号
_TAIL_SUPPRESS_MINUTES = 5  # 14:55 后不出 buy
_MAIN_LIMIT_PCT = 9.8  # 主板 10% 涨跌停留 0.2 安全垫
_GEM_LIMIT_PCT = 19.8  # 创业板/科创板 20%

_LABEL_ORDER = {"强势": 2, "偏强": 1, "震荡": 0, "偏弱": -1, "弱势": -2}
_REASON_PRIORITY = {
    # 手册外扩展：日内极值突破 —— 权重最高，抓"大波段"
    "急拉尖顶": 5,
    "急跌捶底": 5,
    # 手册内 3 类卖点
    "跌破均价线": 3,
    "冲高不创新高": 2,
    "放量滞涨": 1,
    # 手册内 3 类买点
    "缩量止跌": 3,
    "回踩均价线企稳": 2,
    "不再创新低": 1,
}

_HIGH_PRIORITY_REASONS = {"急拉尖顶", "急跌捶底"}


def _hhmm(bar: dict) -> str:
    return bar["time"][11:16]


def _is_gem(code: str) -> bool:
    return code.startswith(("300", "301", "688"))


def _session_start(bars: list[dict], i: int) -> int:
    """返回 bars[i] 所在半日 session 的起始 index（上午/下午边界不跨）."""
    cur_hhmm = _hhmm(bars[i])
    cur_session = "am" if cur_hhmm <= "11:30" else "pm"
    j = i
    while j > 0:
        prev = _hhmm(bars[j - 1])
        prev_session = "am" if prev <= "11:30" else "pm"
        if prev_session != cur_session:
            break
        j -= 1
    return j


def _safe_window(bars: list[dict], i: int, back: int) -> list[dict] | None:
    """取 bars[i-back .. i-1]，同 session 且 back 根足够；否则 None."""
    if i - back < 0:
        return None
    start = _session_start(bars, i)
    if i - back < start:
        return None
    return bars[i - back : i]


def _lookback_ok(bars: list[dict], i: int, back: int) -> bool:
    return _safe_window(bars, i, back) is not None


def _is_limit(bar: dict, preclose: float, code: str) -> bool:
    if preclose <= 0:
        return False
    limit_pct = _GEM_LIMIT_PCT if _is_gem(code) else _MAIN_LIMIT_PCT
    return abs(bar["close"] - preclose) / preclose * 100 >= limit_pct


# ---------- 原子检测器 ----------

def is_buy_shrink_bottom(bars: list[dict], i: int) -> bool:
    """缩量止跌：前置连续下跌 + 缩量 + 不创新低."""
    if not _lookback_ok(bars, i, 5):
        return False
    prior = bars[i - 5 : i]
    c = bars[i]

    # 三根阴序 close[i-3] > close[i-2] > close[i-1]
    if not (bars[i - 3]["close"] > bars[i - 2]["close"] > bars[i - 1]["close"]):
        return False

    prior_vol = mean(b["volume"] for b in prior)
    if prior_vol <= 0 or c["volume"] >= prior_vol * 0.7:
        return False

    prior_min_low = min(b["low"] for b in prior)
    if c["low"] <= prior_min_low:
        return False

    return True


def is_buy_higher_low(bars: list[dict], i: int) -> bool:
    """不再创新低：形成小平台（近 2 根低点 > 前 4-8 根最低）."""
    if not _lookback_ok(bars, i, 8):
        return False
    ref = bars[i - 8 : i - 3]
    ref_min = min(b["low"] for b in ref)
    return bars[i]["low"] > ref_min and bars[i - 1]["low"] > ref_min


def is_buy_vwap_bounce(bars: list[dict], i: int) -> bool:
    """回踩均价线企稳：曾在均价线上 → 触到均价线 → 收回上方 + 未放量."""
    if not _lookback_ok(bars, i, 8):
        return False
    c = bars[i]
    if c["vwap"] <= 0:
        return False

    early = bars[i - 8 : i - 3]
    early_above = mean(b["close"] for b in early) > bars[i - 6]["vwap"]
    if not early_above:
        return False

    recent_lows = [b["low"] for b in bars[i - 2 : i + 1]]
    if min(recent_lows) > c["vwap"]:
        return False

    if c["close"] < c["vwap"]:
        return False

    prior_vol = mean(b["volume"] for b in bars[i - 5 : i])
    if prior_vol > 0 and c["volume"] >= prior_vol * 1.2:
        return False

    return True


def is_sell_break_vwap(bars: list[dict], i: int) -> bool:
    """跌破均价线：上一根还在均价线上，本根收在下 + 有量能（不要求 1.2x 放量）。"""
    if not _lookback_ok(bars, i, 5):
        return False
    prev = bars[i - 1]
    c = bars[i]
    if prev["vwap"] <= 0 or c["vwap"] <= 0:
        return False
    if not (prev["close"] >= prev["vwap"] and c["close"] < c["vwap"]):
        return False

    prior_vol = mean(b["volume"] for b in bars[i - 5 : i])
    if prior_vol > 0 and c["volume"] < prior_vol * 0.5:
        # 量能太少（缩量假破位），拒绝
        return False

    return True


def is_sell_lower_high(bars: list[dict], i: int) -> bool:
    """冲高不创新高 / 第二波冲高失败：本根为 ±2 pivot 且高点低于前段高，且中间有回撤."""
    if i + 2 >= len(bars) or not _lookback_ok(bars, i, 6):
        return False
    window_hi = bars[i - 2 : i + 3]
    if bars[i]["high"] != max(b["high"] for b in window_hi):
        return False

    ref = bars[i - 6 : i - 2]
    ref_high = max(b["high"] for b in ref)
    if bars[i]["high"] >= ref_high:
        return False

    between = bars[i - 2 : i]
    between_low = min(b["low"] for b in between)
    if ref_high <= 0 or (ref_high - between_low) / ref_high * 100 < 0.15:
        return False

    return True


def is_sell_volume_stall(bars: list[dict], i: int) -> bool:
    """放量滞涨：量能相对放大 + 小实体 + 在近期高位。"""
    if not _lookback_ok(bars, i, 8):
        return False
    c = bars[i]
    prior_vol = mean(b["volume"] for b in bars[i - 5 : i])
    if prior_vol <= 0 or c["volume"] < prior_vol * 1.2:
        return False

    rng = max(c["high"] - c["low"], 1e-6)
    body = abs(c["close"] - c["open"])
    if body / rng >= 0.4:
        return False

    recent_high = max(b["close"] for b in bars[i - 8 : i])
    if recent_high <= 0 or c["close"] < recent_high * 0.995:
        return False

    return True


def is_sell_spike_top(bars: list[dict], i: int) -> bool:
    """急拉尖顶（手册外扩展）：突破日内高点 + 巨量 + 下一根开始回落。

    抓 000063 今日 13:49-14:00 那种从 35.7 急拉到 37.15 的巨阳尖顶。
    这类"大波段"手册 3 类卖点覆盖不到（不创新高不满足、大实体不是滞涨）。
    """
    if i + 2 >= len(bars) or not _lookback_ok(bars, i, 10):
        return False
    c = bars[i]

    # 突破日内最高（含当根）
    prior_high = max(b["high"] for b in bars[:i])
    if c["high"] <= prior_high:
        return False

    # 巨量：≥ 前 5 根均量 × 2.5
    prior_vol = mean(b["volume"] for b in bars[i - 5 : i])
    if prior_vol <= 0 or c["volume"] < prior_vol * 2.5:
        return False

    # 后续 1 根开始回落（确认拒绝），2 根有一根低于当根 close 即算
    later = bars[i + 1 : i + 3]
    if not any(b["close"] < c["close"] for b in later):
        return False

    return True


def is_buy_capitulate_low(bars: list[dict], i: int) -> bool:
    """急跌捶底（手册外扩展）：跌破日内低点 + 大量恐慌 + 后续 1 根反弹。

    对称于 is_sell_spike_top，抓日内急杀触底反弹的经典买点。
    """
    if i + 2 >= len(bars) or not _lookback_ok(bars, i, 10):
        return False
    c = bars[i]

    prior_low = min(b["low"] for b in bars[:i])
    if c["low"] >= prior_low:
        return False

    prior_vol = mean(b["volume"] for b in bars[i - 5 : i])
    if prior_vol <= 0 or c["volume"] < prior_vol * 1.8:
        return False

    later = bars[i + 1 : i + 3]
    if not any(b["close"] > c["close"] for b in later):
        return False

    return True


# ---------- 主入口 ----------

_BUY_DETECTORS = [
    # 手册外优先：日内极值
    ("急跌捶底", is_buy_capitulate_low),
    # 手册内
    ("缩量止跌", is_buy_shrink_bottom),
    ("不再创新低", is_buy_higher_low),
    ("回踩均价线企稳", is_buy_vwap_bounce),
]
_SELL_DETECTORS = [
    # 手册外优先：日内极值
    ("急拉尖顶", is_sell_spike_top),
    # 手册内
    ("跌破均价线", is_sell_break_vwap),
    ("冲高不创新高", is_sell_lower_high),
    ("放量滞涨", is_sell_volume_stall),
]


def _tail_suppress_start(bars: list[dict]) -> int:
    """返回 14:55 之后（含）第一个 index；没有则返回 len(bars)."""
    for j, b in enumerate(bars):
        if _hhmm(b) >= "14:55":
            return j
    return len(bars)


def detect_signals(
    bars: list[dict],
    preclose: float,
    label: str,
    code: str = "",
    min_gap: float | None = None,
    min_gap_pct: float = 0.003,
    min_gap_abs: float = 0.02,
) -> list[dict]:
    """扫描分时序列，产出编号后的买卖点。

    差价约束：每对 |Δprice| ≥ max(min_gap_abs, first_price * min_gap_pct)
    - 默认 0.3% + 0.02元 floor，兼顾贵/便宜票
    - 手册的"0.2元不做"对应中兴通讯 @36元 → 0.55%，仍属合理档位
    - 若传统 `min_gap` 被显式指定，则整段用它（向后兼容旧调用/测试）

    Returns list of dicts: {index, time, price, type, reason, seq, note}.
    """
    if not bars or preclose <= 0 or label in {"数据不足", ""}:
        return []
    if len(bars) < _MIN_INDEX + 5:
        return []

    tail_start = _tail_suppress_start(bars)

    raw: list[dict] = []
    for i in range(_MIN_INDEX, len(bars)):
        bar = bars[i]
        if _is_limit(bar, preclose, code):
            continue

        buy_hit: str | None = None
        for reason, fn in _BUY_DETECTORS:
            if i >= tail_start:
                break  # 尾盘不出 buy
            if fn(bars, i):
                buy_hit = reason
                break

        sell_hit: str | None = None
        for reason, fn in _SELL_DETECTORS:
            if fn(bars, i):
                sell_hit = reason
                break

        for stype, reason in (("buy", buy_hit), ("sell", sell_hit)):
            if reason is None:
                continue
            raw.append(
                {
                    "index": i,
                    "time": _hhmm(bar),
                    "price": round(bar["close"], 2),
                    "type": stype,
                    "reason": reason,
                }
            )

    # 主：不再按 label 丢弃对手方 —— label 只决定"先卖后买"或"先买后卖"的配对方向
    # 同类去噪：相邻 <5 根，保留优先级更高的（避免消化盘上买点连续触发）
    deduped = _dedup_same_type(raw, gap=5)

    # 关键：做 T 严格闭合 —— 每组买卖必须完成后才能开下一组，不允许时间重叠。
    # 用 DP 选 K=3 个不重叠、盈利、方向正确的对，总利润最大化。
    paired = _pair_and_limit(
        deduped, label,
        min_gap_pct=min_gap_pct, min_gap_abs=min_gap_abs,
        min_gap_override=min_gap, max_pairs=3,
    )

    # 按时间序编号（红1=最早买、绿1=最早卖），配对信息作为 partner 字段附加
    return _assign_seq(paired)


def _filter_by_label(signals: list[dict], label: str) -> list[dict]:
    """废弃：保留仅供向后引用。做T手册里"强势只倒T"指的是配对顺序（先卖后买），
    不是"只标卖点"。信号本身不按 label 丢弃对手方。"""
    return list(signals)


def _dedup_same_type(signals: list[dict], gap: int) -> list[dict]:
    """相邻 index 差 < gap 的同类信号，只保留 reason 优先级更高的."""
    out: list[dict] = []
    for s in signals:
        # 找是否已有相邻同类
        collide = None
        for j, existing in enumerate(out):
            if existing["type"] == s["type"] and abs(existing["index"] - s["index"]) < gap:
                collide = j
                break
        if collide is None:
            out.append(s)
            continue
        prev = out[collide]
        if _REASON_PRIORITY.get(s["reason"], 0) > _REASON_PRIORITY.get(prev["reason"], 0):
            out[collide] = s
    return out


def _pair_and_limit(
    signals: list[dict],
    label: str,
    min_gap_pct: float = 0.003,
    min_gap_abs: float = 0.02,
    min_gap_override: float | None = None,
    max_pairs: int = 3,
    pair_id_start: int = 1,
    # 兼容 tests 里以关键字 min_gap= 传入
    min_gap: float | None = None,
) -> list[dict]:
    """做 T 严格闭合配对：K 组不重叠、方向正确、盈利足够、总利润最大化。

    用 DP 从所有候选 (buy_i, sell_j) 对中选 K=3 组：
    - 每组内 buy 时间必须 < sell 时间（弱势/偏弱）或 sell < buy（强势/偏强）
    - 每组必须闭合：pair_A.end < pair_B.start（不允许在 pair_A 未平仓时开 pair_B）
    - sell.price - buy.price ≥ 有效 min_gap
    - 目标：3 组总盈利最大

    弱势/偏弱 → 只允许"先买后卖"（正 T）
    强势/偏强 → 只允许"先卖后买"（倒 T）
    震荡 → 两种方向都允许，每组仍需闭合
    """
    if not signals:
        return []

    override = min_gap_override if min_gap_override is not None else min_gap

    def _resolve_gap(price: float) -> float:
        if override is not None:
            return override
        return max(min_gap_abs, price * min_gap_pct)

    if label in {"强势", "偏强"}:
        allowed_dirs = [("sell", "buy")]
    elif label in {"弱势", "偏弱"}:
        allowed_dirs = [("buy", "sell")]
    else:
        allowed_dirs = [("buy", "sell"), ("sell", "buy")]

    ordered = sorted(signals, key=lambda s: s["index"])
    n = len(ordered)
    candidates: list[dict] = []
    for i in range(n):
        for j in range(i + 1, n):
            a, b = ordered[i], ordered[j]
            for first_type, second_type in allowed_dirs:
                if a["type"] != first_type or b["type"] != second_type:
                    continue
                buy_sig = a if first_type == "buy" else b
                sell_sig = b if first_type == "buy" else a
                profit = sell_sig["price"] - buy_sig["price"]
                gap = _resolve_gap(a["price"])
                if profit >= gap:
                    candidates.append({
                        "first": a,
                        "second": b,
                        "start": a["index"],
                        "end": b["index"],
                        "profit": profit,
                    })
                break  # 一个方向匹配即可

    selected = _select_non_overlapping(candidates, max_pairs)

    flat: list[dict] = []
    for offset, pair in enumerate(selected):
        pid = pair_id_start + offset
        first_sig = dict(pair["first"])
        second_sig = dict(pair["second"])
        first_sig["pair_id"] = pid
        second_sig["pair_id"] = pid
        flat.append(first_sig)
        flat.append(second_sig)
    return flat


def _select_non_overlapping(pairs: list[dict], max_k: int) -> list[dict]:
    """DP：从 pairs 中选 ≤ max_k 个不重叠对，总 profit 最大。

    经典加权区间调度 + K 个上限：按 end 排序 → bisect 找 prev 兼容 →
    dp[i][k] = max profit using first i pairs with ≤ k selected。
    """
    if not pairs or max_k <= 0:
        return []

    import bisect

    sorted_pairs = sorted(pairs, key=lambda p: p["end"])
    n = len(sorted_pairs)
    ends = [p["end"] for p in sorted_pairs]

    # prev_valid[i] = 最大 j 使得 sorted_pairs[j].end < sorted_pairs[i].start
    # 即 pair j 完全结束在 pair i 开始之前
    prev_valid: list[int] = []
    for i in range(n):
        target = sorted_pairs[i]["start"]
        j = bisect.bisect_left(ends, target) - 1
        prev_valid.append(j)

    # dp[i][k]：用 pairs[0..i-1] 选最多 k 个的最大 profit
    dp = [[0.0] * (max_k + 1) for _ in range(n + 1)]
    took = [[False] * (max_k + 1) for _ in range(n + 1)]
    for i in range(1, n + 1):
        for kk in range(max_k + 1):
            dp[i][kk] = dp[i - 1][kk]  # skip pair i-1
            took[i][kk] = False
            if kk >= 1:
                pi = prev_valid[i - 1]
                take = dp[pi + 1][kk - 1] + sorted_pairs[i - 1]["profit"]
                if take > dp[i][kk]:
                    dp[i][kk] = take
                    took[i][kk] = True

    best_k = max(range(max_k + 1), key=lambda kk: dp[n][kk])

    selected: list[dict] = []
    i, kk = n, best_k
    while i > 0 and kk > 0:
        if took[i][kk]:
            selected.append(sorted_pairs[i - 1])
            i = prev_valid[i - 1] + 1
            kk -= 1
        else:
            i -= 1

    return sorted(selected, key=lambda p: p["start"])


def _profit(buy_sig: dict, sell_sig: dict) -> float:
    """T+0 一对的利差：卖价 - 买价（正 = 盈利）."""
    return sell_sig["price"] - buy_sig["price"]


def _better_first(existing: dict, new: dict) -> dict:
    """同类新旧择优：
    - sell pending 保留价高的（倒T 卖得越高越好）
    - buy pending 保留价低的（正T 买得越低越好）
    """
    if existing["type"] == "sell":
        return new if new["price"] > existing["price"] else existing
    return new if new["price"] < existing["price"] else existing


def _enforce_min_gap(*args, **kwargs) -> list[dict]:  # noqa: ARG001
    """废弃：旧的贪心配对，改用 _pair_and_limit + _select_non_overlapping DP。"""
    raise NotImplementedError("Use _pair_and_limit instead")


def _enforce_min_gap_bidir(*args, **kwargs) -> list[dict]:  # noqa: ARG001
    """废弃：旧的贪心配对，改用 _pair_and_limit + _select_non_overlapping DP。"""
    raise NotImplementedError("Use _pair_and_limit instead")


def _assign_seq(signals: list[dict]) -> list[dict]:
    """按时间序编号（每类独立）：红1=最早的买、绿1=最早的卖。

    pair_id 保留在字段里给前端表格展示"配对"信息。
    """
    ordered = sorted(signals, key=lambda x: x["index"])

    buy_n = 0
    sell_n = 0
    out: list[dict] = []
    for s in ordered:
        s = dict(s)
        if s["type"] == "buy":
            buy_n += 1
            s["seq"] = buy_n
        else:
            sell_n += 1
            s["seq"] = sell_n
        s["marker"] = f"红{s['seq']}" if s["type"] == "buy" else f"绿{s['seq']}"
        s["note"] = f"{s['marker']} · {s['reason']} @ {s['price']:.2f}"
        # pair_id 保留供前端配对展示
        out.append(s)

    # 补一步：用 pair_id 把每根信号的 "对手 marker" 计算出来，方便前端展示
    pair_map: dict[int, list[dict]] = {}
    for s in out:
        pid = s.get("pair_id")
        if pid is not None:
            pair_map.setdefault(pid, []).append(s)
    for pid, group in pair_map.items():
        if len(group) == 2:
            group[0]["partner"] = group[1]["marker"]
            group[0]["partner_price"] = group[1]["price"]
            group[1]["partner"] = group[0]["marker"]
            group[1]["partner_price"] = group[0]["price"]
    return out
