"""持仓风险监控：跌破成本 -X% / 涨破成本 +Y% / 单日大幅波动 → 触发预警."""
from __future__ import annotations

from pathlib import Path

import yaml

from astock import CONFIG_DIR
from astock.portfolio.manager import build_portfolio


def _monitor_config() -> dict:
    p = CONFIG_DIR / "settings.yaml"
    if not p.exists():
        return {}
    raw = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    return raw.get("position_monitor") or {}


def check_all_positions(config) -> list[dict]:
    """遍历持仓，返回触发的风险事件（结构与 alerts.check_watch 兼容，可复用推送）."""
    m = _monitor_config()
    if not m.get("enabled"):
        return []

    stop_loss = float(m.get("stop_loss_pct", -20))    # 例：-20 → 亏损 20% 触发
    take_profit = float(m.get("take_profit_pct", 30))
    big_move = float(m.get("big_move_pct", 7))

    try:
        summary = build_portfolio(config)
    except Exception:
        return []

    hits: list[dict] = []
    for p in summary.positions:
        if p.profit_pct <= stop_loss:
            hits.append({
                "code": p.code, "name": p.name,
                "type": "position_stop_loss",
                "price": p.current_price,
                "change_pct": p.daily_change,
                "message": (
                    f"⚠️ 亏损 {p.profit_pct:.2f}%（成本 {p.avg_cost:.2f} → 现价 {p.current_price:.2f}），"
                    f"触及阈值 {stop_loss}%"
                ),
            })
        elif p.profit_pct >= take_profit:
            hits.append({
                "code": p.code, "name": p.name,
                "type": "position_take_profit",
                "price": p.current_price,
                "change_pct": p.daily_change,
                "message": (
                    f"✨ 盈利 {p.profit_pct:.2f}%（成本 {p.avg_cost:.2f} → 现价 {p.current_price:.2f}），"
                    f"可考虑止盈"
                ),
            })

        if abs(p.daily_change) >= big_move:
            direction = "涨" if p.daily_change > 0 else "跌"
            hits.append({
                "code": p.code, "name": p.name,
                "type": f"daily_{'up' if p.daily_change > 0 else 'down'}",
                "price": p.current_price,
                "change_pct": p.daily_change,
                "message": f"今日大幅{direction}动 {p.daily_change:+.2f}%",
            })
    return hits
