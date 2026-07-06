"""做T信号后台守护 + 内存快照。

- 交易时段（9:30-11:30 + 13:00-15:00 工作日）每 interval 秒扫全部持仓
- 拉分时（走 30s 缓存）→ score_opening → detect_signals
- 快照写入 SIGNALS_STATE[code]，供 SSE 端点读取
- 非交易时段静默 sleep
"""
from __future__ import annotations

import threading
import time
from datetime import datetime, time as dtime
from typing import Any

from astock.config import AppConfig, load_config
from astock.data.provider import get_intraday_cached
from astock.portfolio.manager import _collect_holdings
from astock.screen.t_signals import detect_signals
from astock.screen.t_trading import score_opening

# code -> {"result": <score dict>, "signals": [...], "updated_at": iso_time}
SIGNALS_STATE: dict[str, dict[str, Any]] = {}
_STATE_LOCK = threading.Lock()

_daemon_thread: threading.Thread | None = None
_stop_event: threading.Event | None = None

_AM_START = dtime(9, 30)
_AM_END = dtime(11, 30)
_PM_START = dtime(13, 0)
_PM_END = dtime(15, 0)


def is_trading_hours(now: datetime | None = None) -> bool:
    now = now or datetime.now()
    if now.weekday() >= 5:  # 周六 / 周日
        return False
    t = now.time()
    return (_AM_START <= t <= _AM_END) or (_PM_START <= t <= _PM_END)


def _compute_one(code: str) -> dict[str, Any] | None:
    try:
        bars, preclose = get_intraday_cached(code, ttl=30)
    except Exception:
        return None
    if not bars or preclose <= 0:
        return None
    scored = score_opening(bars, preclose)
    label = scored.get("label", "")
    signals = detect_signals(bars, preclose, label, code=code)
    return {
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


def _run_loop(stop_event: threading.Event, interval: int, config: AppConfig) -> None:
    holdings = _collect_holdings(config)
    codes = list({h.code for h in holdings})
    while not stop_event.wait(interval):
        if not is_trading_hours():
            continue
        for code in codes:
            snap = _compute_one(code)
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


def start(config: AppConfig | None = None, interval: int = 30) -> bool:
    global _daemon_thread, _stop_event
    if _daemon_thread and _daemon_thread.is_alive():
        return True
    cfg = config or load_config()
    _stop_event = threading.Event()
    _daemon_thread = threading.Thread(
        target=_run_loop, args=(_stop_event, interval, cfg),
        daemon=True, name="astock-signals-daemon",
    )
    _daemon_thread.start()
    return True


def stop() -> None:
    global _stop_event
    if _stop_event is not None:
        _stop_event.set()
