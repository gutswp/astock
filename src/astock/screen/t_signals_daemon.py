"""做T信号后台守护 + 内存快照 + 新对形成时推送。

- 交易时段（9:30-11:30 + 13:00-15:00 工作日）每 interval 秒扫全部持仓
- 拉分时（走短 TTL 缓存）→ score_opening → detect_signals
- 快照写入 SIGNALS_STATE[code]，供 SSE 端点读取
- 每形成一个新的完整 buy-sell 对时，走 notify 推送（飞书 / Server酱 / 邮件）
- dedup: 同一 (code, date, buy_time, sell_time) 只推一次
- 非交易时段静默 sleep
"""
from __future__ import annotations

import threading
from collections import defaultdict
from datetime import datetime, time as dtime
from pathlib import Path
from typing import Any

import yaml

from astock import CONFIG_DIR
from astock.config import AppConfig, load_config
from astock.data.provider import get_intraday_cached
from astock.notify.dispatch import notify
from astock.portfolio.manager import _collect_holdings
from astock.screen.t_signals import detect_signals
from astock.screen.t_trading import score_opening

# code -> {"result": <score dict>, "signals": [...], "updated_at": iso_time}
SIGNALS_STATE: dict[str, dict[str, Any]] = {}
_STATE_LOCK = threading.Lock()

# 名称缓存：code -> name
_NAME_MAP: dict[str, str] = {}

# 已推送去重：(code, date_str, bar_time, type) → True
_PUSHED_PAIRS: set[tuple] = set()
_PUSHED_PAIRS_DATE: str | None = None
_WARMED_UP: set[str] = set()  # 已完成"预热"的 code：首次扫时静默填充 dedup，不推
# 每 (code, date, type) 已推过的最优价：新 push 需比历史新低更低 / 新高更高
_LAST_EXTREME: dict[tuple, float] = {}
_PUSH_LOCK = threading.Lock()

# 价格差阈值：新信号必须比历史极值好 0.3% 才推
_EXTREME_THRESHOLD_PCT = 0.003

_daemon_thread: threading.Thread | None = None
_stop_event: threading.Event | None = None

_AM_START = dtime(9, 30)
_AM_END = dtime(11, 30)
_PM_START = dtime(13, 0)
_PM_END = dtime(15, 0)

_DEFAULT_INTERVAL = 5
_DEFAULT_TTL = 3
_DEFAULT_SSE_POLL = 1


def _load_daemon_config() -> dict:
    p: Path = CONFIG_DIR / "settings.yaml"
    if not p.exists():
        return {}
    raw = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    return raw.get("signals_daemon") or {}


def get_intraday_ttl() -> int:
    return int(_load_daemon_config().get("intraday_ttl_seconds", _DEFAULT_TTL))


def get_sse_poll_seconds() -> float:
    return float(_load_daemon_config().get("sse_poll_seconds", _DEFAULT_SSE_POLL))


def _should_push_pairs() -> bool:
    """settings.yaml::notify.push_tscore_pairs 开关."""
    p = CONFIG_DIR / "settings.yaml"
    if not p.exists():
        return False
    try:
        raw = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
        return bool((raw.get("notify") or {}).get("push_tscore_pairs"))
    except Exception:
        return False


def _reset_pushed_if_new_day() -> None:
    """新交易日清空去重集合 + 预热标记 + 极值追踪."""
    global _PUSHED_PAIRS_DATE
    today = datetime.now().strftime("%Y-%m-%d")
    with _PUSH_LOCK:
        if _PUSHED_PAIRS_DATE != today:
            _PUSHED_PAIRS.clear()
            _WARMED_UP.clear()
            _LAST_EXTREME.clear()
            _PUSHED_PAIRS_DATE = today


def _is_new_extreme(code: str, date_str: str, stype: str, price: float) -> bool:
    """判断是否新极值：buy 需比历史新低更低、sell 需比历史新高更高。"""
    key = (code, date_str, stype)
    with _PUSH_LOCK:
        current = _LAST_EXTREME.get(key)
        if current is None:
            _LAST_EXTREME[key] = price
            return True
        if stype == "buy":
            if price < current * (1 - _EXTREME_THRESHOLD_PCT):
                _LAST_EXTREME[key] = price
                return True
        else:  # sell
            if price > current * (1 + _EXTREME_THRESHOLD_PCT):
                _LAST_EXTREME[key] = price
                return True
    return False


def _format_signal(code: str, snap: dict[str, Any], sig: dict) -> tuple[str, str]:
    """格式化单个信号推送 (title, body)。含对手方（如果已配对）。"""
    name = _NAME_MAP.get(code, code)
    label = snap.get("label", "")
    current = snap.get("current", 0.0)
    change_pct = snap.get("change_pct", 0.0)

    action = "买入" if sig["type"] == "buy" else "卖出"
    emoji = "🔴" if sig["type"] == "buy" else "🟢"

    title = f"{emoji} {name} {code} {action} @{sig['price']:.2f}"

    lines = [
        f"**{label}** · 现价 **{current:.2f}** ({change_pct:+.2f}%)",
        "",
        f"{emoji} **{action}信号** @ **{sig['price']:.2f}**",
        "",
        f"时间 {sig['time']} · 依据 **{sig['reason']}**",
    ]

    # 配对信息
    partner = sig.get("partner")
    partner_price = sig.get("partner_price")
    if partner and partner_price:
        profit = (partner_price - sig["price"]) if sig["type"] == "buy" else (sig["price"] - partner_price)
        profit_pct = profit / min(sig["price"], partner_price) * 100
        lines.append("")
        lines.append(f"配对 → **{partner}** @ {partner_price:.2f}")
        lines.append(f"**Δ {profit:+.2f} 元 ({profit_pct:+.2f}%)** · 1000 股 ≈ **{profit*1000:+.0f}** 元")

    lines.append("")
    lines.append(f"⚡ **立即执行**（做T仓 1000 股）")

    return title, "\n".join(lines)


def _push_new_signals(code: str, snap: dict[str, Any]) -> None:
    """从 DP-selected snapshot signals 推送新出现的信号。

    daemon 每 5s 扫一次，比较当前 vs 上次 snapshot，推送新增的信号（同一
    信号只推一次）。DP 天然限制 3-6 对/天 = 6-12 push/单只票，量可控。

    dedup key: (code, date, bar_time, type)。
    首次调用 warmup：填 dedup 集合，不推 —— 防 daemon 启动/重启时轰炸。
    """
    if not _should_push_pairs():
        return
    signals = snap.get("signals") or []
    if not signals:
        return

    _reset_pushed_if_new_day()
    date_str = datetime.now().strftime("%Y-%m-%d")

    is_warmup = code not in _WARMED_UP
    if is_warmup:
        _WARMED_UP.add(code)

    def _bucket(hhmm: str, minutes: int = 15) -> int:
        """把 HH:MM 归到 minutes 分钟桶。同一 15min 窗口内同类信号只推 1 次。"""
        hh, mm = int(hhmm[:2]), int(hhmm[3:5])
        return (hh * 60 + mm) // minutes

    for s in signals:
        # 15 分钟桶 dedup：DP 每 5s 重选可能反复推同一 pair 的不同版本 buy
        # 用 15 min 桶把它们合并为一条推送
        key = (code, date_str, _bucket(s["time"]), s["type"])
        with _PUSH_LOCK:
            if key in _PUSHED_PAIRS:
                continue
            _PUSHED_PAIRS.add(key)
        if is_warmup:
            continue  # 预热：只填 dedup，不推
        try:
            title, body = _format_signal(code, snap, s)
            notify(title, body)
        except Exception:
            pass


def is_trading_hours(now: datetime | None = None) -> bool:
    now = now or datetime.now()
    if now.weekday() >= 5:  # 周六 / 周日
        return False
    t = now.time()
    return (_AM_START <= t <= _AM_END) or (_PM_START <= t <= _PM_END)


def _compute_one(code: str, ttl: int | None = None) -> dict[str, Any] | None:
    try:
        bars, preclose = get_intraday_cached(code, ttl=ttl or get_intraday_ttl())
    except Exception:
        return None
    if not bars or preclose <= 0:
        return None
    scored = score_opening(bars, preclose)
    label = scored.get("label", "")
    signals = detect_signals(bars, preclose, label, code=code)
    snap = {
        "code": code,
        "label": label,
        "score": scored.get("score", 0),
        "current": scored.get("current", 0.0),
        "preclose": preclose,
        "change_pct": scored.get("change_pct", 0.0),
        "times": [b["time"][11:16] for b in bars],
        "closes": [round(b["close"], 2) for b in bars],
        "vwaps": [round(b["vwap"], 2) for b in bars],
        "signals": signals,
        "updated_at": datetime.now().isoformat(timespec="seconds"),
    }

    # DP 输出里出现的新信号立即推送（每信号推一次，含配对信息）
    try:
        _push_new_signals(code, snap)
    except Exception:
        pass

    return snap


def _run_loop(stop_event: threading.Event, interval: int, ttl: int, config: AppConfig) -> None:
    holdings = _collect_holdings(config)
    codes = list({h.code for h in holdings})
    # 缓存名称，供推送时使用
    for h in holdings:
        _NAME_MAP.setdefault(h.code, h.name)

    while not stop_event.wait(interval):
        if not is_trading_hours():
            continue
        for code in codes:
            snap = _compute_one(code, ttl=ttl)
            if snap is None:
                continue
            with _STATE_LOCK:
                SIGNALS_STATE[code] = snap


def get_snapshot(code: str) -> dict[str, Any] | None:
    with _STATE_LOCK:
        snap = SIGNALS_STATE.get(code)
        return dict(snap) if snap else None


def compute_now(code: str) -> dict[str, Any] | None:
    """按需即时算一次并写回快照（供 SSE 首次连接时预填）."""
    snap = _compute_one(code)
    if snap is None:
        return None
    with _STATE_LOCK:
        SIGNALS_STATE[code] = snap
    return snap


def start(config: AppConfig | None = None, interval: int | None = None) -> bool:
    global _daemon_thread, _stop_event
    if _daemon_thread and _daemon_thread.is_alive():
        return True
    cfg = config or load_config()
    dcfg = _load_daemon_config()
    if interval is None:
        interval = int(dcfg.get("interval_seconds", _DEFAULT_INTERVAL))
    ttl = int(dcfg.get("intraday_ttl_seconds", _DEFAULT_TTL))
    _stop_event = threading.Event()
    _daemon_thread = threading.Thread(
        target=_run_loop, args=(_stop_event, interval, ttl, cfg),
        daemon=True, name="astock-signals-daemon",
    )
    _daemon_thread.start()
    return True


def stop() -> None:
    global _stop_event
    if _stop_event is not None:
        _stop_event.set()
