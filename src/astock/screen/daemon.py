"""后台预警守护线程。web 起动时按 settings.yaml.alert_daemon 决定是否启."""
from __future__ import annotations

import json
import threading
import time
from datetime import datetime
from pathlib import Path

import yaml

from astock import CONFIG_DIR, DATA_DIR
from astock.config import load_config
from astock.notify import notify
from astock.screen.alerts import check_watch, load_watchlist
from astock.screen.position_monitor import check_all_positions

ALERTS_LOG = DATA_DIR / "alerts.log"


def _load_config() -> dict:
    p = CONFIG_DIR / "settings.yaml"
    if not p.exists():
        return {}
    raw = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    return raw.get("alert_daemon") or {}


def _log(entry: dict) -> None:
    ALERTS_LOG.parent.mkdir(parents=True, exist_ok=True)
    with ALERTS_LOG.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def _dispatch(hit: dict, seen: dict, dedup_window: int) -> None:
    key = (hit["code"], hit["type"], round(hit["price"], 1))
    now = time.time()
    last = seen.get(key, 0)
    if now - last < dedup_window:
        return
    seen[key] = now
    title = f"⚠️ AStock 预警：{hit['name']} {hit['type']}"
    body = (
        f"{hit['name']}（{hit['code']}）触发 {hit['type']}\n"
        f"现价 {hit['price']:.2f}，涨跌 {hit['change_pct']:+.2f}%\n"
        f"{hit['message']}\n\n{datetime.now():%Y-%m-%d %H:%M:%S}"
    )
    channels = notify(title, body)
    _log({
        "ts": datetime.now().isoformat(timespec="seconds"),
        **hit,
        "notified": channels,
    })


def _run_loop(stop_event: threading.Event, interval: int, dedup_window: int) -> None:
    seen: dict[tuple, float] = {}
    while not stop_event.wait(interval):
        # 1. 关注池
        try:
            watches = load_watchlist()
        except Exception:
            watches = []
        for w in watches:
            try:
                hits = check_watch(w)
            except Exception:
                hits = []
            for h in hits:
                _dispatch(h, seen, dedup_window)

        # 2. 持仓风险监控
        try:
            cfg = load_config()
            pos_hits = check_all_positions(cfg)
        except Exception:
            pos_hits = []
        for h in pos_hits:
            _dispatch(h, seen, dedup_window)


_daemon_thread: threading.Thread | None = None
_stop_event: threading.Event | None = None


def start() -> bool:
    """启动 daemon。返回是否真的起了。"""
    global _daemon_thread, _stop_event
    cfg = _load_config()
    if not cfg.get("enabled"):
        return False
    if _daemon_thread and _daemon_thread.is_alive():
        return True
    interval = int(cfg.get("interval_seconds", 300))
    dedup = int(cfg.get("dedup_window_seconds", 3600))
    _stop_event = threading.Event()
    _daemon_thread = threading.Thread(
        target=_run_loop, args=(_stop_event, interval, dedup),
        daemon=True, name="astock-alert-daemon",
    )
    _daemon_thread.start()
    return True


def stop() -> None:
    global _stop_event
    if _stop_event is not None:
        _stop_event.set()
