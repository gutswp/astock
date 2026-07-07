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
from astock.screen.t_signals import detect_signals_online, iter_online_signals, new_online_state
from astock.screen.t_trading import score_opening

# code -> {"result": <score dict>, "signals": [...], "updated_at": iso_time}
SIGNALS_STATE: dict[str, dict[str, Any]] = {}
_STATE_LOCK = threading.Lock()

# 名称缓存：code -> name
_NAME_MAP: dict[str, str] = {}

_PUSHED_PAIRS_DATE: str | None = None
_WARMED_UP: set[str] = set()  # 已完成"预热"的 code：首次扫只推进状态、不推，防重启轰炸
# 每个 code 的在线检测状态（因果式状态机，供实时推送）
_ONLINE_STATE: dict[str, dict] = {}
_PUSH_LOCK = threading.Lock()

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
    """新交易日清空预热标记 + 在线检测状态."""
    global _PUSHED_PAIRS_DATE
    today = datetime.now().strftime("%Y-%m-%d")
    with _PUSH_LOCK:
        if _PUSHED_PAIRS_DATE != today:
            _WARMED_UP.clear()
            _ONLINE_STATE.clear()
            _PUSHED_PAIRS_DATE = today


def _format_signal(code: str, snap: dict[str, Any], sig: dict) -> tuple[str, str]:
    """格式化单个在线信号推送 (title, body)。含配对盈利信息。"""
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
        f"{emoji} **{sig.get('marker', action)} · {action}** @ **{sig['price']:.2f}**",
        "",
        f"时间 {sig['time']} · 依据 **{sig['reason']}**",
    ]

    partner = sig.get("partner")
    partner_price = sig.get("partner_price")
    if partner and partner_price:
        profit = (partner_price - sig["price"]) if sig["type"] == "buy" else (sig["price"] - partner_price)
        profit_pct = profit / min(sig["price"], partner_price) * 100
        lines.append("")
        lines.append(f"平T配对 → **{partner}** @ {partner_price:.2f}")
        lines.append(f"**Δ {profit:+.2f} 元 ({profit_pct:+.2f}%)** · 1000 股 ≈ **{profit*1000:+.0f}** 元")

    lines.append("")
    lines.append("⚡ **立即执行**（做T仓 1000 股）")

    return title, "\n".join(lines)


def _push_online_signals(code: str, snap: dict[str, Any], bars: list[dict], preclose: float, label: str) -> None:
    """因果式实时推送：只把刚收完的 bar 走一遍在线状态机，触发即推。

    与旧的 DP-diff 推送不同：不回头改历史、买卖天然交替，signal 时间永远是
    最新那根 bar（滞后仅 2 分钟确认延迟）。首次扫 warmup：只推进状态、不推，
    防 daemon 启动/重启时把当天已发生的信号一次性轰炸出去。
    """
    if not _should_push_pairs():
        return
    if not bars or preclose <= 0 or label in {"数据不足", ""}:
        return

    _reset_pushed_if_new_day()
    today = datetime.now().strftime("%Y-%m-%d")

    with _PUSH_LOCK:
        state = _ONLINE_STATE.get(code)
        if state is None or state.get("date") != today:
            state = new_online_state()
            state["date"] = today
            _ONLINE_STATE[code] = state
        is_warmup = code not in _WARMED_UP
        emitted = iter_online_signals(bars, preclose, label, code, state)
        if is_warmup:
            _WARMED_UP.add(code)
            emitted = []  # 预热：状态已推进到当前，但本轮不推

    for s in emitted:
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
    signals = detect_signals_online(bars, preclose, label, code=code)
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

    # 实时推送走因果式在线检测（DP 输出仅用于网页/回测展示）
    try:
        _push_online_signals(code, snap, bars, preclose, label)
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
