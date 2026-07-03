from dataclasses import dataclass, field
from pathlib import Path

import yaml

from astock import CONFIG_DIR
from astock.data.provider import get_hist, get_spot
from astock.screen.indicators import calc_macd, calc_ma

WATCHLIST_PATH = CONFIG_DIR / "watchlist.yaml"

ALERT_TYPES = {
    "price_above",
    "price_below",
    "stop_loss",
    "change_above",
    "change_below",
    "ma_break",
    "macd_cross",
}


@dataclass
class Alert:
    type: str
    value: float | None = None
    period: int | None = None


@dataclass
class Watch:
    code: str
    name: str = ""
    alerts: list[Alert] = field(default_factory=list)


def load_watchlist(path: Path | None = None) -> list[Watch]:
    path = path or WATCHLIST_PATH
    if not path.exists():
        return []
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    watches = []
    for w in raw.get("watches") or []:
        alerts = [Alert(**a) for a in w.get("alerts") or []]
        watches.append(Watch(code=str(w["code"]).zfill(6), name=w.get("name", ""), alerts=alerts))
    return watches


def save_watchlist(watches: list[Watch], path: Path | None = None) -> None:
    path = path or WATCHLIST_PATH
    raw = {
        "watches": [
            {
                "code": w.code,
                "name": w.name,
                "alerts": [
                    {k: v for k, v in a.__dict__.items() if v is not None}
                    for a in w.alerts
                ],
            }
            for w in watches
        ]
    }
    path.write_text(yaml.dump(raw, allow_unicode=True, default_flow_style=False), encoding="utf-8")


def add_watch_alert(code: str, alert_type: str, value: float | None, period: int | None) -> Watch:
    if alert_type not in ALERT_TYPES:
        raise ValueError(f"未知 alert type: {alert_type}. 可选: {sorted(ALERT_TYPES)}")
    code = code.zfill(6)
    watches = load_watchlist()
    target = next((w for w in watches if w.code == code), None)
    if target is None:
        name = code
        try:
            spot = get_spot([code])
            if not spot.empty:
                name = str(spot.iloc[0]["名称"])
        except Exception:
            pass
        target = Watch(code=code, name=name)
        watches.append(target)
    target.alerts.append(Alert(type=alert_type, value=value, period=period))
    save_watchlist(watches)
    return target


def remove_watch(code: str, index: int | None = None) -> None:
    code = code.zfill(6)
    watches = load_watchlist()
    for w in watches:
        if w.code == code:
            if index is None:
                watches.remove(w)
            else:
                if 0 <= index < len(w.alerts):
                    del w.alerts[index]
                if not w.alerts:
                    watches.remove(w)
            save_watchlist(watches)
            return
    raise ValueError(f"关注列表中没有 {code}")


def _macd_cross(closes) -> str | None:
    if len(closes) < 35:
        return None
    dif, dea, _ = calc_macd(closes)
    if dif.iloc[-2] < dea.iloc[-2] and dif.iloc[-1] >= dea.iloc[-1]:
        return "金叉"
    if dif.iloc[-2] > dea.iloc[-2] and dif.iloc[-1] <= dea.iloc[-1]:
        return "死叉"
    return None


def _ma_break(closes, period: int) -> str | None:
    if len(closes) < period + 1:
        return None
    ma = calc_ma(closes, period)
    import pandas as pd
    if pd.isna(ma.iloc[-1]) or pd.isna(ma.iloc[-2]):
        return None
    if closes.iloc[-2] < ma.iloc[-2] and closes.iloc[-1] >= ma.iloc[-1]:
        return f"上穿MA{period}"
    if closes.iloc[-2] > ma.iloc[-2] and closes.iloc[-1] <= ma.iloc[-1]:
        return f"跌破MA{period}"
    return None


def check_watch(watch: Watch) -> list[dict]:
    """检查一只关注股的所有 alert，返回触发列表."""
    triggered: list[dict] = []
    spot = get_spot([watch.code])
    if spot.empty:
        return triggered
    row = spot.iloc[0]
    price = float(row["最新价"])
    change_pct = float(row.get("涨跌幅", 0))

    hist_needed = any(a.type in {"ma_break", "macd_cross"} for a in watch.alerts)
    closes = None
    if hist_needed:
        try:
            hist = get_hist(watch.code, 60)
            if not hist.empty:
                closes = hist["收盘"].astype(float)
        except Exception:
            closes = None

    for a in watch.alerts:
        hit_msg: str | None = None
        if a.type == "price_above" and a.value is not None and price >= a.value:
            hit_msg = f"现价 {price:.2f} ≥ {a.value}"
        elif a.type == "price_below" and a.value is not None and price <= a.value:
            hit_msg = f"现价 {price:.2f} ≤ {a.value}"
        elif a.type == "stop_loss" and a.value is not None and price <= a.value:
            hit_msg = f"⚠️ 止损：{price:.2f} ≤ {a.value}"
        elif a.type == "change_above" and a.value is not None and change_pct >= a.value:
            hit_msg = f"涨幅 {change_pct:+.2f}% ≥ {a.value:+.2f}%"
        elif a.type == "change_below" and a.value is not None and change_pct <= a.value:
            hit_msg = f"跌幅 {change_pct:+.2f}% ≤ {a.value:+.2f}%"
        elif a.type == "ma_break" and closes is not None and a.period:
            m = _ma_break(closes, a.period)
            if m:
                hit_msg = m
        elif a.type == "macd_cross" and closes is not None:
            m = _macd_cross(closes)
            if m:
                hit_msg = f"MACD {m}"

        if hit_msg:
            triggered.append({
                "code": watch.code,
                "name": watch.name,
                "type": a.type,
                "price": price,
                "change_pct": change_pct,
                "message": hit_msg,
            })
    return triggered
