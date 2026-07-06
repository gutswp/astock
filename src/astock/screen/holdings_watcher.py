"""盯盘模式：盘中循环刷新持仓价格，异动触发终端 + macOS 通知."""
from __future__ import annotations

import shutil
import subprocess
import time
from datetime import datetime

from rich.console import Console
from rich.live import Live
from rich.table import Table

from astock.config import AppConfig
from astock.data import cache as _cache
from astock.data.provider import get_spot
from astock.portfolio.manager import _collect_holdings


def _osascript_notify(title: str, subtitle: str, message: str) -> None:
    if not shutil.which("osascript"):
        return
    script = f'display notification "{message}" with title "{title}" subtitle "{subtitle}"'
    try:
        subprocess.run(["osascript", "-e", script], timeout=5, check=False)
    except Exception:
        pass


def _build_table(
    positions: list[dict],
    alerts: list[str],
    ts: str,
    refresh_count: int,
) -> Table:
    table = Table(
        title=f"盯盘 {ts}  (第 {refresh_count} 次刷新)",
        show_header=True,
        header_style="bold",
        expand=True,
        title_style="dim",
    )
    table.add_column("股票", style="bold", ratio=3)
    table.add_column("代码", ratio=2)
    table.add_column("现价", justify="right", ratio=2)
    table.add_column("涨跌%", justify="right", ratio=2)
    table.add_column("持股", justify="right", ratio=2)
    table.add_column("市值", justify="right", ratio=2)
    table.add_column("盈亏%", justify="right", ratio=2)
    table.add_column("异动", ratio=4)

    for p in positions:
        change = p["change_pct"]
        if change > 0:
            chg_str = f"[red]+{change:.2f}%[/red]"
        elif change < 0:
            chg_str = f"[green]{change:.2f}%[/green]"
        else:
            chg_str = "0.00%"

        profit_pct = p["profit_pct"]
        if profit_pct > 0:
            pnl_str = f"[red]+{profit_pct:.2f}%[/red]"
        elif profit_pct < 0:
            pnl_str = f"[green]{profit_pct:.2f}%[/green]"
        else:
            pnl_str = "0.00%"

        mv = p["market_value"]
        mv_str = f"{mv / 10000:.2f}万" if abs(mv) >= 10000 else f"{mv:.0f}"

        flag = p.get("flag", "")
        flag_str = f"[bold red]{flag}[/bold red]" if flag else "[dim]-[/dim]"

        table.add_row(
            p["name"], p["code"],
            f"{p['price']:.3f}", chg_str,
            str(p["shares"]), mv_str,
            pnl_str, flag_str,
        )

    if alerts:
        table.caption = " | ".join(alerts[-5:])
        table.caption_style = "bold yellow"

    return table


def _detect_anomalies(
    positions: list[dict],
    change_threshold: float,
    seen: set[str],
) -> tuple[list[str], list[dict]]:
    new_alerts: list[str] = []
    notify_items: list[dict] = []

    for p in positions:
        flags = []
        change = abs(p["change_pct"])
        if change >= change_threshold:
            direction = "涨" if p["change_pct"] > 0 else "跌"
            flags.append(f"大幅{direction} {p['change_pct']:+.2f}%")

        if flags:
            p["flag"] = " ".join(flags)
            for f in flags:
                key = f"{p['code']}:{f}"
                if key not in seen:
                    seen.add(key)
                    msg = f"{p['name']}({p['code']}) {f}"
                    new_alerts.append(msg)
                    notify_items.append({"name": p["name"], "code": p["code"], "msg": msg})
        else:
            p["flag"] = ""

    return new_alerts, notify_items


def run_holdings_watch(
    config: AppConfig,
    interval: int = 30,
    change_threshold: float = 3.0,
    notify: bool = True,
) -> None:
    console = Console()
    holdings = _collect_holdings(config)
    if not holdings:
        console.print("[yellow]持仓为空，无法盯盘[/yellow]")
        return

    codes = list({h.code for h in holdings})
    shares_map: dict[str, int] = {}
    cost_value_map: dict[str, float] = {}
    name_map: dict[str, str] = {}
    for h in holdings:
        shares_map[h.code] = shares_map.get(h.code, 0) + h.shares
        cost_value_map[h.code] = cost_value_map.get(h.code, 0) + h.shares * h.cost
        name_map[h.code] = h.name
    cost_map = {c: cost_value_map[c] / shares_map[c] for c in codes if shares_map[c]}

    console.print(
        f"[dim]盯盘模式：{len(codes)} 只持仓股，"
        f"每 {interval}s 刷新，涨跌超 {change_threshold}% 报警，"
        f"Ctrl+C 停止[/dim]"
    )

    seen_alerts: set[str] = set()
    all_alert_msgs: list[str] = []
    refresh_count = 0

    try:
        with Live(console=console, refresh_per_second=1) as live:
            while True:
                refresh_count += 1
                ts = datetime.now().strftime("%H:%M:%S")

                try:
                    spot_key = f"spot_{'_'.join(sorted(codes))}"
                    _cache._cache_path(spot_key).unlink(missing_ok=True)
                    spot_df = get_spot(codes)
                except Exception as e:
                    live.update(Table(title=f"[red]拉取行情失败: {e}[/red]"))
                    time.sleep(interval)
                    continue

                price_map: dict[str, float] = {}
                change_map: dict[str, float] = {}
                if not spot_df.empty:
                    for _, row in spot_df.iterrows():
                        price_map[row["代码"]] = row["最新价"]
                        change_map[row["代码"]] = row.get("涨跌幅", 0)

                positions = []
                for code in codes:
                    price = price_map.get(code, 0)
                    shares = shares_map[code]
                    avg_cost = cost_map[code]
                    mv = price * shares
                    profit_pct = ((price - avg_cost) / avg_cost * 100) if avg_cost else 0
                    positions.append({
                        "code": code,
                        "name": name_map.get(code, code),
                        "price": price,
                        "change_pct": change_map.get(code, 0),
                        "shares": shares,
                        "market_value": mv,
                        "profit_pct": profit_pct,
                    })

                positions.sort(key=lambda x: x["market_value"], reverse=True)

                new_alerts, notify_items = _detect_anomalies(
                    positions, change_threshold, seen_alerts,
                )
                all_alert_msgs.extend(new_alerts)

                if notify and notify_items:
                    for item in notify_items:
                        _osascript_notify(
                            title="AStock 盯盘",
                            subtitle=f"{item['name']} ({item['code']})",
                            message=item["msg"],
                        )

                table = _build_table(positions, all_alert_msgs, ts, refresh_count)
                live.update(table)

                time.sleep(interval)

    except KeyboardInterrupt:
        console.print("\n[dim]盯盘结束[/dim]")
