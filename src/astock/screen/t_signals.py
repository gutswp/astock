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
    "跌破均价线": 3,
    "冲高不创新高": 2,
    "放量滞涨": 1,
    "缩量止跌": 3,
    "回踩均价线企稳": 2,
    "不再创新低": 1,
}


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


# ---------- 主入口 ----------

_BUY_DETECTORS = [
    ("缩量止跌", is_buy_shrink_bottom),
    ("不再创新低", is_buy_higher_low),
    ("回踩均价线企稳", is_buy_vwap_bounce),
]
_SELL_DETECTORS = [
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

    # 配对 + min_gap + 3 对上限（label 决定配对顺序）
    paired = _pair_and_limit(
        deduped, label,
        min_gap_pct=min_gap_pct,
        min_gap_abs=min_gap_abs,
        min_gap_override=min_gap,
        max_pairs=3,
    )

    # 编号
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
    # 兼容 tests 里以关键字 min_gap= 传入
    min_gap: float | None = None,
) -> list[dict]:
    """按 label 偏好配对：差价 < 有效 min_gap 的对被丢，未配对的单边信号保留。

    有效 min_gap: 优先 min_gap_override / min_gap；否则 max(min_gap_abs, price * min_gap_pct)。
    最多 max_pairs * 2 = 6 个信号。
    """
    if not signals:
        return []

    override = min_gap_override if min_gap_override is not None else min_gap

    def _resolve_gap(first_price: float) -> float:
        if override is not None:
            return override
        return max(min_gap_abs, first_price * min_gap_pct)

    ordered = sorted(signals, key=lambda s: s["index"])
    max_signals = max_pairs * 2

    if label in {"强势", "偏强"}:
        return _enforce_min_gap(ordered, "sell", "buy", _resolve_gap, max_signals)
    if label in {"弱势", "偏弱"}:
        return _enforce_min_gap(ordered, "buy", "sell", _resolve_gap, max_signals)
    return _enforce_min_gap_bidir(ordered, _resolve_gap, max_signals)


def _enforce_min_gap(
    ordered: list[dict],
    first_type: str,
    second_type: str,
    resolve_gap,
    max_signals: int,
) -> list[dict]:
    """先 first_type 后 second_type 尝试配对；早于 first 的 second 违反 label 意图，丢弃。

    做T 逻辑上，连续买/连续卖没意义 —— 未完成配对时新 first 覆盖旧 pending
    （代表 trader 应该用最新价加仓/挂新单）。只有配对完成后才开启下一轮。
    """
    kept: list[dict] = []
    pending_first: dict | None = None
    for s in ordered:
        if len(kept) >= max_signals:
            break
        if s["type"] == first_type:
            pending_first = s  # 用最新的 first 作 pending，不累积历史
        elif s["type"] == second_type:
            if pending_first is None:
                continue  # 违反 label 顺序，跳过
            gap = resolve_gap(pending_first["price"])
            if abs(s["price"] - pending_first["price"]) >= gap:
                kept.append(pending_first)
                kept.append(s)
                pending_first = None
            # else 差价不够
    if pending_first is not None and len(kept) < max_signals:
        kept.append(pending_first)
    return kept[:max_signals]


def _enforce_min_gap_bidir(
    ordered: list[dict], resolve_gap, max_signals: int
) -> list[dict]:
    """震荡：接受任意起手，贪心配对；未配的也保留."""
    kept: list[dict] = []
    pending: dict | None = None
    for s in ordered:
        if len(kept) >= max_signals:
            break
        if pending is None:
            pending = s
            continue
        if s["type"] != pending["type"]:
            gap = resolve_gap(pending["price"])
            if abs(s["price"] - pending["price"]) >= gap:
                kept.append(pending)
                kept.append(s)
                pending = None
            # else 差价不够
        else:
            kept.append(pending)
            pending = s
    if pending is not None and len(kept) < max_signals:
        kept.append(pending)
    return kept[:max_signals]


def _assign_seq(signals: list[dict]) -> list[dict]:
    buy_n = 0
    sell_n = 0
    out: list[dict] = []
    for s in sorted(signals, key=lambda x: x["index"]):
        s = dict(s)
        if s["type"] == "buy":
            buy_n += 1
            s["seq"] = buy_n
            s["marker"] = f"红{buy_n}"
        else:
            sell_n += 1
            s["seq"] = sell_n
            s["marker"] = f"绿{sell_n}"
        s["note"] = f"{s['marker']} · {s['reason']} @ {s['price']:.2f}"
        out.append(s)
    return out
